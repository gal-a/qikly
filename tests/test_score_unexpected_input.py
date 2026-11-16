"""
`qikly --score` given something other than a module it can score.

A missing file, a text file and a name in the wrong case were all reported as
"No test files that import it were found", which sent people to look at their
tests for a mistake in the path. And a suite that fails before any fault is
planted printed the right advice but exited 0, which tells a script or CI that
the score was taken.
"""
import os

import pytest

from qikly import cli


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    (tmp_path / "calc.py").write_text("def rate(x):\n    return x\n")
    (tmp_path / "notes.txt").write_text("hello\n")
    (tmp_path / "pkg").mkdir()
    return tmp_path


def test_a_missing_module_is_named_as_missing(here):
    problem = cli._score_target_problem("nope.py")
    assert problem.startswith("No such file: nope.py")


def test_a_text_file_is_named(here):
    assert "is not a Python file" in cli._score_target_problem("notes.txt")


@pytest.mark.skipif(os.name != "nt", reason="only Windows finds a file by another case")
def test_a_name_in_the_wrong_case_says_the_real_name(here):
    problem = cli._score_target_problem("Calc.py")
    assert "The file is called calc.py, not Calc.py" in problem


@pytest.mark.parametrize("target", ["calc.py", "pkg"])
def test_a_module_or_a_folder_is_fine(here, target):
    assert cli._score_target_problem(target) is None


def test_the_command_exits_1_on_a_missing_module(here, capsys):
    assert cli._do_score_suite(None, None, None, code="nope.py") == 1
    assert "No such file" in capsys.readouterr().err


def test_a_suite_that_fails_on_its_own_exits_non_zero(here):
    (here / "calc.py").write_text("def rate(x):\n    if x > 100:\n        return 100\n    return x\n")
    (here / "tests").mkdir()
    (here / "tests" / "test_calc.py").write_text(
        "from calc import rate\n\ndef test_r():\n    assert rate(5) == 6\n")
    assert cli._do_score_suite(None, 2, 0, code="calc.py") == 1


def test_a_suite_that_passes_still_exits_0(here):
    (here / "calc.py").write_text("def rate(x):\n    if x > 100:\n        return 100\n    return x\n")
    (here / "tests").mkdir()
    (here / "tests" / "test_calc.py").write_text(
        "from calc import rate\n\ndef test_r():\n    assert rate(5) == 5\n")
    assert cli._do_score_suite(None, 2, 0, code="calc.py") == 0


def test_a_long_path_gets_the_windows_limit_named():
    exc = FileNotFoundError(2, "No such file or directory", "C:\\" + "d" * 260)
    hint = cli._long_path_hint(exc)
    assert ("260 characters" in hint) == (os.name == "nt")


def test_a_test_that_hangs_is_named_instead_of_hanging(here, monkeypatch, capsys):
    from qikly import start
    monkeypatch.setattr(start, "SUITE_TIMEOUT", 3)
    monkeypatch.delenv("QIKLY_SUITE_TIMEOUT", raising=False)
    (here / "calc.py").write_text("def rate(x):\n    if x > 100:\n        return 100\n    return x\n")
    (here / "tests").mkdir()
    (here / "tests" / "test_calc.py").write_text(
        "import time\nfrom calc import rate\n\ndef test_r():\n    time.sleep(600)\n")
    assert cli._do_score_suite(None, None, None, code="calc.py") == 1
    err = capsys.readouterr().err
    assert "did not finish within 3 seconds" in err and "waiting for input" in err, err


def test_the_scoring_run_has_its_own_limit(here, monkeypatch, capsys):
    # With the number of faults given, the timing step is skipped, so the
    # untouched suite's own limit is what stops it.
    from qikly import mutation_score as ms
    monkeypatch.setattr(ms, "BASELINE_TIMEOUT", 3.0)
    monkeypatch.delenv("QIKLY_SUITE_TIMEOUT", raising=False)
    (here / "calc.py").write_text("def rate(x):\n    if x > 100:\n        return 100\n    return x\n")
    (here / "tests").mkdir()
    (here / "tests" / "test_calc.py").write_text(
        "import time\nfrom calc import rate\n\ndef test_r():\n    time.sleep(600)\n")
    assert cli._do_score_suite(None, 2, 0, code="calc.py") == 1
    assert "did not finish within 3 seconds" in capsys.readouterr().out


def test_a_syntax_error_is_one_line_not_a_traceback(here, capsys):
    (here / "calc.py").write_text("def rate(x:\n    return x\n")
    (here / "tests").mkdir()
    (here / "tests" / "test_calc.py").write_text("from calc import rate\n")
    assert cli._do_score_suite(None, None, None, code="calc.py") == 1
    err = capsys.readouterr().err
    assert "calc.py, line 1, does not parse" in err and "Traceback" not in err, err


def test_named_tests_skip_the_case_check(here):
    # 0.6.2 scored `--score CALC.PY --score-tests ...`; the case only matters
    # when qikly searches for the tests itself.
    assert cli._score_target_problem("Calc.py", check_case=False) is None


def test_a_name_that_exists_exactly_is_never_refused(here, monkeypatch):
    # A case-sensitive disk with both Calc.py and calc.py.
    monkeypatch.setattr(cli.os, "listdir", lambda folder: ["Calc.py", "calc.py", "notes.txt"])
    assert cli._score_target_problem("calc.py") is None


def test_a_slow_suite_can_be_given_more_time(monkeypatch):
    from qikly import mutation_score as ms
    monkeypatch.setenv("QIKLY_SUITE_TIMEOUT", "3600")
    assert ms.suite_limit(900) == 3600
    monkeypatch.setenv("QIKLY_SUITE_TIMEOUT", "nonsense")
    assert ms.suite_limit(900) == 900
    assert "QIKLY_SUITE_TIMEOUT" in ms.stuck_message("x", ["tests"], 900)


def test_a_huge_limit_is_the_largest_the_platform_takes(monkeypatch):
    # 999999999 ended --score in OverflowError from subprocess.
    import threading
    from qikly import mutation_score as ms
    for value in ("999999999", "1e12", "inf", "1e999"):
        monkeypatch.setenv("QIKLY_SUITE_TIMEOUT", value)
        assert ms.suite_limit(900) in (threading.TIMEOUT_MAX, 900), value
    monkeypatch.setenv("QIKLY_SUITE_TIMEOUT", "nan")
    assert ms.suite_limit(900) == 900


def test_ninety_seconds_is_not_one_minute():
    from qikly import mutation_score as ms
    assert "1.5 minutes" in ms.stuck_message("x", ["tests"], 90)
