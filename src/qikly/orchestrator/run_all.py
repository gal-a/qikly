"""
Master sweep across every task: run.py (real convergence), then
gen_and_eval_acceptance_criteria.py (one-shot generation vs. real criteria), then
refine_acceptance_criteria.py --all (iterative refinement) -- everything
needed to judge how the tool performs across the full task catalog in one
invocation, rather than three separate commands typed by hand.

This is genuinely expensive, dominated by the last stage:
refine_acceptance_criteria.py alone is up to --rounds full multi-iteration
convergence runs PER TASK, times every task in the catalog -- 9 tasks at
the default 3 rounds is potentially dozens of full convergence runs.
Budget real time (likely well over an hour) and a real number of LLM
calls. Prints a cost estimate and asks for confirmation before starting
(skip the prompt with --yes; skip the expensive stage entirely with
--skip-refine).

Each stage is invoked as a genuinely separate `python` subprocess (not
imported and called in-process) -- this is deliberate: run.py's own
multiprocessing, and each script's own os.chdir()/argparse setup, all
behave exactly as if you'd typed the command yourself, with no risk of
this wrapper's own process state leaking into or interfering with theirs.
A stage failing doesn't stop the sweep -- the whole point is judging
performance across every task, and one task's convergence failure
shouldn't prevent the other stages from still running.

--repeat N runs the whole configured sweep N times and then aggregates the
result. That exists because convergence is not deterministic: real sweeps of
the same nine tasks have come back 5/9, 6/9 and 8/9, and one task has stalled
on a run using the same inputs and seed that passed the day before. One sweep
is a single draw, so quoting its pass count as a measurement claims more than
one run can support. Repeating produces a rate with an interval instead.

It multiplies cost by N, so pair it with the skip flags: --repeat 10
--skip-eval --skip-refine repeats only the convergence stage, which is the
one whose variance is actually in question, and leaves the expensive
criteria-tuning stages out of the loop entirely.

    python -m orchestrator.run_all
    python -m orchestrator.run_all --tasks ETL_NAME_SPLIT,MERGE_SALES  # just these tasks
    python -m orchestrator.run_all --rounds 2           # cheaper refine stage
    python -m orchestrator.run_all --skip-refine         # skip the expensive stage
    python -m orchestrator.run_all --skip-run --skip-eval  # only refine_
    python -m orchestrator.run_all --repeat 10 --skip-eval --skip-refine  # convergence variance
    python -m orchestrator.run_all --yes                 # no confirmation prompt
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

from qikly.paths import chdir_to_project_root

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/reports/run_all"
RUN_SUMMARY_DIR = "outputs/reports/run_summary"
AGGREGATE_DIR = "outputs/reports/aggregate"
DEFAULT_ROUNDS = 3


def _run_summary_files():
    """
    Snapshot of the per-run summary files on disk. Diffing this before and
    after the sweep is how the repetitions get identified without run.py
    having to report back: run.py already writes one summary per task per
    run, and anything new since the snapshot belongs to this invocation.
    """
    return set(glob.glob(os.path.join(RUN_SUMMARY_DIR, "*.json")))


def _run_timestamps_from(paths):
    """
    Read each summary's own run_timestamp rather than parsing it out of the
    filename: both task_id and the timestamp contain underscores, so filename
    splitting is ambiguous for any task_id whose name gains a part later.
    """
    stamps = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                stamp = json.load(f).get("run_timestamp")
        except (OSError, json.JSONDecodeError):
            continue
        if stamp:
            stamps.add(stamp)
    return stamps


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Run run.py, gen_and_eval_acceptance_criteria.py, and refine_acceptance_criteria.py "
                    "across every task in one sweep, to judge performance across the full catalog."
    )
    parser.add_argument(
        "--tasks", default=None,
        help="Comma-separated task_ids to scope every stage to, e.g. ETL_NAME_SPLIT,MERGE_SALES "
             "(default: every task under inputs/config/tasks/). Passed through as run.py's "
             "--tasks, gen_and_eval_acceptance_criteria.py's --task, and refine_acceptance_criteria.py's "
             "--task (replacing --all)."
    )
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="Rounds for the refine_ stage")
    parser.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="Repeat the whole configured sweep N times and write an aggregate report "
             "across the repetitions (convergence rate with a confidence interval, rather "
             "than one sweep's pass count). Multiplies cost by N -- pair with --skip-eval "
             "--skip-refine to repeat only the convergence stage."
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--skip-run", action="store_true", help="Skip the run.py stage")
    parser.add_argument("--skip-eval", action="store_true", help="Skip the gen_and_eval_acceptance_criteria.py stage")
    parser.add_argument("--skip-refine", action="store_true", help="Skip refine_acceptance_criteria.py (the expensive stage)")
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation prompt")
    return parser.parse_args()


def _subprocess_env(extra=None):
    """
    Every stage but the first is launched as `python -m qikly...`,
    which needs the package importable in the child. From a plain clone it
    isn't: the src layout deliberately keeps it off sys.path, which is why
    run.py carries its own sys.path line. Stage 1 therefore worked from a
    clone while every -m stage died with ModuleNotFoundError.

    This process has already imported the package, so its location is known.
    Putting that directory on the child's PYTHONPATH makes a clone behave the
    same as an install, and is a no-op when the package really is installed.
    """
    import qikly
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(qikly.__file__)))
    env = {**os.environ}
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([pkg_parent] + ([existing] if existing else []))
    if extra:
        env.update(extra)
    return env


def _run_stage(label, cmd, env=None):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"[{label}] exited with code {result.returncode} -- continuing to the next stage anyway")
    return result.returncode


def main():
    from qikly.console import use_utf8

    use_utf8()

    from qikly.orchestrator.orchestrator import discover_task_ids

    args = _parse_args()
    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        unknown = sorted(set(task_ids) - set(discover_task_ids()))
        if unknown:
            print(f"Unknown task_id(s): {', '.join(unknown)} -- not found under inputs/config/tasks/")
            return
    else:
        task_ids = discover_task_ids()
    n = len(task_ids)

    if args.repeat < 1:
        print(f"--repeat must be at least 1 (got {args.repeat}).")
        return
    reps = args.repeat

    print(f"{'Scoped to' if args.tasks else 'Discovered'} {n} task(s): {', '.join(task_ids)}")
    print(f"\nThis sweep runs, in order{f', {reps} times over' if reps > 1 else ''}:")
    if not args.skip_run:
        print(f"  1. run.py                                  -- {n * reps} real convergence runs "
              f"({n} per repetition)")
    if not args.skip_eval:
        print(f"  2. gen_and_eval_acceptance_criteria.py      -- {n * reps} one-shot generation calls")
    if not args.skip_refine:
        print(f"  3. refine_acceptance_criteria.py            -- up to {n} x {args.rounds} x {reps} = "
              f"{n * args.rounds * reps} additional full convergence runs -- the expensive stage")
    if reps > 1:
        print(f"\n  Each repetition runs with its own seed, so the repetitions are independent")
        print(f"  draws rather than reruns of one seed. An aggregate report over all {reps} is")
        print(f"  written to {AGGREGATE_DIR}/ at the end.")
    elif not args.skip_run:
        # This script exists to judge performance across the catalog, and at
        # --repeat 1 it cannot: convergence varies run to run, so a single
        # sweep's pass count is one draw, not a measurement. Said before the
        # spend rather than after, in the same register as the cost estimate
        # below -- the failure mode is a confident claim, not a wasted run.
        print("\n  NOTE: --repeat is 1, so this sweep produces output, not a measurement.")
        print("  Convergence is not deterministic -- the same task with the same seed")
        print("  converges on some runs and exhausts its budget on others -- so this run's")
        print("  pass count cannot support a claim about how often anything converges.")
        print("  Repeat when you are making a claim; run once when you want the artifacts.")
        print("  For a rate with a confidence interval: --repeat 10 (see --help).")
    print()

    if not args.yes:
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    os.makedirs(LOG_DIR, exist_ok=True)
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = os.path.join(LOG_DIR, f"run_all_{run_timestamp}.txt")

    scope_label = f"tasks: {args.tasks}" if args.tasks else "all tasks"
    summaries_before = _run_summary_files()

    # Repetitions vary run.py's seed so they sample real run-to-run variation
    # rather than re-running one seed N times. Pinning a single seed across
    # repetitions would measure only the model's own nondeterminism, which is
    # a narrower question than "how often does this task converge".
    from qikly.cli import HARDCODED_SEED
    base_seed = args.seed if args.seed is not None else HARDCODED_SEED

    # Per-repetition summary accounting. A repetition is meant to produce one
    # run summary per task; anything less means runs happened (or didn't) that
    # the aggregate report will never see, because it can only read summaries
    # that exist. Silently averaging over a subset is how a convergence rate
    # ends up unfalsifiable, so the shortfall is counted here and reported.
    seen_summaries = set(summaries_before)
    rep_counts = []

    results = defaultdict(list)
    for rep in range(reps):
        if reps > 1:
            print(f"\n{'#' * 70}\n# Repetition {rep + 1} of {reps}\n{'#' * 70}")
        rep_label = f" [rep {rep + 1}/{reps}]" if reps > 1 else ""

        if not args.skip_run:
            cmd = [sys.executable, "run.py"]
            if args.tasks:
                cmd += ["--tasks", args.tasks]
            seed_override = None
            if reps > 1 and base_seed is not None:
                seed_override = {"AGENT_SEED": str(base_seed + rep)}
            results["run.py"].append(_run_stage(
                f"Stage 1: run.py ({scope_label}){rep_label}", cmd,
                env=_subprocess_env(seed_override)
            ))
            now = _run_summary_files()
            produced = len(now - seen_summaries)
            seen_summaries = now
            rep_counts.append(produced)
            if produced != n:
                print(f"  [accounting] repetition {rep + 1} produced {produced} run "
                      f"summar{'y' if produced == 1 else 'ies'}, expected {n}. "
                      f"{n - produced} run(s) will be missing from the aggregate.")

        if not args.skip_eval:
            cmd = [sys.executable, "-m", "qikly.orchestrator.tuning.gen_and_eval_acceptance_criteria"]
            if args.tasks:
                cmd += ["--task", args.tasks]
            if args.seed is not None:
                cmd += ["--seed", str(args.seed)]
            results["gen_and_eval_acceptance_criteria"].append(_run_stage(
                f"Stage 2: gen_and_eval_acceptance_criteria.py ({scope_label}){rep_label}", cmd,
                env=_subprocess_env()
            ))

        if not args.skip_refine:
            cmd = [sys.executable, "-m", "qikly.orchestrator.tuning.refine_acceptance_criteria"]
            cmd += ["--task", args.tasks] if args.tasks else ["--all"]
            cmd += ["--rounds", str(args.rounds)]
            if args.seed is not None:
                cmd += ["--seed", str(args.seed)]
            results["refine_acceptance_criteria"].append(_run_stage(
                f"Stage 3: refine_acceptance_criteria.py ({scope_label}){rep_label}", cmd,
                env=_subprocess_env()
            ))

    expected_runs = n * reps if not args.skip_run else 0
    observed_runs = sum(rep_counts)
    shortfall = expected_runs - observed_runs
    short_reps = [i + 1 for i, c in enumerate(rep_counts) if c != n]
    if shortfall:
        print(f"\n{'!' * 70}")
        print(f"! ACCOUNTING GAP: {observed_runs} of {expected_runs} expected runs produced a summary.")
        print(f"! {shortfall} run(s) ({100 * shortfall / expected_runs:.0f}%) are missing and are NOT")
        print(f"! counted as failures -- they are absent from the rate entirely, so any")
        print(f"! convergence rate below is computed over {observed_runs} runs, not {expected_runs}.")
        print(f"! Short repetitions: {', '.join(str(r) for r in short_reps)}")
        print(f"! Check the console output above for those repetitions before quoting the rate.")
        print(f"{'!' * 70}")

    aggregate_path = None
    new_stamps = _run_timestamps_from(_run_summary_files() - summaries_before)
    if reps > 1 and new_stamps:
        _run_stage(
            f"Aggregate: {len(new_stamps)} run timestamp(s) across {reps} repetitions",
            [sys.executable, "-m", "qikly.orchestrator.reports.aggregate_report",
             "--runs", ",".join(sorted(new_stamps)), "--label", run_timestamp],
            env=_subprocess_env(),
        )
        aggregate_path = os.path.join(AGGREGATE_DIR, f"aggregate_{run_timestamp}.html")
    elif reps > 1:
        print("\nNo new run summaries were written, so there is nothing to aggregate.")
        print("(--repeat only produces them via the run.py stage; --skip-run disables that.)")

    with open(summary_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"run_all sweep -- {run_timestamp}\n")
        f.write(f"tasks: {', '.join(task_ids)}\n")
        f.write(f"repetitions: {reps}\n")
        if not args.skip_run:
            f.write(f"runs expected: {expected_runs} ({n} task(s) x {reps} repetition(s))\n")
            f.write(f"runs with a summary: {observed_runs}\n")
            if shortfall:
                f.write(f"MISSING: {shortfall} run(s) produced no summary and are excluded from\n"
                        f"  the aggregate rate entirely -- not counted as failures. Short\n"
                        f"  repetitions: {', '.join(str(r) for r in short_reps)}\n")
        f.write("\n")
        for stage, codes in results.items():
            rendered = ", ".join(str(c) for c in codes)
            f.write(f"{stage}: exit code{'s' if len(codes) > 1 else ''} {rendered}\n")
        f.write(
            "\nThis file is just a pointer, not a replacement for the real results:\n"
            "  outputs/reports/iterations/       -- per-task debugging timelines (stage 1)\n"
            "  outputs/reports/metrics/           -- per-task KPI reports (stage 1)\n"
            "  outputs/reports/acceptance_criteria/  -- gen_and_eval_/refine_ logs (stages 2-3)\n"
        )
        if reps > 1 and new_stamps:
            f.write(f"  outputs/reports/aggregate/         -- convergence rate across all {reps} repetitions\n")

    print(f"\nDone. Summary: {summary_path}")
    print("Real results are in outputs/reports/iterations/, outputs/reports/metrics/,")
    print("and outputs/reports/acceptance_criteria/ -- read those, not just this summary.")
    if aggregate_path:
        print(f"Aggregate across repetitions: {aggregate_path}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
