"""
JUnit XML: the one artifact another system reads.

Everything else qikly writes is for a person or for this project's own reports.
JUnit XML is the format test-management tools and CI servers already ingest, so
it is what lets a generated suite be filed as evidence against the ticket its
acceptance criteria came from, instead of staying inside outputs/.

Two properties carry the weight. The merged document must describe the run
honestly, including saying nothing when a stage never ran, and producing it
must never be able to change a run's outcome.
"""
import os
import xml.etree.ElementTree as ET

import pytest

from qikly.agent_tools import junit


SUITE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<testsuites><testsuite name="pytest" errors="0" failures="{f}" '
    'skipped="0" tests="{t}" time="0.1">'
    '<testcase classname="c" name="test_one" time="0.01"/>'
    '</testsuite></testsuites>'
)


def _write(tmp_path, task, stamp, stage, tests=1, failures=0):
    path = junit.stage_path(task, stamp, stage)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(SUITE.format(t=tests, f=failures))
    return path


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(junit, "JUNIT_DIR", str(tmp_path / "junit"))


def test_the_merged_document_carries_one_suite_per_stage(tmp_path):
    for stage in ("integration", "system", "unit"):
        _write(tmp_path, "T", "20260101_000000", stage)

    out = junit.merge("T", "20260101_000000", ["integration", "system", "unit"])
    root = ET.parse(out).getroot()
    assert root.tag == "testsuites"
    assert [s.get("name") for s in root] == [
        "T.integration", "T.system", "T.unit"]


def test_each_suite_is_named_for_its_stage_rather_than_pytest():
    """
    pytest names every suite "pytest". Three identically named suites in one
    document is not a report, it is three anonymous blocks, and the stage is
    the only thing that distinguishes them.
    """
    _write(None, "T", "20260101_000000", "unit")
    out = junit.merge("T", "20260101_000000", ["unit"])
    assert ET.parse(out).getroot()[0].get("name") == "T.unit"


def test_totals_are_summed_across_the_stages():
    _write(None, "T", "20260101_000000", "integration", tests=4, failures=1)
    _write(None, "T", "20260101_000000", "unit", tests=6, failures=2)
    root = ET.parse(junit.merge("T", "20260101_000000", ["integration", "unit"])).getroot()
    assert root.get("tests") == "10"
    assert root.get("failures") == "3"


def test_a_stage_that_never_ran_is_absent_rather_than_an_empty_pass():
    """
    The important one. A run can stall before a later stage executes, and the
    tempting tidiness is to emit an empty testsuite for it so the document has
    a uniform shape. That would file a zero-test passing stage as evidence,
    which is precisely the vacuous green this project exists to prevent.
    """
    _write(None, "T", "20260101_000000", "integration")
    root = ET.parse(junit.merge("T", "20260101_000000", ["integration", "system", "unit"])).getroot()
    assert [s.get("name") for s in root] == ["T.integration"]


def test_a_run_with_no_stage_files_produces_nothing():
    assert junit.merge("T", "20260101_000000", ["integration"]) is None


def test_a_truncated_file_is_skipped_rather_than_raising():
    """
    Reporting must never fail a run that converged. A half-written XML file is
    a reporting problem, and turning it into an exception would report success
    as failure, which is the wrong direction for this project's one guarantee.
    """
    _write(None, "T", "20260101_000000", "integration")
    bad = junit.stage_path("T", "20260101_000000", "unit")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("<testsuites><testsuite")
    root = ET.parse(junit.merge("T", "20260101_000000", ["integration", "unit"])).getroot()
    assert [s.get("name") for s in root] == ["T.integration"]


def test_the_stage_file_is_overwritten_not_accumulated():
    """
    One file per stage, holding its final state. A run makes many attempts, and
    a directory of hundreds of intermediate failures would bury the result. The
    attempts are already in the transaction log, which is where they belong.
    """
    first = _write(None, "T", "20260101_000000", "unit", tests=3)
    second = _write(None, "T", "20260101_000000", "unit", tests=9)
    assert first == second
    assert ET.parse(first).getroot()[0].get("tests") == "9"


def test_run_tests_passes_the_flag_only_when_asked():
    """
    A path argument, not a default. Writing XML on every invocation of every
    stage would produce files nobody asked for in a user's project directory.
    """
    import inspect

    from qikly.agent_tools import run_tests as rt

    source = inspect.getsource(rt.run_tests)
    assert "if junit_path:" in source
    assert "--junitxml=" in source
    # xunit2 is the modern schema and the one current importers expect.
    assert "junit_family=xunit2" in source
