import argparse
import atexit
import multiprocessing
import os
import contextlib
import subprocess
import sys
import time
from datetime import datetime

from qikly.paths import ENV_VAR, chdir_to_project_root

# Module scope, not inside __main__: every path constant in orchestrator.py,
# agent_interface.py, etc. is relative to this. On Windows, multiprocessing's
# spawn start method re-imports this module fresh in each child process (as
# "__mp_main__", not "__main__") without re-running the __main__ guard below
# -- putting the chdir here, rather than only inside that guard, is what
# makes it happen in child processes too, not just the parent. A spawned
# child inherits the parent's working directory, so it re-resolves to the
# same root the parent already selected.
# Where the user actually invoked us, captured before the chdir below moves
# us to the project root. --init and --scaffold are the commands a person runs
# to CREATE a project, so they must act on the directory the person is standing
# in, not on whichever project root the resolver happened to find.
INVOKED_FROM = os.getcwd()

PROJECT_ROOT = chdir_to_project_root()

# Edit this to pin a seed directly instead of using the AGENT_SEED env var.
# The env var takes precedence over this when set.
HARDCODED_SEED = 42  # None

# --demo defaults to the task that converges fastest and most reliably (91%
# of 43 runs, median 2 FIX iterations, ~55 test executions), because the
# point of the demo is that a first-time reader watches the whole loop
# finish inside a minute. Any task can be demoed with --demo --tasks <id>.
DEMO_TASK = "CALC_TAX"
DEMO_DIR = "demo"


HEARTBEAT_SECONDS = 300


def _heartbeat(task_id, every=HEARTBEAT_SECONDS):
    """
    Say the process is alive, every `every` seconds, until the run ends.

    A converging run takes under two minutes, so this normally prints nothing
    at all. It exists for the case where something has gone wrong: a sweep once
    sat silent for two hours with four live processes and no output, and there
    was no way to tell a slow model call from a dead connection without
    checking the clock. Provider calls now time out, which removes the known
    cause, but "the process is not answering" should be visible rather than
    inferred.

    A daemon thread, so it can never hold the process open. It reports elapsed
    time only: anything more would need state from the orchestrator and this
    has to be safe to start before the orchestrator exists.
    """
    import threading
    import time

    started = time.monotonic()
    stop = threading.Event()

    def tick():
        while not stop.wait(every):
            minutes = (time.monotonic() - started) / 60.0
            print(f"still running, {minutes:.0f} minutes elapsed", flush=True)

    thread = threading.Thread(target=tick, name=f"heartbeat-{task_id}", daemon=True)
    thread.start()
    return stop


def _run_task_process(task_id, seed, generate_criteria, resume=False):
    """
    Entry point for one task's process. Prefixes every print() with the
    task_id, since when multiple tasks run concurrently their stdout
    interleaves line by line -- without a prefix there'd be no way to tell
    which task a given line belongs to.
    """
    import builtins
    real_print = builtins.print
    prefix = f"[{task_id}]"
    builtins.print = lambda *args, **kwargs: real_print(prefix, *args, **kwargs)

    heartbeat = _heartbeat(task_id)

    from qikly.orchestrator.orchestrator import orchestrate, generate_and_write_acceptance_criteria_if_missing
    from qikly.orchestrator.reports.report import generate_report
    from qikly.orchestrator.reports.metrics_report import generate_metrics_report
    from qikly.orchestrator.run_summary import record

    # Explicit opt-in only (--generate-criteria) -- without it, a task
    # missing acceptance_criteria just gets orchestrate()'s own warning and
    # runs as-is. See generate_and_write_acceptance_criteria_if_missing()'s
    # docstring for why writing to the real task file is the right call
    # here specifically, unlike the read-only orchestrator/tuning/ scripts.
    if generate_criteria:
        generate_and_write_acceptance_criteria_if_missing(task_id, seed=seed)

    failed = False
    try:
        orchestrate(task_id, seed=seed, resume=resume)
    except RuntimeError as e:
        print(f"Run failed: {e}")
        failed = True
    except Exception as e:
        # Anything that isn't already an actionable RuntimeError. Without
        # this the exception escapes into multiprocessing, which prints the
        # raw traceback -- for a dropped network connection that is sixty
        # lines through httpx, httpcore and a retry library, with the one
        # useful word buried in the middle. Keep the traceback available,
        # but behind a flag, so the default output stays readable.
        print(f"Run failed: {type(e).__name__}: {e}")
        if os.environ.get("QIKLY_TRACEBACK"):
            import traceback
            traceback.print_exc()
        else:
            print("Set QIKLY_TRACEBACK=1 to see the full traceback.")
        failed = True

    heartbeat.set()

    # Reports replay a run's log, so they need one to exist. A stalled run
    # has a log and is often the more instructive artifact, so failure alone
    # is no reason to skip them. A run that died before writing anything --
    # no network, bad key -- has nothing to replay, and three "no transaction
    # log found" errors would only bury the one message that matters.
    from qikly.orchestrator import orchestrator as _orch
    log_path = getattr(_orch, "TRANSACTIONS_PATH", None)
    if not (log_path and os.path.exists(log_path)):
        if failed:
            print("No run log was written, so there is nothing to report on.")
        sys.exit(1 if failed else 0)

    try:
        report_path = generate_report(task_id)
        print(f"Report: {report_path}")
    except Exception as e:
        print(f"Report generation failed: {e}")

    try:
        metrics_path = generate_metrics_report(task_id)
        print(f"Metrics: {metrics_path}")
    except Exception as e:
        print(f"Metrics report generation failed: {e}")

    # Always written, like the two reports above -- it's the same numbers in a
    # form a script can read. It was briefly opt-in behind a `telemetry` setting,
    # which was wrong twice over: the name implied it was sent somewhere (it
    # isn't -- there's no network call in this codebase), and gating a local
    # file write behind consent implied there was something to consent to.
    try:
        summary_path = record(task_id)
        if summary_path:
            print(f"Run summary: {summary_path}")
    except Exception as e:
        print(f"Run summary generation failed: {e}")

    # The one artifact here that another system reads. Test management tools
    # and CI servers ingest JUnit XML, so this is what lets a generated suite
    # be filed as evidence against the ticket its criteria came from, rather
    # than staying inside this project's own reports.
    try:
        from qikly.agent_tools import junit
        from qikly.orchestrator import orchestrator as _o
        junit_path = junit.merge(task_id, getattr(_o, "RUN_TIMESTAMP", None),
                                 getattr(_o, "RUN_STAGES", ()))
        if junit_path:
            print(f"JUnit XML: {junit_path}")
    except Exception as e:
        print(f"JUnit XML generation failed: {e}")

    try:
        from qikly.agent_api.usage import USAGE, write_record
        print(USAGE.summary())
        for line in USAGE.breakdown():
            print(line)
        # On disk as well as on screen. Each task runs in its own process, so
        # the printed line is the only record a parent would otherwise have,
        # and by then it is text rather than numbers.
        write_record(task_id)
    except Exception:
        pass

    if failed:
        sys.exit(1)

    print("All tests passed.")


def _demo_root(where=None):
    """
    A fresh <somewhere>/demo/<timestamp>/ for this run, and where that is.

    Default is the directory you invoked from, NOT the resolved project root.
    Those differ exactly when you are standing outside a project, which is the
    common case for a demo: `cd C:\Temp\scratch && qikly --demo` used to write
    into the qikly checkout instead, because the root resolver walks up looking
    for inputs_private/ and falls back to the source tree. `--init` had the
    same bug and was fixed the same way.

    Nothing here needs a project root anyway. The demo runs on a bundled task
    whose inputs travel inside the package, and it hands the child its own
    QIKLY_PROJECT_ROOT pointing at this directory.

    `--demo-dir` overrides it. A relative path is taken from where you are
    standing, for the same reason.
    """
    base = INVOKED_FROM
    if where:
        base = where if os.path.isabs(where) else os.path.join(INVOKED_FROM, where)
        return os.path.join(os.path.abspath(base),
                            datetime.now().strftime("%Y%m%d_%H%M%S"))
    return os.path.join(base, DEMO_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))


class _Tee:
    """
    Write to the terminal and the demo's console log at the same time.

    The demo's console output is the thing a first-time reader actually
    watches, and until now it was the one artifact the run did not keep:
    the record, reports and per-stage summaries were all on disk, but
    what scrolled past was gone. That is the part someone pastes into an
    issue, a README, or a post.
    """

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle

    def write(self, data):
        self._stream.write(data)
        self._handle.write(data)
        return len(data)

    def flush(self):
        self._stream.flush()
        self._handle.flush()


def _demo_facts(demo_root, task_id):
    """
    Gather what went in and what came out, for the demo's closing summary.
    Best-effort by design: every lookup is guarded, because a missing file
    should cost a line of the summary, never the run's real exit status.
    """
    import glob, json
    f = {"reqs": None, "crits": None, "spec": None, "fixtures": [], "impl": [],
         "impl_lines": 0, "suites": {}, "log": None, "events": 0, "patches": 0,
         "reports": [], "calls": 0}

    try:
        import yaml
        from qikly.agent_api.agent_interface import task_config_path
        f["spec"] = task_config_path(task_id)
        with open(f["spec"], encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        f["reqs"] = len(cfg.get("requirements") or [])
        f["crits"] = len(cfg.get("acceptance_criteria") or [])
    except Exception:
        pass

    out = os.path.join(demo_root, "outputs")
    f["fixtures"] = sorted(glob.glob(os.path.join(demo_root, "inputs_private", "data", task_id, "*")))

    # .orig files are GNU patch's backups, not written work.
    for p in sorted(glob.glob(os.path.join(out, "agent_src", "code", task_id, "*.py"))):
        f["impl"].append(p)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                f["impl_lines"] += sum(1 for _ in fh)
        except Exception:
            pass

    f["patches"] = len(glob.glob(os.path.join(out, "logs", "patches", task_id, "*", "*.diff")))
    f["reports"] = sorted(glob.glob(os.path.join(out, "reports", "*", "*.html")))

    logs = sorted(glob.glob(os.path.join(out, "logs", f"transactions_{task_id}_*.jsonl")))
    if logs:
        f["log"] = logs[-1]
        last_total = {}
        try:
            with open(f["log"], encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip().startswith("{"):
                        continue
                    e = json.loads(line)
                    f["events"] += 1
                    a = e.get("action")
                    if a in ("agent_fix_requested", "agent_patch_requested", "tests_generated"):
                        f["calls"] += 1
                    if a == "test_run" and not e.get("is_regression_check") and not e.get("is_bootstrap"):
                        total = (e.get("counts") or {}).get("total")
                        if total:
                            last_total[e.get("stage")] = total
        except Exception:
            pass
        f["suites"] = last_total
    return f


# Convergence rates from the 427-run sweep of 14 August 2026, on
# gemini-3.5-flash-lite. HISTORICAL ONLY: nothing reads this any more.
#
# These numbers are sound, and were doubted for half a day. A re-measurement on
# 30 August returned 30% for CALC_TAX against the 91% here, which looked like a
# hosted model changing silently under a stable name. It was not. A local
# settings override, test_generation.criteria_per_batch = 4, had been left on
# from an experiment; it triples the generated suite sizes, so every run was
# clearing a bar three times the height. With it off, the same sweep returned
# 90% for CALC_TAX and 63% on average against this table's 59%, with 9 of 10
# tasks inside their intervals.
#
# The lesson stands even though the drift did not: a stored rate is a claim
# about a configuration as much as about a tool, and this table could not say
# which configuration it came from. The demo now explains that instead of
# printing a number.
_MEASURED_RATES_2026_08_14 = {
    "CALC_TAX": 91, "CALC_DISCOUNT": 79, "ETL_EMAIL": 72, "MERGE_SALES": 72,
    "CALC_CALENDAR": 63, "ETL_ADDRESS": 60, "AGG_RUNLOG": 51,
    "ETL_NAME_SPLIT": 37, "MERGE_STOCK": 33, "MERGE_CONTACTS": 32,
}


def _print_demo_note(task_ids, converged):
    """
    What the reader just watched, and what it does and does not prove.

    Without this the demo is a wall of passing tests, which is the least
    interesting reading of it: the point is not that tests passed, it is
    that they were written from a standard the code's author never saw.
    """
    print()
    print("  WHAT THIS DEMONSTRATED")
    print("    Every failure above was real. The coding agent had to infer the")
    print("    rule it had broken from a failing test's output alone, having")
    print("    never been shown the rule, as the header at the top set out.")
    print()
    print("    The record holds the whole loop: a first run against no code at")
    print("    all, each stage cleared in order, a FIX (the reasoning) and a")
    print("    PATCH (the diff) per failure, and earlier stages re-run whenever")
    print("    a later one changed the code.")

    if not converged:
        print()
        print("    This run stopped without converging, and nothing shipped: non-zero")
        print("    exit, the blocking tests named, the full record kept. There is no")
        print("    path by which it reports success on code its own tests reject.")

    print()
    print("    One run is an artifact, not a rate, and a rate belongs to a model")
    print("    and a configuration as much as to a tool. Measure your own with")
    print("    `run_all --repeat N`; every run summary records the settings that")
    print("    produced it.")


def _print_demo_facts(demo_root, task_id, elapsed):
    """The INPUTS/OUTPUTS block. One input, three outputs, and what each cost."""
    f = _demo_facts(demo_root, task_id)
    rel = lambda p: os.path.relpath(p, demo_root) if p and p.startswith(demo_root) else p

    spec_note = ""
    if f["reqs"] is not None:
        spec_note = f"{f['reqs']} requirements, {f['crits']} acceptance criteria"

    print("  INPUTS")
    print(f"    Spec           {task_id}.yaml   {spec_note}")
    if f["spec"]:
        print(f"                   {f['spec']}")
    print(f"    Fixture data   {len(f['fixtures'])} file(s)   "
          f"{os.path.join('inputs_private', 'data', task_id)}")
    model = os.environ.get("LLM_MODEL")
    if not model:
        try:
            from qikly.agent_api.providers.router import _PROVIDERS, _resolve_provider_name
            import importlib
            mod = importlib.import_module(_PROVIDERS[_resolve_provider_name()][0])
            model = getattr(mod, "DEFAULT_MODEL", "<provider default>")
        except Exception:
            model = "<provider default>"
    print(f"    Model          {model}   seed {os.environ.get('AGENT_SEED', HARDCODED_SEED)}")
    print()

    print("  OUTPUTS")
    if f["impl"]:
        names = ", ".join(os.path.basename(p) for p in f["impl"])
        print(f"    Implementation {names}   {f['impl_lines']} lines")
        print(f"                   {rel(os.path.dirname(f['impl'][0]))}")
    if f["suites"]:
        counts = ", ".join(f"{k} {v}" for k, v in f["suites"].items())
        print(f"    Test suites    {counts} tests, none written by hand")
        print(f"                   {os.path.join('outputs', 'tests', task_id)}")
    trail = f"{f['events']} logged events, {f['patches']} patch(es), {len(f['reports'])} HTML report(s)"
    print(f"    Audit trail    {trail}")
    if f["log"]:
        print(f"                   {rel(f['log'])}")
    for r in f["reports"]:
        print(f"                   {rel(r)}")
    print()
    # No model-call count here. This block used to print one derived from the
    # transaction log, which counts three specific actions and therefore
    # undercounts: a real run showed "16 model calls" directly above a usage
    # line saying 29. The usage counter counts every call the providers
    # actually made, so it is the only one that gets to report the number.
    print(f"  {elapsed:.0f}s wall clock, everything under {demo_root}")


def _run_demo(task_ids, where=None):
    """
    Run the demo in its own throwaway project directory, so a first run
    writes nothing into the tree the reader just cloned or installed into.

    Everything lands under <project>/demo/<timestamp>/: its own outputs/,
    its own inputs_private/ fixtures, its own logs and reports. Delete the
    folder and the demo never happened.

    This re-executes the CLI as a subprocess rather than relocating in
    place, because chdir_to_project_root() runs at *import* time (see the
    module-scope PROJECT_ROOT above) -- by the time argv is parsed the
    working directory is already chosen, and every path constant in
    orchestrator.py is relative to it. A child process with QIKLY_PROJECT_ROOT
    preset resolves the root once, correctly, on its own import.
    """
    demo_root = _demo_root(where)
    os.makedirs(demo_root, exist_ok=True)

    # Same reasoning as run_all.py's _subprocess_env(): `-m` in a child needs
    # the package's parent on PYTHONPATH, or a src-layout clone fails to
    # import what the parent process imported fine.
    import qikly
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(qikly.__file__)))
    env = {**os.environ, ENV_VAR: demo_root}
    env["PYTHONPATH"] = os.pathsep.join([pkg_parent] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    # Alongside the run's other logs, and stamped like them, rather than
    # loose in the demo root. The stamp is the demo root's own, which is
    # fixed before the child picks its run timestamp a second or two later.
    log_dir = os.path.join(demo_root, "outputs", "logs")
    os.makedirs(log_dir, exist_ok=True)
    console_log = os.path.join(log_dir, f"demo_console_{os.path.basename(demo_root)}.log")
    handle = open(console_log, "w", encoding="utf-8")
    stack = contextlib.ExitStack()
    stack.enter_context(handle)
    stack.enter_context(contextlib.redirect_stdout(_Tee(sys.stdout, handle)))
    with stack:
        return _demo_body(task_ids, demo_root, env, console_log)


def _demo_body(task_ids, demo_root, env, console_log):
    """The demo's own output, with stdout already teed to the console log."""
    print()
    print("=" * 72)
    print(f"  qikly demo: {', '.join(task_ids)}")
    print(f"  Writing everything to {demo_root}")
    print("  Nothing outside that folder is touched. Delete it to undo the demo.")
    print("=" * 72)
    print()

    # Before the run, not after. Someone watching a demo has one question
    # underneath all the others: what makes this different from an agent
    # writing its own tests? Answering it first, from the real prompt
    # builders and with no model call, means everything that follows is read
    # in the right frame. It takes a fraction of a second and costs nothing.
    try:
        from qikly.explain import build, render
        print(render(build(task_ids[0])))
        print()
    except Exception:
        # A demo must never fail because an explanation could not be built.
        pass

    # Unbuffered, because reading the child through a pipe turns its stdout
    # from a TTY into a block-buffered stream -- without this the whole run
    # appears at once when it finishes, and watching it happen is the point.
    env["PYTHONUNBUFFERED"] = "1"
    # The parent invocation already checked, so keep the child quiet.
    env["QIKLY_NO_VERSION_CHECK"] = "1"
    env["QIKLY_QUIET_BANNER"] = "1"

    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "qikly.cli", "--tasks", ",".join(task_ids)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="")
    returncode = proc.wait()
    elapsed = time.monotonic() - started

    # Three outcomes, not two. A run that never started (bad key, exhausted
    # quota, no network) leaves no transaction log, and telling that user
    # their run "did not converge inside the retry budget" points them at a
    # log that does not exist and a problem they do not have.
    log_dir = os.path.join(demo_root, "outputs", "logs")
    ran = os.path.isdir(log_dir) and any(
        n.startswith("transactions_") and n.endswith(".jsonl") for n in os.listdir(log_dir)
    )

    print()
    print("=" * 72)
    if returncode == 0:
        print(f"  Converged in {elapsed:.0f}s. Passes every test in every stage.")
    elif ran:
        print(f"  Stopped after {elapsed:.0f}s without converging, which the tool reports")
        print("  rather than hides. The record names exactly what blocked it.")
    else:
        print("  The run never started, so this is a setup problem rather than a")
        print("  result. The error above says which one. Nothing was measured.")
        print()
        print(f"  Remove this empty demo directory: {demo_root}")
        print("=" * 72)
        return returncode
    # Explanation first, then the artefacts. A reader who does not yet know
    # what the loop was doing cannot tell which parts of a file listing
    # matter, so the "why" has to arrive before the "where".
    try:
        _print_demo_note(task_ids, returncode == 0)
    except Exception:
        pass  # cosmetic; never let it change what the demo reports

    print()
    try:
        # Every task, not just the first: --demo --tasks A,B runs both, and
        # summarising only A would quietly under-report half the run.
        for i, task_id in enumerate(task_ids):
            if i:
                print()
            if len(task_ids) > 1:
                print(f"  --- {task_id} ---")
            _print_demo_facts(demo_root, task_id, elapsed)
    except Exception as e:
        # Never let a cosmetic summary change what the demo reports.
        print(f"  (summary unavailable: {type(e).__name__}: {e})")
        print(f"  Everything is under {demo_root}")
    # What it cost, read back from the records the child processes wrote inside
    # the demo directory. The child printed its own totals as it went, but a
    # demo that spawns the run cannot add up lines it has already streamed
    # past, and "what did that cost me" is the first question anyone asks
    # after watching one.
    try:
        from qikly.agent_api.usage import read_records
        spent = read_records(demo_root)
        print()
        print(f"  {spent.summary()}")
        for line in spent.breakdown():
            print(" " + line)
        if spent.calls:
            print("  The money is an estimate from a static price table, not a bill.")
    except Exception:
        pass

    print()
    print(f"  This console output is saved to {os.path.relpath(console_log, demo_root)}")
    print("=" * 72)
    return returncode


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one or more qikly tasks, each in its own process.")
    # The first thing anyone types against an unfamiliar CLI, and the first
    # thing a bug report needs. Reads the installed package rather than a
    # literal, so it cannot drift from what pip actually put on disk.
    from qikly import __version__
    parser.add_argument(
        "--version", action="version", version=f"qikly {__version__}"
    )
    parser.add_argument(
        "--tasks", default=None,
        help="Comma-separated task_ids to run (default: every task found in config/tasks/, bundled or private)"
    )
    parser.add_argument(
        "--generate-criteria", action="store_true",
        help="For any task with no acceptance_criteria yet, generate a one-shot first draft "
             "from requirements alone and write it into that task's config file before running. "
             "Explicit opt-in only -- without this flag, such a task just runs with a warning "
             "(see README.md#auto-generating-acceptance-criteria). Never touches a task that "
             "already has acceptance_criteria."
    )
    parser.add_argument(
        "--init", action="store_true",
        help="Create the inputs_private/ layout and a commented starter task in the "
             "current directory, then stop. A fresh install has nowhere to put a task "
             "until this has been run. Never overwrites an existing file."
    )
    parser.add_argument(
        "--scaffold", metavar="FILE", default=None,
        help="Read a Python file and write the task YAML for it: module path, the real "
             "signatures of its public functions, and a guessed entrypoint. Leaves "
             "requirements and acceptance_criteria for you, because criteria derived "
             "from an implementation can only describe what it already does."
    )
    parser.add_argument(
        "--task-id", default=None,
        help="task_id for --scaffold and --criteria-from. Defaults, for --scaffold, "
             "to the file's name upper-cased."
    )
    parser.add_argument(
        "--criteria-from", metavar="FILE", default=None,
        help="Read acceptance criteria out of a ticket, markdown file or .feature "
             "file and print them as YAML. Bullet lists, a headed 'Acceptance "
             "Criteria' section, and Gherkin scenarios are all understood. With "
             "--task-id, writes them into that task instead, refusing if it already "
             "has criteria. Copying a ticket into a file is the whole integration: "
             "there is no API token and no vendor involved."
    )
    parser.add_argument(
        "--criteria-from-jira", metavar="ISSUE", default=None,
        help="Read acceptance criteria from a Jira issue, e.g. PROJ-412. Needs "
             "JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN. Looks for a field named "
             "something like 'Acceptance Criteria', then falls back to the issue "
             "description, through the same parser --criteria-from uses. Same "
             "--task-id behaviour: prints unless you name a task."
    )
    parser.add_argument(
        "--pr-comment", action="store_true",
        help="Print the most recent run(s) as markdown for a pull request comment: "
             "whether each task converged, where it stopped, and the model and "
             "settings behind it. Reads summaries already on disk, so no model call."
    )
    parser.add_argument(
        "--artifacts-url", metavar="URL", default=None,
        help="Link included in --pr-comment output, for the run's uploaded artifacts."
    )
    parser.add_argument(
        "--compare-criteria", metavar="TASK", default=None,
        help="Draft acceptance criteria from this task's requirements alone, then "
             "report them against the criteria you already wrote, treating yours as "
             "ground truth. Says what a generated bar would have missed. Two model "
             "calls; your task file is never modified."
    )
    parser.add_argument(
        "--trends", action="store_true",
        help="Convergence per task over time, from the run summaries already on "
             "disk. No model call. Each period names the model and settings behind "
             "it, and a period where those changed is marked, because a rate that "
             "moved when the configuration moved is not a trend."
    )
    parser.add_argument(
        "--by", default="day", choices=("day", "week", "month"),
        help="Period for --trends. Default day."
    )
    parser.add_argument(
        "--explain", metavar="TASK", default=None,
        help="Print what test generation sees and what the coding agent sees for "
             "one task, and the difference between them, then stop. No model call "
             "and no API key: it builds the same prompts a run builds and shows "
             "them, so the central claim can be read rather than trusted."
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Check every task file offline and stop: valid YAML, required sections, "
             "acceptance_criteria a list rather than one long string, fixture paths "
             "that resolve, and criteria that name values instead of adjectives. "
             "Free, so it suits a pre-commit hook."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the result as one JSON object on stdout instead of prose. Works "
             "with --explain, --validate, and a normal run. Human output moves to "
             "stderr, so stdout stays parseable."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate every patch and apply none of them. The run cannot converge, "
             "which is the point: you get the complete set of changes the agent "
             "would have made, as diffs under outputs/logs/patches/, to read at "
             "your own pace."
    )
    parser.add_argument(
        "--review-patches", action="store_true",
        help="Print each patch and wait for y/N before applying it. Anything other "
             "than a clear yes is a rejection, so an unattended run declines "
             "everything rather than assuming consent."
    )
    parser.add_argument(
        "--from-doc", metavar="DOC",
        help="Build a task file from a document plus the code it describes. "
             "Use with --scaffold: the acceptance criteria come from DOC (a "
             "markdown page, a ticket export or a .feature file) and the "
             "interface comes from the module. requirements are still left for "
             "you, on purpose: the coding agent reads them, and a feature page "
             "usually restates its own criteria in the prose above them."
    )
    parser.add_argument(
        "--start", metavar="TASK",
        help="Start a run in the background and print its run id, without waiting. "
             "A run takes minutes to hours, so this is for when the terminal is not "
             "where you want to spend them: start it, close the window, ask later "
             "with --status. It is also the mechanism the MCP server is built on."
    )
    parser.add_argument(
        "--status", metavar="RUN_ID",
        help="What happened, or is happening, to one run started with --start. "
             "Reads what the run itself writes, so it is accurate even if the "
             "process died: 'stalled' means gone without a summary, which is a "
             "crash rather than a failing suite."
    )
    parser.add_argument(
        "--runs", action="store_true",
        help="List known runs, newest first, with the state of each."
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Keep the suites and implementation a previous attempt left on disk instead "
             "of regenerating them. Everything already generated cost model calls, and a "
             "run that died out of credit or mid-outage has all of it sitting there."
    )
    parser.add_argument(
        "--check-criteria", action="store_true",
        help="One model call per task asking whether any implementation could satisfy "
             "both the requirements and the acceptance criteria, then stop. Advisory: "
             "it changes nothing. A contradiction here is a stage that spends its whole "
             "budget without converging."
    )
    parser.add_argument(
        "--demo-dir", metavar="PATH", default=None,
        help="Where --demo writes. A timestamped folder is created inside it. "
             f"Default is {DEMO_DIR}/ under the directory you invoked from; a "
             "relative path here is taken from there too. Nothing outside the "
             "created folder is touched either way."
    )
    parser.add_argument(
        "--demo", action="store_true",
        help=f"Run one task end to end in a throwaway {DEMO_DIR}/<timestamp>/ directory and print "
             f"where the code, tests, and full record landed. Defaults to {DEMO_TASK}; combine with "
             f"--tasks to demo a different one. Writes nothing outside that directory."
    )
    return parser.parse_args()


def _print_run(info, brief=False):
    """
    One run, for a human. Returns a shell exit code: 0 for a run that passed or
    is still going, 1 for one that failed or stalled, so this composes with &&.
    """
    import json as _json

    state = info.get("state", "unknown")
    progress = info.get("progress") or {}
    if brief:
        print("%-34s %-8s %s" % (
            info.get("run_id"), state,
            progress.get("stage") or info.get("detail") or ""))
    else:
        print(_json.dumps(info, indent=2, default=str))
    return 0 if state in ("passed", "running") else 1


def _do_init():
    """Create the project layout. Prints what it made and what to do next."""
    from qikly.scaffold import init_project

    root = INVOKED_FROM
    made, skipped = init_project(root)
    print(f"qikly init in {root}")
    for path in made:
        print(f"  created  {os.path.relpath(path, root)}")
    for path in skipped:
        print(f"  kept     {os.path.relpath(path, root)}   (already there)")
    print()
    print("  Next: edit inputs_private/config/tasks/MY_FIRST_TASK.yaml, then run")
    print("    qikly --tasks MY_FIRST_TASK")
    print("  Or point it at code you already have:")
    print("    qikly --scaffold path/to/module.py")
    return 0


def _seed():
    """The run seed, from the environment or the module default."""
    env = os.environ.get("AGENT_SEED")
    return int(env) if env else HARDCODED_SEED


def _do_check_criteria(tasks):
    """Look for specification contradictions before spending a stage budget."""
    from qikly.orchestrator.orchestrator import discover_task_ids
    from qikly.orchestrator.tuning.check_criteria import check, report

    task_ids = [t.strip() for t in tasks.split(",")] if tasks else discover_task_ids()
    total = 0
    for task_id in task_ids:
        total += report(task_id, check(task_id, seed=_seed()))

    # It is one call per task, but it is still a call, and a command that
    # spends money silently teaches people not to trust the accounting on the
    # commands that spend a lot of it.
    try:
        from qikly.agent_api.usage import USAGE
        print()
        print(USAGE.summary())
        for line in USAGE.breakdown():
            print(line)
    except Exception:
        pass
    return 1 if total else 0


def _effective_model(provider):
    """
    The model this run will actually use.

    LLM_MODEL wins; otherwise each provider module owns its own default, and
    reading it from there rather than from a second copy here is what keeps a
    cost estimate priced for the model that is really called.
    """
    override = os.environ.get("LLM_MODEL")
    if override:
        return override
    try:
        import importlib

        module = importlib.import_module(f"qikly.agent_api.providers.{provider}")
        return getattr(module, "DEFAULT_MODEL", "")
    except Exception:
        return ""


def _do_pr_comment(tasks, artifacts_url):
    """Markdown for a PR comment, from summaries already on disk."""
    from qikly.pr_comment import latest_runs, render

    task_ids = [t.strip() for t in tasks.split(",")] if tasks else None
    print(render(latest_runs(task_ids=task_ids), artifacts_url))
    return 0


def _do_compare_criteria(task_id, as_json):
    """
    What --generate-criteria would have written, against what you wrote.

    Yours are the ground truth and are never touched. The point is the gap: a
    generated bar that misses three of your eleven rules is a different
    proposition from one that misses none, and until now the only way to find
    out was to read two lists side by side and do the matching in your head.
    """
    from qikly.criteria_compare import compare, render

    try:
        result = compare(task_id, seed=_seed())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if as_json:
        import json as _json

        print(_json.dumps(result, indent=2))
    else:
        print(render(result["task_id"], result["reference"], result["draft"],
                     {int(k): v for k, v in result["verdicts"].items()},
                     result["extra"], result["summary"]))
        try:
            from qikly.agent_api.usage import USAGE

            print()
            print(USAGE.summary())
        except Exception:
            pass
    # Non-zero when the draft would have lost a rule, so this can gate.
    return 1 if result["summary"]["missed"] else 0


def _do_trends(tasks, grain, as_json):
    """Convergence over time, from summaries already on disk. No model call."""
    from qikly.orchestrator.reports.trend_report import collect, render, write_json

    task_ids = [t.strip() for t in tasks.split(",")] if tasks else None
    trends = collect(task_ids, grain=grain)

    if as_json:
        import json as _json

        print(_json.dumps(trends, indent=2))
        return 0

    print(render(trends, grain=grain))
    if trends:
        print()
        print(f"Written to {write_json(trends)}")
    return 0


def _do_criteria_from_jira(issue_key, task_id):
    """
    The same import as --criteria-from, over the network instead of from a file.

    Everything after the fetch is shared with the file path, deliberately: the
    only part that can break because Atlassian changed something is one GET,
    and the parsing it feeds is already covered.
    """
    from qikly.jira import criteria_for

    try:
        criteria, where = criteria_for(issue_key)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Could not read {issue_key}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        print("  Check JIRA_BASE_URL, that the issue key is right, and that the "
              "token has read access to that project.", file=sys.stderr)
        return 2

    if not criteria:
        print(f"No acceptance criteria found in {issue_key} "
              f"(looked in {where}).", file=sys.stderr)
        print("  Prose is deliberately not split into criteria. Add a list to "
              "the issue, or use --criteria-from on a file you edit yourself.",
              file=sys.stderr)
        return 2

    print(f"# {len(criteria)} criteria from {issue_key} ({where})")
    print("acceptance_criteria:")
    for item in criteria:
        print('  - "%s"' % item.replace("\\", "\\\\").replace('"', '\\"'))

    if not task_id:
        print(file=sys.stderr)
        print("  Paste this into your task file, or re-run with --task-id TASK.",
              file=sys.stderr)
        return 0

    return _append_criteria_to_task(task_id, criteria)


def _do_explain(task_id, as_json):
    """
    Show the withholding rather than asserting it.

    `pytest tests/test_withholding.py` already proves it, and proves it to
    engineers. This shows it to everyone else: the criteria present in one
    column, absent from the other, in the text a real run would send.
    """
    from qikly.explain import build, render

    try:
        facts = build(task_id)
    except FileNotFoundError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    if as_json:
        import json as _json

        # The whole task text is the point on the console and noise in a
        # machine-readable document, where the counts and the verdict are what
        # a caller acts on.
        print(_json.dumps({k: v for k, v in facts.items()
                           if k not in ("test_generation_sees", "coding_agent_sees")},
                          indent=2))
    else:
        print(render(facts))
    return 0 if facts["withheld_ok"] or not facts["criteria_count"] else 1


def _do_validate(tasks, as_json):
    """Everything about a task file that can be known without calling anything."""
    from qikly.validate import check_all, render

    task_ids = [t.strip() for t in tasks.split(",")] if tasks else None
    results = check_all(task_ids)

    if as_json:
        import json as _json

        print(_json.dumps({
            "tasks": {t: {"errors": e, "warnings": w} for t, (e, w) in results.items()},
            "error_count": sum(len(e) for e, _ in results.values()),
            "warning_count": sum(len(w) for _, w in results.values()),
        }, indent=2))
        return 1 if any(e for e, _ in results.values()) else 0

    text, errors = render(results)
    print(text)
    return 1 if errors else 0


def _do_criteria_from(source, task_id):
    """
    Lift acceptance criteria out of wherever they were already written.

    The blank `acceptance_criteria:` list is the biggest thing between someone
    and a first run, and for most teams the list is not actually blank: it is
    sitting in a ticket, written before any code was cut, because their process
    asked for it. This reads that ticket.

    Printing is the default and writing needs --task-id, because criteria are
    the one input the whole tool is judged against. Silently editing them is
    not a thing this should ever do without being asked by name.

    Only the YAML goes to stdout. Every explanation goes to stderr, so

        qikly --criteria-from ticket.md >> inputs_private/config/tasks/T.yaml

    appends a valid block rather than a block with advice wedged into the
    middle of it. A command whose output is meant to be pasted has to be
    pipeable, or the advice is worth less than the friction it adds.
    """
    from qikly.criteria_import import parse_file

    root = INVOKED_FROM
    path = source if os.path.isabs(source) else os.path.join(root, source)
    if not os.path.isfile(path):
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    criteria = parse_file(path)
    if not criteria:
        print(f"No acceptance criteria found in {shown(path)}.", file=sys.stderr)
        print(file=sys.stderr)
        print("  Looked for a bullet list, an 'Acceptance Criteria' section, and", file=sys.stderr)
        print("  Gherkin scenarios. Prose is deliberately not split into criteria:", file=sys.stderr)
        print("  a rule nobody wrote is exactly the invented bar this tool argues", file=sys.stderr)
        print("  against. Add a list and run this again.", file=sys.stderr)
        return 2

    print(f"# {len(criteria)} criteria from {shown(path)}")
    print("acceptance_criteria:")
    for item in criteria:
        print(f'  - "{item.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"')

    if not task_id:
        print(file=sys.stderr)
        print("  Paste this into your task file, or re-run with --task-id TASK to", file=sys.stderr)
        print("  have it written in for you.", file=sys.stderr)
        return 0

    return _append_criteria_to_task(task_id, criteria)


def shown(path, root=None):
    """
    A path as a reader wants to see it.

    A file outside the project relpaths into a wall of "..", which is worse
    than the absolute path it came from.
    """
    rel = os.path.relpath(path, root or INVOKED_FROM)
    return path if rel.startswith("..") else rel


def _append_criteria_to_task(task_id, criteria):
    """
    Write criteria into a task that has none. Shared by both importers, so a
    ticket read from a file and the same ticket read from Jira cannot end up
    with two different rules about overwriting.
    """
    import yaml

    root = INVOKED_FROM
    dest = os.path.join(root, "inputs_private", "config", "tasks", f"{task_id}.yaml")
    if not os.path.isfile(dest):
        print(file=sys.stderr)
        print(f"  No such task: {shown(dest)}", file=sys.stderr)
        print("  Create it with --init or --scaffold first, then run this again.", file=sys.stderr)
        return 2
    with open(dest, encoding="utf-8") as handle:
        text = handle.read()
    existing = (yaml.safe_load(text) or {}).get("acceptance_criteria") or []
    # A placeholder qikly wrote itself is not a bar to protect. --scaffold
    # seeds a TODO line so the shape of the file is obvious, and treating that
    # as real criteria blocked the natural sequence: scaffold from your code,
    # then import the criteria from the ticket that described it.
    placeholder = bool(existing) and all(
        isinstance(c, str) and c.strip().upper().startswith("TODO") for c in existing)
    if placeholder:
        # Drop the placeholder block so the new criteria are the file's only
        # bar, rather than being appended under a TODO nobody meant to keep.
        kept, skipping = [], False
        for line in text.splitlines():
            if line.startswith("acceptance_criteria:"):
                skipping = True
                continue
            if skipping and (line.startswith("  - ") or not line.strip()):
                continue
            skipping = False
            kept.append(line)
        text = "\n".join(kept).rstrip("\n") + "\n"
        with open(dest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    if existing and not placeholder:
        print(file=sys.stderr)
        print(f"  {task_id} already has acceptance_criteria, so nothing was written.", file=sys.stderr)
        print("  Merging two bars automatically would be a guess about which rule", file=sys.stderr)
        print("  wins. Paste what you want from the list above.", file=sys.stderr)
        return 2

    block = "acceptance_criteria:\n" + "".join(
        '  - "%s"\n' % item.replace("\\", "\\\\").replace('"', '\\"')
        for item in criteria)
    with open(dest, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(("" if text.endswith("\n") else "\n") + "\n" + block)
    print(file=sys.stderr)
    print(f"  Written into {shown(dest)}.", file=sys.stderr)
    print("  Read them before you run. They are the standard the code is judged", file=sys.stderr)
    print("  against, and a criterion that came out of a ticket is a draft.", file=sys.stderr)
    return 0


def _fill_criteria_from(text, doc, root):
    """Put a document's acceptance criteria into a freshly scaffolded task."""
    from qikly import from_doc as fd
    from qikly.criteria_import import parse_file

    path = doc if os.path.isabs(doc) else os.path.join(root, doc)
    if not os.path.isfile(path):
        return text, f"no such document: {shown(path)}"
    try:
        criteria = parse_file(path)
    except Exception as exc:                        # noqa: BLE001
        return text, f"could not read {shown(path)}: {exc}"
    return fd.merge(text, criteria)


def _do_scaffold(source, task_id, doc=None):
    """
    Write task files for an existing Python module. Two of them, on purpose.

    Scaffolding from code means one of two different jobs, and the command line
    cannot tell which: you either want that code tested, or you want a fresh
    implementation of the same interface. The first version wrote one file with
    the deciding line commented out, which asks a reader to understand the
    distinction before they have run anything.

    So both are written. You read two short files, keep the one that matches
    what you are doing, and delete the other.
    """
    from qikly.scaffold import build_task

    root = INVOKED_FROM
    source = source if os.path.isabs(source) else os.path.join(root, source)
    if not os.path.isfile(source):
        print(f"no such file: {source}")
        return 2

    import re

    dest_dir = os.path.join(root, "inputs_private", "config", "tasks")
    os.makedirs(dest_dir, exist_ok=True)

    written = []
    for seed_mode, suffix, headline in (
        ("existing", "_VERIFY", "tests the code you already have"),
        (None, "", "writes a fresh implementation"),
    ):
        text, problem = build_task(source, root, task_id=task_id, seed=seed_mode)
        if problem:
            print(problem)
            return 2
        if doc:
            text, doc_problem = _fill_criteria_from(text, doc, root)
            if doc_problem:
                print(doc_problem)
                return 2
        base = re.search(r'task_id:\s*"([^"]+)"', text).group(1)
        tid = base + suffix
        text = text.replace(f'task_id: "{base}"', f'task_id: "{tid}"', 1)
        dest = os.path.join(dest_dir, f"{tid}.yaml")
        if os.path.exists(dest):
            print(f"{shown(dest)} already exists. Move it aside first, or pass "
                  f"--task-id to write a different name.")
            return 2
        with open(dest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written.append((tid, dest, headline))

    print(f"Read {shown(source)} and wrote two task files.")
    print()
    print("  Keep one, delete the other. They differ in one section:")
    print()
    for tid, dest, headline in written:
        print(f"    {tid:28} {headline}")
        print(f"    {'':28} {shown(dest)}")
    print()
    if doc:
        print(f"  Acceptance criteria came from {shown(doc)}.")
        print()
        print("  One section is still yours:")
        print("    requirements         what the code is meant to do, in your words")
        print()
        print("  It is not filled from the document on purpose. The coding agent")
        print("  reads requirements, and a feature page usually restates its own")
        print("  acceptance criteria in the prose above them. Lifting that across")
        print("  would hand the criteria to the one agent that must never see")
        print("  them, by a route nobody would think to check.")
        print()
        print("  `qikly --validate` checks what you write there against the")
        print("  criteria and says so if the two say the same thing.")
    else:
        print("  Both need the same two sections from you, and neither can be")
        print("  derived from the code:")
        print("    requirements         what the code is meant to do, in your words")
        print("    acceptance_criteria  the checkable edge cases, with boundary values")
        print()
        print("  Criteria read out of an implementation can only describe what it")
        print("  already does, and a bar that agrees with the code by construction is")
        print("  exactly what this tool exists to avoid. So those two are yours.")
        print()
        print("  Already written them somewhere? Point at it:")
        print("    qikly --scaffold %s --from-doc feature.md" % shown(source))
    print()
    print(f"  Then: qikly --tasks {written[0][0]}")
    return 0


def _do_criteria_from(source, task_id):
    """
    Lift acceptance criteria out of wherever they were already written.

    The blank `acceptance_criteria:` list is the biggest thing between someone
    and a first run, and for most teams the list is not actually blank: it is
    sitting in a ticket, written before any code was cut, because their process
    asked for it. This reads that ticket.

    Printing is the default and writing needs --task-id, because criteria are
    the one input the whole tool is judged against. Silently editing them is
    not a thing this should ever do without being asked by name.

    Only the YAML goes to stdout. Every explanation goes to stderr, so

        qikly --criteria-from ticket.md >> inputs_private/config/tasks/T.yaml

    appends a valid block rather than a block with advice wedged into the
    middle of it. A command whose output is meant to be pasted has to be
    pipeable, or the advice is worth less than the friction it adds.
    """
    from qikly.criteria_import import parse_file

    root = INVOKED_FROM
    path = source if os.path.isabs(source) else os.path.join(root, source)
    if not os.path.isfile(path):
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    criteria = parse_file(path)
    if not criteria:
        print(f"No acceptance criteria found in {shown(path)}.", file=sys.stderr)
        print(file=sys.stderr)
        print("  Looked for a bullet list, an 'Acceptance Criteria' section, and", file=sys.stderr)
        print("  Gherkin scenarios. Prose is deliberately not split into criteria:", file=sys.stderr)
        print("  a rule nobody wrote is exactly the invented bar this tool argues", file=sys.stderr)
        print("  against. Add a list and run this again.", file=sys.stderr)
        return 2

    print(f"# {len(criteria)} criteria from {shown(path)}")
    print("acceptance_criteria:")
    for item in criteria:
        print(f'  - "{item.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"')

    if not task_id:
        print(file=sys.stderr)
        print("  Paste this into your task file, or re-run with --task-id TASK to", file=sys.stderr)
        print("  have it written in for you.", file=sys.stderr)
        return 0

    return _append_criteria_to_task(task_id, criteria)


def shown(path, root=None):
    """
    A path as a reader wants to see it.

    A file outside the project relpaths into a wall of "..", which is worse
    than the absolute path it came from.
    """
    rel = os.path.relpath(path, root or INVOKED_FROM)
    return path if rel.startswith("..") else rel


def _append_criteria_to_task(task_id, criteria):
    """
    Write criteria into a task that has none. Shared by both importers, so a
    ticket read from a file and the same ticket read from Jira cannot end up
    with two different rules about overwriting.
    """
    import yaml

    root = INVOKED_FROM
    dest = os.path.join(root, "inputs_private", "config", "tasks", f"{task_id}.yaml")
    if not os.path.isfile(dest):
        print(file=sys.stderr)
        print(f"  No such task: {shown(dest)}", file=sys.stderr)
        print("  Create it with --init or --scaffold first, then run this again.", file=sys.stderr)
        return 2
    with open(dest, encoding="utf-8") as handle:
        text = handle.read()
    existing = (yaml.safe_load(text) or {}).get("acceptance_criteria") or []
    # A placeholder qikly wrote itself is not a bar to protect. --scaffold
    # seeds a TODO line so the shape of the file is obvious, and treating that
    # as real criteria blocked the natural sequence: scaffold from your code,
    # then import the criteria from the ticket that described it.
    placeholder = bool(existing) and all(
        isinstance(c, str) and c.strip().upper().startswith("TODO") for c in existing)
    if placeholder:
        # Drop the placeholder block so the new criteria are the file's only
        # bar, rather than being appended under a TODO nobody meant to keep.
        kept, skipping = [], False
        for line in text.splitlines():
            if line.startswith("acceptance_criteria:"):
                skipping = True
                continue
            if skipping and (line.startswith("  - ") or not line.strip()):
                continue
            skipping = False
            kept.append(line)
        text = "\n".join(kept).rstrip("\n") + "\n"
        with open(dest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    if existing and not placeholder:
        print(file=sys.stderr)
        print(f"  {task_id} already has acceptance_criteria, so nothing was written.", file=sys.stderr)
        print("  Merging two bars automatically would be a guess about which rule", file=sys.stderr)
        print("  wins. Paste what you want from the list above.", file=sys.stderr)
        return 2

    block = "acceptance_criteria:\n" + "".join(
        '  - "%s"\n' % item.replace("\\", "\\\\").replace('"', '\\"')
        for item in criteria)
    with open(dest, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(("" if text.endswith("\n") else "\n") + "\n" + block)
    print(file=sys.stderr)
    print(f"  Written into {shown(dest)}.", file=sys.stderr)
    print("  Read them before you run. They are the standard the code is judged", file=sys.stderr)
    print("  against, and a criterion that came out of a ticket is a draft.", file=sys.stderr)
    return 0


def main():
    from qikly.console import use_utf8

    use_utf8()

    from qikly.orchestrator.orchestrator import discover_task_ids
    from qikly.agent_api.providers.router import validate_config

    args = _parse_args()

    # Once per invocation, before any work, and before the early returns below.
    # It sat after them, which quietly exempted --scaffold and --check-criteria:
    # two commands someone uses repeatedly, and therefore two of the better
    # moments to mention a new release. Safe here because it needs no provider
    # key, times out in 1.5 seconds, and is silent on every failure path.
    #
    # Not literally every invocation: --version and --help are argparse actions
    # that print and exit inside _parse_args() on the line above, so they never
    # reach this. That is deliberate rather than an oversight. The notice goes
    # to stdout, and `qikly --version` is the one command a script is likely to
    # parse, so adding a second line to it would break callers to tell them
    # something they did not ask for.
    try:
        from qikly.version_check import check_for_update, repeat_notice
        check_for_update()
        # And again on the way out. A run prints for minutes, so the opening
        # line has scrolled away by the time anyone reads the result. atexit
        # rather than a wrapper around the body below, because main() returns
        # from a dozen places and one of them would eventually be missed.
        atexit.register(repeat_notice)
    except Exception:
        pass

    # These run before anything else and exit: they exist to make a project
    # runnable, so they must work when nothing is configured yet and must not
    # require a provider key.
    if args.start:
        from qikly import runs
        run_id = runs.start(args.start)
        print(run_id)
        return 0
    if args.status:
        from qikly import runs
        return _print_run(runs.status(args.status))
    if args.runs:
        from qikly import runs
        found = runs.list_runs()
        if not found:
            print("no runs recorded in %s" % runs.runs_dir())
            return 0
        for item in found:
            _print_run(item, brief=True)
        return 0

    if args.init:
        return _do_init()
    if args.scaffold:
        return _do_scaffold(args.scaffold, args.task_id, args.from_doc)
    if args.criteria_from:
        return _do_criteria_from(args.criteria_from, args.task_id)
    if args.criteria_from_jira:
        return _do_criteria_from_jira(args.criteria_from_jira, args.task_id)
    if args.compare_criteria:
        return _do_compare_criteria(args.compare_criteria, args.json)
    if args.trends:
        return _do_trends(args.tasks, args.by, args.json)
    if args.pr_comment:
        return _do_pr_comment(args.tasks, args.artifacts_url)
    if args.explain:
        return _do_explain(args.explain, args.json)
    if args.validate:
        return _do_validate(args.tasks, args.json)
    if args.check_criteria:
        return _do_check_criteria(args.tasks)

    if args.demo and not args.tasks:
        task_ids = [DEMO_TASK]
    else:
        task_ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_task_ids()
    task_ids = [t for t in task_ids if t]
    if not task_ids:
        print("No tasks found in config/tasks/, bundled or private (and none given via --tasks).")
        sys.exit(1)

    # Fail fast on a misconfigured/unsupported LLM_PROVIDER or a missing
    # required env var, before spawning any per-task process -- otherwise
    # every task's process would hit (and print) the same error separately,
    # once real work is already underway.
    try:
        provider = validate_config()
    except RuntimeError as e:
        print(f"LLM configuration error: {e}")
        sys.exit(1)
    # The demo spawns this same entry point as a child, so without the guard
    # the provider banner appears twice, once from each process.
    if not os.environ.get("QIKLY_QUIET_BANNER"):
        print(f"LLM provider: {provider} (model={os.environ.get('LLM_MODEL', '<provider default>')})")

    # After validate_config() so a missing API key fails before we create a
    # demo directory that would then sit there empty.
    if args.demo:
        sys.exit(_run_demo(task_ids, args.demo_dir))

    # Set before the task processes are spawned, because each inherits the
    # environment and nothing else carries this down to where a patch is
    # applied.
    from qikly import approval
    if args.dry_run and args.review_patches:
        print("--dry-run and --review-patches contradict each other: one applies "
              "nothing, the other asks. Pick one.")
        sys.exit(2)
    if args.dry_run:
        os.environ[approval.ENV_MODE] = approval.DRY_RUN
        print("Dry run: every patch will be generated and written to "
              "outputs/logs/patches/, and none will be applied. The run cannot "
              "converge, which is what you asked for.")
    if args.review_patches:
        if len(task_ids) > 1:
            print("--review-patches runs one task at a time. Tasks run "
                  "concurrently in separate processes, so several would compete "
                  "for the same terminal and you could not tell which patch you "
                  "were approving. Re-run with --tasks naming one.")
            sys.exit(2)
        os.environ[approval.ENV_MODE] = approval.REVIEW
        print("Reviewing patches: each one is printed and waits for y/N. "
              "Anything else declines it.")

    # Said before the spend, not after. The moment someone hesitates is the
    # moment before they press enter, and a receipt afterwards does not help
    # with the decision they were making.
    try:
        from qikly import forecast
        print(forecast.render(forecast.estimate(
            task_ids, _effective_model(provider))))
    except Exception:
        pass

    seed_env = os.environ.get("AGENT_SEED")
    seed = int(seed_env) if seed_env else HARDCODED_SEED

    print("Project root:", PROJECT_ROOT)
    print(f"Running {len(task_ids)} task(s), one process each: {', '.join(task_ids)}")
    if seed is not None:
        print(f"Running with seed={seed} (best-effort determinism)")

    processes = [
        multiprocessing.Process(
            target=_run_task_process,
            args=(task_id, seed, args.generate_criteria, args.resume), name=task_id
        )
        for task_id in task_ids
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    failed = [p.name for p in processes if p.exitcode != 0]
    if failed:
        print(f"Task(s) failed: {', '.join(failed)}")
        sys.exit(1)

    print("All tasks passed.")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
