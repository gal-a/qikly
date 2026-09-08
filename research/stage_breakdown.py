"""
Where a sweep's runs stopped, stage by stage.

The aggregate report answers "how many runs converged". It does not answer
"how many cleared integration and system", and that second number is the one
the gap argument rests on: nearly all of the distance between the two is the
unit stage.

That figure was quoted in the design write-up and README.md for some time
with no
artifact behind it, which is exactly the situation MAINTAIN.md exists to
prevent. This script recomputes it from the run summaries the aggregate
itself counted, so the number can be checked rather than trusted.

    python research/stage_breakdown.py outputs/reports/aggregate/<file>.json

One caution learned the hard way. `AGG_RUNLOG` looks like an internal artifact
and is in fact one of the ten tasks, "AGG - Run log aggregation". Dropping it
moves integration+system from 83% to 86%. Select runs by the aggregate's own
task keys, never by guessing which keys are real.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stats_helpers import wilson

SUMMARY_DIR = os.path.join("outputs", "reports", "run_summary")


def breakdown(aggregate_path, summary_dir=SUMMARY_DIR):
    """Convergence and integration+system rates over one aggregate's runs.

    A run cleared integration and system exactly when the unit stage ran at
    all: the stages are ordered, so a `unit` entry in `stage_iterations` is
    the record that everything before it passed.
    """
    with open(aggregate_path, encoding="utf-8") as handle:
        report = json.load(handle)

    converged = cleared = matched = 0
    missing = []
    for task, entry in report["tasks"].items():
        for stamp in entry["run_timestamps"]:
            path = os.path.join(summary_dir, f"{task}_{stamp}.json")
            if not os.path.exists(path):
                missing.append(path)
                continue
            with open(path, encoding="utf-8") as handle:
                run = json.load(handle)
            matched += 1
            converged += bool(run["passed_overall"])
            cleared += "unit" in (run.get("stage_iterations") or {})

    return {
        "aggregate": os.path.basename(aggregate_path),
        "runs": matched,
        "missing_summaries": len(missing),
        "converged": converged,
        "cleared_integration_and_system": cleared,
        "converged_rate": converged / matched if matched else 0.0,
        "cleared_rate": cleared / matched if matched else 0.0,
        "converged_ci": wilson(converged, matched),
        "cleared_ci": wilson(cleared, matched),
        "unit_stage_gap_points": round(100 * (cleared - converged) / matched)
        if matched else 0,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__.strip().split("\n\n")[0])
        print("\nusage: python research/stage_breakdown.py <aggregate.json>")
        return 2

    result = breakdown(argv[0])
    if result["missing_summaries"]:
        print(f"warning: {result['missing_summaries']} run summaries missing, "
              f"rates are over the {result['runs']} that were found")

    for label, key, ci in (
            ("converged, unit tests included", "converged", "converged_ci"),
            ("cleared integration + system", "cleared_integration_and_system",
             "cleared_ci")):
        rate = result[key] / result["runs"] * 100
        low, high = (100 * b for b in result[ci])
        print(f"  {label:32} {result[key]:>4}/{result['runs']} = {rate:4.1f}%"
              f"   95% CI {low:.0f} to {high:.0f}")
    print(f"\n  the unit stage accounts for {result['unit_stage_gap_points']} "
          f"points of the difference")

    out = os.path.join(os.path.dirname(argv[0]),
                       "stage_" + os.path.basename(argv[0]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(f"\n  written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
