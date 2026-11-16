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
