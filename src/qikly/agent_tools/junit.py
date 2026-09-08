"""
JUnit XML, so a generated suite can be filed as evidence somewhere else.

qikly already produces the two things a test-management system wants: an
executable suite, and a record of it passing. What it did not produce was
either of them in a format anything else reads. JUnit XML is the format every
tool in that category already ingests, from Xray and qTest and TestRail through
to Jenkins, GitLab and GitHub Actions, and pytest emits it natively. All that
was missing was passing the flag and keeping the files somewhere sensible.

Why the merge exists
--------------------

pytest writes one file per invocation, and a run invokes it once per stage,
many times over. Two decisions follow.

Each stage's file is overwritten on every iteration, so what survives is the
final state of that stage rather than a directory of hundreds of intermediate
failures. Intermediate results are already recorded in the transaction log,
which is the right place for them.

Then the per-stage files are merged into one document at the end of the run,
because "did this task pass" is a question about the whole run, and an importer
handed three files has to be told how they relate. A single `<testsuites>`
element with one `<testsuite>` per stage says it directly.
"""
import os
import xml.etree.ElementTree as ET

JUNIT_DIR = "outputs/reports/junit"


def stage_path(task_id, run_timestamp, stage):
    """Where one stage's XML lives. Overwritten each iteration on purpose."""
    return os.path.join(JUNIT_DIR, f"{task_id}_{run_timestamp}_{stage}.xml")


def merged_path(task_id, run_timestamp):
    return os.path.join(JUNIT_DIR, f"{task_id}_{run_timestamp}.xml")


def _int(elem, name):
    try:
        return int(elem.get(name) or 0)
    except (TypeError, ValueError):
        return 0


def merge(task_id, run_timestamp, stages):
    """
    Combine each stage's XML into one document, and return its path.

    Returns None when no stage produced a file. That is not an error: a run can
    stall before a stage ever executes, and a missing file is the honest report
    of a stage that never ran. Inventing an empty testsuite for it would put a
    passing zero-test stage into the record, which is precisely the kind of
    vacuous green this project exists to prevent.
    """
    root = ET.Element("testsuites", {"name": f"qikly.{task_id}"})
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    found = False

    for stage in stages:
        path = stage_path(task_id, run_timestamp, stage)
        if not os.path.isfile(path):
            continue
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            # A malformed file is skipped rather than failing the run: the
            # report is a convenience, and a run that converged must not be
            # reported as failed because an XML file was truncated.
            continue
        found = True
        # pytest writes <testsuites><testsuite/></testsuites>, so take the
        # inner elements wherever they sit.
        node = tree.getroot()
        suites = node.findall("testsuite") if node.tag == "testsuites" else [node]
        for suite in suites:
            # The stage is the useful name here. pytest names every suite
            # "pytest", which would produce three indistinguishable entries.
            suite.set("name", f"{task_id}.{stage}")
            for key in totals:
                totals[key] += _int(suite, key)
            root.append(suite)

    if not found:
        return None

    for key, value in totals.items():
        root.set(key, str(value))

    out = merged_path(task_id, run_timestamp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return out
