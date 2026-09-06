import os
import re
import subprocess
import sys

REPORT_DIR = "outputs/reports/iterations"


def _parse_counts(combined_output):
    # Read the LAST line that carries counts, scanning backwards, rather than
    # the literal last line. Two things sit between the two:
    #
    #   - run_tests concatenates stdout and stderr, so anything pytest or a
    #     plugin writes to stderr lands after the summary. Taking the literal
    #     last line then finds nothing and reports a confident 0/0, which looks
    #     like a stage that ran no tests instead of a parser that lost them.
    #   - intermediate lines such as "Interrupted: 1 error during collection"
    #     match the same pattern, so counting every match double counts. The
    #     last matching line is the real summary in both cases.
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}
    pattern = r"(\d+) (passed|failed|error|skipped)"
    for line in reversed([l for l in combined_output.splitlines() if l.strip()]):
        found = re.findall(pattern, line)
        if not found:
            continue
        for num, kind in found:
            counts[kind] += int(num)
        break
    counts["total"] = counts["passed"] + counts["failed"] + counts["error"] + counts["skipped"]
    return counts


def _parse_test_results(combined_output):
    # Verbose pytest output lines look like:
    # outputs/tests/<task_id>/integration/test_integration.py::test_extract_reads_all_rows PASSED [ 33%]
    results = []
    for match in re.finditer(
        r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)\b",
        combined_output,
        re.MULTILINE
    ):
        test_id, status = match.groups()
        results.append((test_id.split("::", 1)[-1], status.lower()))
    return results


def _write_summary_report(task_id, stage, iteration, counts, test_results, run_timestamp, stage_number, total_stages):
    os.makedirs(REPORT_DIR, exist_ok=True)
    # task_id is part of the filename (not just the log line) so two tasks'
    # reports never collide even if their run_timestamps happen to match --
    # a real possibility when several tasks run concurrently as separate
    # processes.
    filename = f"{task_id}_{stage}_{run_timestamp}.txt" if run_timestamp else f"{task_id}_{stage}.txt"
    report_path = os.path.join(REPORT_DIR, filename)

    if stage_number is not None:
        stage_prefix = f"[stage {stage_number}/{total_stages}]" if total_stages else f"[stage {stage_number}]"
        prefix = f"{stage_prefix} [iteration {iteration}]"
    else:
        prefix = f"[iteration {iteration}]"

    if test_results:
        # Real per-test results are available (collection succeeded).
        passed, total = counts["passed"], counts["total"]
        line = f"{prefix} {passed}/{total} passed"
        if passed < total:
            failing = [name for name, status in test_results if status != "passed"]
            line += " | FAILED: " + ", ".join(failing)
    elif counts["error"] and not counts["passed"] and not counts["failed"]:
        # Nothing ran, so the counts say nothing a reader can use. Three of
        # these in a row open the demo and used to be indistinguishable from
        # each other and from the tool spinning, when in fact the first is a
        # deliberate bootstrap against no code and the rest are the agent
        # failing to produce a module that imports.
        if iteration == 0:
            line = (f"{prefix} no code exists yet, so nothing ran: this first "
                    f"failure is expected and costs no attempt")
        else:
            line = f"{prefix} no test ran: the module could not be imported"
    else:
        # Some other shape entirely. Fall back to the aggregate counts, which
        # are then the only signal that exists.
        line = (
            f"{prefix} "
            f"{counts['passed']} passed, {counts['failed']} failed, "
            f"{counts['error']} error, {counts['skipped']} skipped, "
            f"{counts['total']} total"
        )

    with open(report_path, "a", newline="\n") as f:
        f.write(line + "\n")
    print(line)


def run_tests(stage, tests_dir, task_id=None, iteration=None, run_timestamp=None,
              stage_number=None, total_stages=None, junit_path=None):
    """
    Run pytest for the given stage's tests under <tests_dir>/<stage>/ and
    return a structured result:
    {
        "status": "pass" | "fail",
        "raw_output": "<pytest stdout>",
        "failed_tests": [...],
        "counts": {"passed": N, "failed": N, "error": N, "skipped": N, "total": N},
        "tests": [(name, "passed"|"failed"|"error"|"skipped"), ...],
    }
    A pass/fail/total summary, prefixed with the iteration number and followed
    by one line per individual test function, is appended to
    outputs/reports/iterations/<task_id>_<stage>_<run_timestamp>.txt.

    When `junit_path` is given, pytest also writes JUnit XML there, which is
    the format test-management systems and CI servers ingest. It is overwritten
    on every iteration by design, so the file left behind describes the stage's
    final state rather than one of the attempts along the way; the attempts are
    already in the transaction log.
    """

    cmd = [
        sys.executable, "-m", "pytest", os.path.join(tests_dir, stage), "-v", "--disable-warnings",
        # pytest's cache dir defaults to <rootdir>/.pytest_cache, shared by
        # every invocation regardless of task -- across concurrent processes
        # for different tasks that's a real collision risk. Nothing here
        # relies on the cache (no --lf/--ff), so just turn it off.
        "-p", "no:cacheprovider",
        # Ignore the project's own pytest addopts. A user's pyproject.toml can
        # set anything there, and some values silently break the counts this
        # tool reports: -q combines with a -q of our own into -qq, which
        # suppresses pytest's final count line, and every number then parses
        # as zero. A suite that ran and failed becomes indistinguishable from
        # one that never ran.
        "-o", "addopts=",
    ]

    if junit_path:
        os.makedirs(os.path.dirname(junit_path) or ".", exist_ok=True)
        # A JUnit file is a convenience, so it is never allowed to change the
        # outcome of a run: pytest fails the invocation if it cannot write the
        # path, which would turn a reporting problem into a test failure.
        cmd += [f"--junitxml={junit_path}", "-o", "junit_family=xunit2"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
    except Exception as e:
        return {
            "status": "fail",
            "raw_output": str(e),
            "failed_tests": ["pytest_execution_error"]
        }

    stdout = proc.stdout
    stderr = proc.stderr
    combined = stdout + "\n" + stderr

    counts = _parse_counts(combined)
    test_results = _parse_test_results(combined)
    _write_summary_report(task_id, stage, iteration, counts, test_results, run_timestamp, stage_number, total_stages)

    if proc.returncode == 0:
        return {
            "status": "pass",
            "raw_output": combined,
            "failed_tests": [],
            "counts": counts,
            "tests": test_results
        }

    failed = []
    for line in combined.splitlines():
        if "FAILED" in line and "::" in line:
            failed.append(line.strip())

    return {
        "status": "fail",
        "raw_output": combined,
        "failed_tests": failed,
        "counts": counts,
        "tests": test_results
    }
