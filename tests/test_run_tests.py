"""
Tests for the pytest output parser.

This module deserves the most scrutiny in the package, because it is the only
place where a subprocess's text becomes a number. Every figure the project
reports (pass counts per iteration, convergence rates, the per stage tables in
the reports) is downstream of these two regexes. A parser bug does not announce
itself: it produces a plausible smaller number and every conclusion drawn from
it is quietly wrong.

So the cases below are mostly about output that does not look like the happy
path: a summary with something after it, a collection error where no test ever
ran, plural nouns, and zero output at all.
"""
import os

import pytest

from qikly.agent_tools import run_tests as rt


# --------------------------------------------------------------- counts ----

def test_counts_read_the_final_summary_line():
    out = (
        "outputs/tests/T/integration/test_i.py::test_a PASSED   [ 50%]\n"
        "outputs/tests/T/integration/test_i.py::test_b FAILED   [100%]\n"
        "\n"
        "============ 1 failed, 1 passed in 0.34s ============\n"
    )
    counts = rt._parse_counts(out)
    assert counts == {"passed": 1, "failed": 1, "error": 0, "skipped": 0, "total": 2}


def test_intermediate_lines_are_not_double_counted():
    """
    "Interrupted: 1 error during collection" matches the same pattern as the
    summary. Counting every match instead of the last line inflates the total.
    """
    out = (
        "!!!!!! Interrupted: 1 error during collection !!!!!!\n"
        "============ 1 error in 0.11s ============\n"
    )
    counts = rt._parse_counts(out)
    assert counts["error"] == 1
    assert counts["total"] == 1


def test_plural_nouns_still_parse():
    out = "==== 3 failed, 2 passed, 4 errors, 1 skipped in 1.20s ====\n"
    counts = rt._parse_counts(out)
    assert counts == {"passed": 2, "failed": 3, "error": 4, "skipped": 1, "total": 10}


def test_no_output_yields_zeros_rather_than_raising():
    assert rt._parse_counts("")["total"] == 0
    assert rt._parse_counts("\n  \n")["total"] == 0


def test_counts_survive_output_after_the_summary():
    """
    run_tests concatenates stdout and stderr, so anything pytest or a plugin
    writes to stderr lands AFTER the summary line. Taking the literal last
    line then finds no counts and reports a confident 0/0, which looks like a
    task that ran no tests rather than a parser that lost them.
    """
    out = (
        "==== 2 failed, 5 passed in 0.42s ====\n"
        "\n"
        "DeprecationWarning: ssl module is deprecated\n"
    )
    counts = rt._parse_counts(out)
    assert counts["passed"] == 5
    assert counts["failed"] == 2
    assert counts["total"] == 7


def test_the_last_summary_wins_when_several_appear():
    """A rerun plugin can emit more than one summary; the final one is the run."""
    out = (
        "==== 3 failed, 1 passed in 0.20s ====\n"
        "rerunning failures\n"
        "==== 1 failed, 3 passed in 0.25s ====\n"
    )
    counts = rt._parse_counts(out)
    assert counts["failed"] == 1
    assert counts["passed"] == 3


# -------------------------------------------------------- per test rows ----

def test_test_results_are_parsed_with_names_only():
    out = (
        "outputs/tests/T/unit/test_u.py::test_alpha PASSED  [ 33%]\n"
        "outputs/tests/T/unit/test_u.py::test_beta FAILED   [ 66%]\n"
        "outputs/tests/T/unit/test_u.py::test_gamma SKIPPED [100%]\n"
    )
    assert rt._parse_test_results(out) == [
        ("test_alpha", "passed"),
        ("test_beta", "failed"),
        ("test_gamma", "skipped"),
    ]


def test_windows_paths_and_parametrised_ids_parse():
    out = (
        r"outputs\tests\T\unit\test_u.py::test_p[1-a] PASSED [ 50%]" "\n"
        r"outputs\tests\T\unit\test_u.py::TestC::test_m ERROR [100%]" "\n"
    )
    names = rt._parse_test_results(out)
    assert names[0][0] == "test_p[1-a]"
    assert names[1] == ("TestC::test_m", "error")


def test_prose_mentioning_a_status_is_not_a_result_row():
    out = "The suite FAILED to collect because the module was missing\n"
    assert rt._parse_test_results(out) == []


# ------------------------------------------------------------- reports -----

def test_report_filename_carries_the_task_id(tmp_path, monkeypatch):
    """
    Tasks run concurrently as separate processes and can share a timestamp, so
    the task_id has to be in the filename and not only in the line.
    """
    monkeypatch.setattr(rt, "REPORT_DIR", str(tmp_path))
    counts = {"passed": 2, "failed": 0, "error": 0, "skipped": 0, "total": 2}
    rows = [("test_a", "passed"), ("test_b", "passed")]
    rt._write_summary_report("CALC_TAX", "unit", 1, counts, rows, "20260826_120000", 3, 3)
    rt._write_summary_report("ETL_EMAIL", "unit", 1, counts, rows, "20260826_120000", 3, 3)

    names = sorted(os.listdir(tmp_path))
    assert names == ["CALC_TAX_unit_20260826_120000.txt",
                     "ETL_EMAIL_unit_20260826_120000.txt"]


def test_report_names_the_failing_tests_and_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "REPORT_DIR", str(tmp_path))
    counts = {"passed": 1, "failed": 1, "error": 0, "skipped": 0, "total": 2}
    rows = [("test_a", "passed"), ("test_b", "failed")]
    rt._write_summary_report("T", "unit", 1, counts, rows, "TS", 1, 3)
    rt._write_summary_report("T", "unit", 2, counts, rows, "TS", 1, 3)

    text = (tmp_path / "T_unit_TS.txt").read_text()
    lines = text.strip().splitlines()
    assert len(lines) == 2, "each iteration appends rather than overwriting"
    assert lines[0] == "[stage 1/3] [iteration 1] 1/2 passed | FAILED: test_b"
    assert "[iteration 2]" in lines[1]


def test_a_collection_error_is_reported_as_nothing_having_run(tmp_path, monkeypatch):
    """
    No per-test rows exist after a collection error, so the line has to carry
    the meaning instead of the counts.

    It used to print "0 passed, 0 failed, 1 error, 0 skipped, 1 total", which
    is accurate and tells a reader nothing: four numbers, three of them zero,
    describing an event that is not a test failure at all. Three of these open
    the demo, and they read as the tool spinning.
    """
    monkeypatch.setattr(rt, "REPORT_DIR", str(tmp_path))
    counts = {"passed": 0, "failed": 0, "error": 1, "skipped": 0, "total": 1}
    rt._write_summary_report("T", "integration", 4, counts, [], "TS", None, None)

    line = (tmp_path / "T_integration_TS.txt").read_text().strip()
    assert line.startswith("[iteration 4] ")
    assert "could not be imported" in line
    assert "FAILED:" not in line, "nothing failed, because nothing ran"


# ---------------------------------------------------------- end to end -----

@pytest.fixture
def suite(tmp_path, monkeypatch):
    """A real two test stage on disk, so pytest is actually invoked."""
    monkeypatch.setattr(rt, "REPORT_DIR", str(tmp_path / "reports"))
    stage_dir = tmp_path / "tests" / "integration"
    stage_dir.mkdir(parents=True)
    return tmp_path, stage_dir


def test_run_tests_reports_a_real_pass(suite):
    tmp_path, stage_dir = suite
    (stage_dir / "test_ok.py").write_text(
        "def test_one():\n    assert 1 == 1\n"
        "def test_two():\n    assert 2 == 2\n")

    result = rt.run_tests("integration", str(tmp_path / "tests"),
                          task_id="T", iteration=1, run_timestamp="TS")
    assert result["status"] == "pass"
    assert result["counts"]["passed"] == 2
    assert result["counts"]["total"] == 2
    assert result["failed_tests"] == []
    assert sorted(n for n, _ in result["tests"]) == ["test_one", "test_two"]


def test_run_tests_reports_a_real_failure(suite):
    tmp_path, stage_dir = suite
    (stage_dir / "test_bad.py").write_text(
        "def test_good():\n    assert True\n"
        "def test_bad():\n    assert False\n")

    result = rt.run_tests("integration", str(tmp_path / "tests"),
                          task_id="T", iteration=1, run_timestamp="TS")
    assert result["status"] == "fail"
    assert result["counts"]["passed"] == 1
    assert result["counts"]["failed"] == 1
    assert any("test_bad" in line for line in result["failed_tests"])


def test_run_tests_survives_a_module_that_cannot_be_imported(suite):
    """
    A generated test file with a syntax error must come back as a fail with
    output the FIX prompt can read, not as an exception that ends the run.
    """
    tmp_path, stage_dir = suite
    (stage_dir / "test_broken.py").write_text("def test_x(:\n    pass\n")

    result = rt.run_tests("integration", str(tmp_path / "tests"),
                          task_id="T", iteration=1, run_timestamp="TS")
    assert result["status"] == "fail"
    assert result["raw_output"].strip(), "the error text is what the agent gets to fix"


# ------------------------------------------- immunity to project config ----

def test_the_projects_own_addopts_are_neutralised():
    """
    The counts are parsed out of pytest's final summary line, and a host
    project can suppress that line through its own configuration. This
    repository sets addopts = "-q"; combined with a -q of the tool's own that
    becomes -qq, and -qq prints no count line at all. Every number then parses
    as zero, which is indistinguishable from a suite that ran nothing.

    It is not hypothetical: it silently emptied the cross-arm measurement of a
    whole experiment run.
    """
    import inspect
    src = inspect.getsource(rt.run_tests)
    assert '"-o", "addopts="' in src or "'-o', 'addopts='" in src


def test_this_project_does_not_set_quiet_on_its_own_contributors():
    """
    The same collision, pointed the other way. With addopts = "-q" here, a
    contributor typing the ordinary `pytest -q` gets -qq and a bare "100%":
    no count of what ran, and no count of what failed. The tool protects
    itself with -o addopts=; a person typing pytest by hand has no such guard,
    so the setting simply should not be here.
    """
    # Read as text rather than parsed: tomllib is 3.11+, and this package
    # supports 3.10.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as handle:
        lines = [ln.strip() for ln in handle if ln.strip().startswith("addopts")]
    for line in lines:
        assert "-q" not in line.split(), (
            f"pyproject has {line!r}; a -q here becomes -qq for anyone typing -q"
        )


def test_counts_survive_a_project_that_sets_quiet(tmp_path, monkeypatch):
    """
    End to end: put an addopts that would suppress the summary into a config
    the child pytest will read, and check the counts still come back.
    """
    monkeypatch.setattr(rt, "REPORT_DIR", str(tmp_path / "reports"))
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n", encoding="utf-8")
    stage = tmp_path / "tests" / "integration"
    stage.mkdir(parents=True)
    (stage / "test_x.py").write_text(
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert False\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = rt.run_tests("integration", str(tmp_path / "tests"),
                          task_id="T", iteration=1, run_timestamp="TS")
    assert result["counts"]["total"] == 2, "the summary line must survive"
    assert result["counts"]["passed"] == 1
    assert result["counts"]["failed"] == 1


def test_the_research_harnesses_pin_their_pytest_rootdir():
    """
    Same class as the addopts collision: the host environment leaking into a
    pytest subprocess we spawn.

    false_rejection and shared_substrate run archived suites from throwaway
    directories. Without an explicit --rootdir, pytest walks up from the test
    path and settles on the shared system temp directory, so every concurrent
    run in this project resolves to the SAME rootdir, shares whatever conftest
    chain is there, and names modules relative to it.

    The symptom was a test file that failed roughly one run in three, with a
    different test failing each time and the counts reporting one test where
    two had run. Pinning the rootdir took it to zero failures in eight runs and
    halved the wall time, because pytest stopped scanning the temp tree.
    """
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = []
    for name in ("false_rejection.py", "shared_substrate.py"):
        path = os.path.join(root, "research", name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for call in re.finditer(r'\[sys\.executable,\s*"-m",\s*"pytest".*?\]', text,
                                re.S):
            if "--rootdir" not in call.group(0):
                missing.append(name)
    assert not missing, (
        "these spawn pytest without pinning --rootdir, so it resolves to the "
        "shared temp directory: " + ", ".join(sorted(set(missing))))
