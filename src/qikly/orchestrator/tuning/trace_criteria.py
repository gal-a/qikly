"""
Which criterion did each generated test come from, for suites already on disk.

Offline and free: it reads the suites under outputs/tests/<task>/ and the
task's acceptance criteria, and makes no model call. `qikly.traceability`
does the parsing; this is the way to run it over a real run's output.

What it is for. Six refinement experiments compared two suites in aggregate
and found nothing, and an aggregate cannot distinguish a bar that adds
nothing from a bar the generator ignores. The measured fact that 54% more
criteria produced a 6% smaller suite says the second is live. Per-criterion
counts make the question direct: delete a criterion, regenerate, and the
change in its row prices that criterion with no fault model in between.

Read `uncovered` as the useful column. A criterion no test names is either a
criterion the generator dropped, which is the research question, or one the
task did not need, which is a specification question. Both are worth seeing
before a run rather than after it.

    python -m qikly.orchestrator.tuning.trace_criteria --tasks ADAS_HEADWAY
    python -m qikly.orchestrator.tuning.trace_criteria --json coverage.json
"""
import json
import os
import sys

from qikly.traceability import coverage

STAGES = ("integration", "system", "unit")


def trace(task_id, tests_dir, stages=STAGES):
    """Coverage for one task, or None when it has no suites and no criteria."""
    from qikly import explain
    from qikly.orchestrator.tuning.check_suites import suite_sources

    found = suite_sources(tests_dir, stages)
    if not found:
        return None
    criteria = explain.build(task_id)["criteria"]
    sources = {"%s/%s" % (stage, name): source for stage, name, source in found}
    result = coverage(sources, len(criteria))
    result["task_id"] = task_id
    result["criteria"] = criteria
    return result


def report(result):
    """One task's coverage, as a block a person reads in the terminal."""
    print("=" * 72)
    print("  %s: %d tests across %d criteria"
          % (result["task_id"], result["tests_total"], result["criteria_count"]))
    print("=" * 72)

    for index, text in enumerate(result["criteria"], start=1):
        count = result["per_criterion"].get(index, 0)
        mark = "  " if count else "!!"
        head = text if len(text) <= 88 else text[:87] + "\u2026"
        print("%s %2d  %2d test(s)  %s" % (mark, index, count, head))

    if result["uncovered"]:
        print()
        print("  No test names criteria: %s"
              % ", ".join(str(i) for i in result["uncovered"]))
    if result["tests_untraced"]:
        print()
        print("  Unlabelled tests (%d), the generator ignored the instruction:"
              % len(result["tests_untraced"]))
        for where in result["tests_untraced"][:10]:
            print("    %s" % where)
        if len(result["tests_untraced"]) > 10:
            print("    ... and %d more" % (len(result["tests_untraced"]) - 10))
    if result["tests_requirements_only"]:
        print()
        print("  From the requirements rather than a criterion: %d"
              % len(result["tests_requirements_only"]))
    if result.get("markers_outside_docstrings"):
        print()
        print("  %d Criteria: line(s) sit in a function body rather than a docstring,"
              % result["markers_outside_docstrings"])
        print("  so they are dead code and are not counted.")
    if result["out_of_range"]:
        print()
        print("  Indices that name no criterion, so the label is wrong:")
        for where, indices in sorted(result["out_of_range"].items()):
            print("    %s -> %s" % (where, ", ".join(str(i) for i in indices)))
    print()
    return len(result["uncovered"])


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Map generated tests to the acceptance criteria they name. "
                    "Reads suites already on disk and makes no model call.")
    parser.add_argument("--tasks", help="comma-separated task ids; all tasks with suites if omitted")
    parser.add_argument("--json", metavar="PATH", help="also write the full mapping as JSON")
    args = parser.parse_args(argv)

    from qikly.orchestrator.orchestrator import GENERATED_TESTS_ROOT, discover_task_ids
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    task_ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_task_ids()

    results, uncovered = [], 0
    for task_id in [t for t in task_ids if t]:
        result = trace(task_id, os.path.join(GENERATED_TESTS_ROOT, task_id))
        if result is None:
            print("[%s] no generated suites on disk; run the task first" % task_id)
            continue
        results.append(result)
        uncovered += report(result)

    if args.json and results:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
        print("wrote %s" % args.json)

    # Advisory. An uncovered criterion is a finding to look at, not a failure:
    # nothing here should be able to fail a build.
    return 0


if __name__ == "__main__":
    sys.exit(main())
