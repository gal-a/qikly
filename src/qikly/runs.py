"""
Starting a run without waiting for it, and asking about it afterwards.

A run takes minutes to hours. Anything that has to answer a caller promptly,
an MCP host above all, cannot block on one, so this splits the two halves:
`start()` launches a run and returns immediately, `status()` reports on it.

The run id is not new. Every run already derives its transaction log, its patch
directory and its summary from `<task_id>_<YYYYmmdd_HHMMSS>`, so that string is
the id. Inventing a second identifier would mean maintaining a mapping between
them, and a mapping is a thing that can be wrong.

The parent chooses the timestamp and passes it in `QIKLY_RUN_TIMESTAMP`, which
is what makes the run addressable before it has written anything. Without that
the child would pick its own and the parent would have to guess which of the
files appearing on disk was the one it just started.

Status is derived, never stored. A stored state has to be updated by something,
and the thing that would update it is the process that just crashed. So
`status()` reads what the run itself writes: the transaction log while it runs,
the summary once it finishes.
"""
import csv
import errno
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

# Resolved against the project root rather than the working directory. The rest
# of the package uses relative paths and relies on chdir_to_project_root()
# having been called, which is fine for a CLI that does exactly that on the way
# in. It is not fine here: an MCP host starts its server in whatever directory
# it likes and never chdirs, and cli.main() moves the working directory out
# from under a caller mid-call. Found by starting a real detached run and
# watching its record land in the repository instead of the project.
_RUNS_REL = os.path.join("outputs", "runs")
_LOG_REL = os.path.join("outputs", "logs")
_SUMMARY_REL = os.path.join("outputs", "reports", "run_summary")


def _root():
    """The project this run belongs to, falling back to the working directory."""
    try:
        from qikly.paths import project_root
        return project_root()
    except Exception:
        return os.getcwd()


def runs_dir():
    return os.path.join(_root(), _RUNS_REL)


def log_dir():
    return os.path.join(_root(), _LOG_REL)


def summary_dir():
    return os.path.join(_root(), _SUMMARY_REL)


RUN_ID_RE = re.compile(r"^(?P<task>[A-Za-z0-9_.-]+)_(?P<stamp>\d{8}_\d{6})$")


def _now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class BadTaskId(ValueError):
    """A task id that cannot safely become part of a path."""


def check_task_id(task_id):
    """
    Refuse a task id that is not a single path segment.

    `status()` was already safe, because RUN_ID_RE rejects anything odd on the
    way back in. `start()` had no equivalent check, so a task id containing
    `..` or a separator escaped outputs/runs: os.path.join happily normalises
    "outputs/runs/../../evil_20260910_120000.json" two levels up, and more of
    them leave the project entirely. It arrives here straight from an MCP tool
    call, so a host's agent, or somebody pasting a file path where a task id
    was wanted, is enough to trigger it.
    """
    if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
        raise BadTaskId(
            "task_id must be one path segment of letters, digits, dot, dash or "
            "underscore; got %r" % (task_id,))
    if task_id in (".", ".."):
        raise BadTaskId("task_id must not be %r" % task_id)
    return task_id


def make_run_id(task_id, stamp=None):
    return "%s_%s" % (check_task_id(task_id), stamp or _now_stamp())


def split_run_id(run_id):
    """(task_id, timestamp), or (None, None) if this is not a run id."""
    m = RUN_ID_RE.match(run_id or "")
    return (m.group("task"), m.group("stamp")) if m else (None, None)


def _record_path(run_id):
    return os.path.join(runs_dir(), "%s.json" % run_id)


def _read_json(path, default=None):
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_record(path, record):
    """
    Write a run record, replacing whatever was there.

    Via a temporary file and os.replace, which is atomic, so a reader never
    sees half a record. status() runs while runs are being written and a
    truncated file would parse as no record at all, which reads as a crash.
    """
    tmp = "%s.tmp" % path
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
    os.replace(tmp, path)


# A run that claims to be alive but has written nothing for this long is not
# believed. `_alive` is the only signal separating "running" from "stalled",
# and a reused pid makes it say yes about an unrelated process, which would
# hide a crash forever. Generous, because a slow model call can legitimately
# leave the log quiet for minutes.
SILENCE_BEFORE_DOUBT = 15 * 60


def _alive(pid):
    """
    Is that process still running?

    Best effort by design. A pid can be reused, and on a machine that has been
    up for weeks it eventually will be. `status()` therefore does not trust
    this alone: see SILENCE_BEFORE_DOUBT.

    When the question cannot be answered at all, the answer is "yes". Saying
    "no" would report a healthy run as a crash on the strength of a broken
    lookup, whereas saying "yes" wrongly is corrected within
    SILENCE_BEFORE_DOUBT by the run's own silence. The failure that fixes
    itself is the better one to choose.
    """
    if not pid:
        return False
    if os.name == "nt":
        # CSV, because the plain format is whitespace-separated and an image
        # name may contain spaces. Quoted fields let the pid be compared as a
        # field rather than as a substring of the line, which would otherwise
        # match the memory column: pid 42 is a substring of "42,168 K".
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            # tasklist missing, restricted, or too slow to answer. Unknown, so
            # believed alive, and the silence rule decides in the end.
            return True
        for row in csv.reader(io.StringIO(out.stdout or "")):
            if len(row) > 1 and row[1].strip() == str(pid):
                return True
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def _claim_run_id(task_id, limit=120):
    """
    Reserve a run id nobody else holds, and return it with its open claim.

    The timestamp has one-second resolution and the id is the task plus that
    timestamp, so two starts of the same task inside one second produced the
    *same* id, and nothing noticed. The second record overwrote the first, both
    children were handed the same QIKLY_RUN_TIMESTAMP, so they appended to one
    transaction log and raced to overwrite one summary. A host retrying a slow
    tool call is enough to cause it.

    The claim uses O_CREAT|O_EXCL, so checking and reserving are one atomic
    step rather than a look followed by a write another process can win in
    between. On a collision the stamp moves forward a second, which keeps it
    matching the \\d{8}_\\d{6} the orchestrator validates.
    """
    check_task_id(task_id)
    os.makedirs(runs_dir(), exist_ok=True)
    when = datetime.now()
    for _ in range(limit):
        stamp = when.strftime("%Y%m%d_%H%M%S")
        run_id = "%s_%s" % (task_id, stamp)
        path = _record_path(run_id)
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            when += timedelta(seconds=1)
            continue
        os.close(handle)
        return run_id, stamp, path
    raise RuntimeError(
        "could not find a free run id for %s after %d attempts" % (task_id, limit))


def start(task_id, env=None, python=None, extra_args=()):
    """
    Launch a run in its own process and return its run id straight away.

    The child is detached: it outlives this call, writes to the same output
    tree a foreground run would, and is never waited on here.
    """
    run_id, stamp, claim = _claim_run_id(task_id)

    # A placeholder record, written *before* the process exists.
    #
    # The record used to be written only after Popen returned, which left a
    # window where the claim was an empty file: status() read no pid, found no
    # summary, and called a run that was starting normally "stalled". Narrow on
    # a local disk, and much less narrow on a synced folder. Worse, if the
    # record write itself failed the run was orphaned that way permanently.
    #
    # Now the record exists first and gains its pid afterwards, so the window
    # contains a record that says "started, no pid yet" rather than nothing.
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    record = {"run_id": run_id, "task_id": task_id, "run_timestamp": stamp,
              "pid": None, "started_at": started_at, "cwd": _root()}
    _write_record(claim, record)

    child_env = dict(os.environ if env is None else env)
    child_env["QIKLY_RUN_TIMESTAMP"] = stamp
    # The parent has already said whatever it was going to say about versions.
    child_env["QIKLY_NO_VERSION_CHECK"] = "1"

    cmd = [python or sys.executable, "-m", "qikly.cli", "--tasks", task_id, *extra_args]

    # Detach, so the run survives the caller exiting, and stay invisible.
    #
    # DETACHED_PROCESS was wrong on Windows: it only stops the child inheriting
    # this console, leaving it and the per-stage subprocesses it spawns free to
    # acquire one, which appears as a console window opening on the user's
    # desktop. CREATE_NO_WINDOW suppresses that. The two are mutually
    # exclusive, so this cannot ask for both.
    #
    # CREATE_NEW_PROCESS_GROUP does the surviving half: without it a Ctrl+C or
    # a closing console in the parent's group reaches the run and kills it.
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "env": child_env, "cwd": _root()}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except Exception:
        # The claim is an empty file that exists only to reserve the id. If the
        # process never starts, leaving it behind would make status() report a
        # run that does not exist as "stalled" forever, and would burn that id.
        try:
            os.unlink(claim)
        except OSError:
            pass
        raise

    record["pid"] = proc.pid
    _write_record(claim, record)
    return run_id


def _progress(task_id, stamp):
    """The last thing the run said, read from its own transaction log."""
    path = os.path.join(log_dir(), "transactions_%s_%s.jsonl" % (task_id, stamp))
    if not os.path.exists(path):
        return {}
    last, count, passed = {}, 0, False
    try:
        with io.open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a line still being written
                count += 1
                last = row
                if row.get("action") == "all_tests_passed":
                    passed = True
    except OSError:
        return {}
    out = {"events": count, "all_tests_passed": passed}
    for key in ("stage", "action", "iteration", "ts"):
        if last.get(key) is not None:
            out[key] = last[key]
    return out


def _silent_too_long(record, progress):
    """
    Has this run said nothing for longer than a working run ever would?

    Measured from the last transaction if there is one, otherwise from the
    start, so a run that dies before writing anything is caught too. Any
    unparseable timestamp means "do not doubt it", because a clock problem
    must not turn healthy runs into crashes.
    """
    when = progress.get("ts") or record.get("started_at")
    if not when:
        return False
    try:
        seen = datetime.fromisoformat(str(when))
    except ValueError:
        return False
    now = datetime.now(seen.tzinfo) if seen.tzinfo else datetime.now()
    return (now - seen).total_seconds() > SILENCE_BEFORE_DOUBT


def status(run_id):
    """
    What is happening, or what happened, to one run.

    `state` is one of: unknown, running, stalled, passed, failed. "stalled"
    means the process is gone and no summary was written, which is the shape a
    crash leaves behind and is worth naming rather than reporting as failure.
    """
    task_id, stamp = split_run_id(run_id)
    if not task_id:
        return {"run_id": run_id, "state": "unknown",
                "detail": "not a run id of the form <task>_<YYYYmmdd_HHMMSS>"}

    record = _read_json(_record_path(run_id), {}) or {}
    summary = _read_json(os.path.join(summary_dir(), "%s_%s.json" % (task_id, stamp)))
    progress = _progress(task_id, stamp)
    # A record with no pid is one that start() wrote just before launching the
    # process. It is starting, not dead, so it counts as running here and the
    # silence rule below is what eventually decides otherwise if the launch
    # never completed.
    running = _alive(record["pid"]) if record.get("pid") else bool(record)

    out = {"run_id": run_id, "task_id": task_id, "run_timestamp": stamp,
           "started_at": record.get("started_at"), "progress": progress}

    if summary is not None:
        out["state"] = "passed" if summary.get("passed_overall") else "failed"
        for key in ("total_fix_attempts", "regression_fails", "apply_failed",
                    "duration_seconds", "stage_iterations"):
            if key in summary:
                out[key] = summary[key]
        out["provenance"] = summary.get("provenance")
        out["artifacts"] = {
            "run_summary": os.path.join(summary_dir(), "%s_%s.json" % (task_id, stamp)),
            "transactions": os.path.join(
                log_dir(), "transactions_%s_%s.jsonl" % (task_id, stamp)),
        }
    elif running and not _silent_too_long(record, progress):
        out["state"] = "running"
    elif running:
        # The pid answers, but nothing has been written for a long time. A
        # reused pid says "alive" about an unrelated process, and believing it
        # would hide the crash this state exists to name.
        out["state"] = "stalled"
        out["detail"] = ("the process id is in use but this run has written "
                         "nothing for over %d minutes, so that pid is probably "
                         "somebody else's now" % (SILENCE_BEFORE_DOUBT // 60))
    elif record:
        out["state"] = "stalled"
        out["detail"] = "the process is gone and no summary was written"
    else:
        out["state"] = "unknown"
        out["detail"] = "no record of this run in %s" % runs_dir()
    return out


def list_runs(limit=20):
    """Known runs, newest first. Reads the directory, not a stored list."""
    try:
        names = [n[:-5] for n in os.listdir(runs_dir()) if n.endswith(".json")]
    except OSError:
        return []
    names.sort(key=lambda n: split_run_id(n)[1] or "", reverse=True)
    return [status(n) for n in names[:limit]]
