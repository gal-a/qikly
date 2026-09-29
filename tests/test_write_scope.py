"""
The guard that says when a fault is somewhere the task may not write.

Two signals with different blind spots, so each is pinned separately, and one
test holds the reason both exist: pytest names a helper's file when the helper
raises and never names it when the helper merely returns the wrong value.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from qikly.orchestrator.write_scope import (
    blocked_fault_message,
    implicated_files,
    unreachable_import_hint,
    unwritable_imports,
    workaround_warning,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root with a task directory, a tests directory and a helper."""
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / "PRICING"
    tests = root / "outputs" / "tests" / "PRICING"
    _write(str(root / "helpers" / "__init__.py"), "")
    _write(str(root / "helpers" / "money.py"), """
        def to_cents(amount):
            return int(amount * 100)
    """)
    _write(str(code / "pricing.py"), """
        from helpers.money import to_cents


        def total_cents(amount):
            return to_cents(amount)
    """)
    _write(str(tests / "test_pricing.py"), "def test_nothing():\n    pass\n")
    monkeypatch.chdir(root)
    return {"root": str(root), "code": str(code), "tests": str(tests)}


# --- the static signal -------------------------------------------------------

def test_a_helper_imported_from_outside_the_task_is_named(project):
    assert unwritable_imports(project["code"]) == ["helpers/money.py"]


def test_a_task_that_imports_nothing_local_reports_nothing(project):
    _write(os.path.join(project["code"], "pricing.py"), """
        import json


        def total_cents(amount):
            return json.dumps(amount)
    """)
    assert unwritable_imports(project["code"]) == []


def test_a_sibling_inside_the_task_is_not_out_of_scope(project):
    """The task owns its whole directory, so a module it wrote is writable."""
    _write(os.path.join(project["code"], "rounding.py"), "def half_up(x):\n    return x\n")
    _write(os.path.join(project["code"], "pricing.py"), """
        import rounding


        def total_cents(amount):
            return rounding.half_up(amount)
    """)
    assert unwritable_imports(project["code"]) == []


def test_a_relative_import_is_never_out_of_scope(project):
    """`from .x import y` cannot reach outside the package it is written in."""
    _write(os.path.join(project["code"], "pricing.py"), """
        from .rounding import half_up


        def total_cents(amount):
            return half_up(amount)
    """)
    assert unwritable_imports(project["code"]) == []


def test_a_half_written_implementation_does_not_fail_the_run(project):
    """Between patches the file can be unparseable. That is not an error."""
    _write(os.path.join(project["code"], "pricing.py"), "def total_cents(\n")
    assert unwritable_imports(project["code"]) == []


def test_a_null_byte_in_the_source_does_not_kill_the_run(project):
    """
    Found by audit 2026-09-29. `ast.parse` raises ValueError rather than
    SyntaxError on a NUL byte, so an `except SyntaxError` let it through and
    a diagnostic would have ended a run that was working.
    """
    with open(os.path.join(project["code"], "pricing.py"), "wb") as handle:
        handle.write(b"from helpers.money import to_cents\n\x00\n")
    assert unwritable_imports(project["code"]) == []


def test_a_file_that_cannot_be_read_is_skipped_rather_than_raised(project, monkeypatch):
    import builtins

    real_open = builtins.open

    def refuse(path, *args, **kwargs):
        if str(path).endswith("pricing.py"):
            raise PermissionError(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refuse)
    assert unwritable_imports(project["code"]) == []


def test_a_missing_code_directory_reports_nothing(project):
    assert unwritable_imports(os.path.join(project["root"], "nope")) == []


# --- the dynamic signal ------------------------------------------------------

def test_a_frame_in_a_helper_is_reported(project):
    raw = "helpers/money.py:2: in to_cents\n    raise ValueError('x')\n"
    assert implicated_files(raw, project["code"], project["tests"]) == ["helpers/money.py"]


def test_the_task_s_own_code_is_never_reported(project):
    raw = "outputs/agent_src/code/PRICING/pricing.py:5: in total_cents\n"
    assert implicated_files(raw, project["code"], project["tests"]) == []


def test_the_generated_tests_are_never_reported(project):
    raw = "outputs/tests/PRICING/test_pricing.py:9: AssertionError\n"
    assert implicated_files(raw, project["code"], project["tests"]) == []


def test_a_file_outside_the_project_is_never_reported(project):
    """pytest's own frames and every installed dependency stay out."""
    raw = "%s:404: in call\n" % os.path.join(
        os.path.dirname(project["root"]), "site-packages", "pluggy", "_hooks.py")
    assert implicated_files(raw, project["code"], project["tests"]) == []


def test_a_path_that_does_not_exist_is_not_invented(project):
    raw = "helpers/ghost.py:1: in nothing\n"
    assert implicated_files(raw, project["code"], project["tests"]) == []


def test_an_unnormalised_absolute_path_still_matches(project):
    """pytest prints one when the helper is reached through sys.path."""
    raw = "%s:2: ValueError: bad amount\n" % os.path.join(
        project["root"], "outputs", "..", "helpers", "money.py")
    assert implicated_files(raw, project["code"], project["tests"]) == ["helpers/money.py"]


def test_a_conftest_is_test_infrastructure_wherever_it_sits(project):
    _write(os.path.join(project["root"], "conftest.py"), "")
    raw = "conftest.py:1: in <module>\n"
    assert implicated_files(raw, project["code"], project["tests"]) == []


def test_the_same_helper_named_twice_is_reported_once(project):
    raw = ("helpers/money.py:2: in to_cents\n"
           "helpers/money.py:7: in to_cents\n")
    assert implicated_files(raw, project["code"], project["tests"]) == ["helpers/money.py"]


def test_a_path_with_spaces_in_it_is_still_found(tmp_path, monkeypatch):
    """`C:\\Program Files\\...` is an ordinary place for a project to live."""
    root = tmp_path / "with space"
    _write(str(root / "shared lib" / "money.py"), "def to_cents(x):\n    return x\n")
    monkeypatch.chdir(root)
    raw = "%s:2: in to_cents\n" % os.path.join(str(root), "shared lib", "money.py")
    assert implicated_files(raw, "code", "tests", str(root)) == ["shared lib/money.py"]


def test_a_long_unbroken_line_does_not_stall_the_loop(project):
    """
    Found by audit 2026-09-29, and the reason the path is walked rather than
    matched. The pattern this replaced took 15.6s over 40,000 characters and
    315s over 200,000, quadrupling for every doubling, and it ran on every
    attempt of the convergence loop against output that is never truncated.
    pytest prints one unbroken line whenever it compares two long strings.
    """
    import time

    raw = "E   assert " + ("A" * 200_000) + " == 1\n"
    started = time.time()
    assert implicated_files(raw, project["code"], project["tests"]) == []
    elapsed = time.time() - started
    assert elapsed < 2.0, "took %.1fs on 200k characters" % elapsed


def test_one_helper_named_in_thousands_of_frames_stays_cheap(project):
    """
    The normal shape of a bad run, not a pathological one: a helper called
    once per row fails once per row, so the same path arrives thousands of
    times. Each distinct candidate is decided once rather than re-stated.
    """
    import time

    raw = "helpers/money.py:2: in to_cents\n" * 40_000
    started = time.time()
    assert implicated_files(raw, project["code"], project["tests"]) == ["helpers/money.py"]
    elapsed = time.time() - started
    assert elapsed < 2.0, "took %.1fs on 40,000 repeated frames" % elapsed


def test_the_answer_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    """
    Every entry point chdirs to the project root first, so today these agree.
    This module cannot enforce that, so it must not rely on it: resolving a
    relative frame against the process instead of against `project_root`
    silently returned nothing at all.
    """
    root = tmp_path / "proj"
    _write(str(root / "helpers" / "money.py"), "def to_cents(x):\n    return x\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    raw = "helpers/money.py:2: in to_cents\n"
    assert implicated_files(raw, "code", "tests", str(root)) == ["helpers/money.py"]


# --- why there are two of them ----------------------------------------------

@pytest.mark.parametrize("tb_mode", ["line", "short", "auto"])
def test_a_helper_that_raises_is_named_at_every_traceback_rung(tmp_path, tb_mode):
    root = tmp_path / "raises"
    _write(str(root / "util.py"), """
        def to_cents(amount):
            raise ValueError("bad amount")
    """)
    _write(str(root / "test_it.py"), """
        from util import to_cents


        def test_cents():
            assert to_cents(0.125) == 13
    """)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_it.py", "-q", "--tb=" + tb_mode,
         "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=str(root), capture_output=True, text=True)
    assert "util.py" in proc.stdout, proc.stdout
    # And the module reads it out of that real output, rather than this test
    # only confirming something about pytest. Without this line the test
    # would pass with `implicated_files` deleted, which an audit pointed out
    # on 2026-09-29.
    assert implicated_files(proc.stdout, str(root / "code"), str(root / "t"),
                            str(root)) == ["util.py"]


@pytest.mark.parametrize("tb_mode", ["line", "short", "auto"])
def test_a_helper_that_returns_the_wrong_value_is_named_at_none_of_them(tmp_path, tb_mode):
    """
    The reason `unwritable_imports` exists. This is the commoner failure and
    the one that produces a workaround, and no traceback rung mentions the
    file at all: the only frame is the assertion in the test.
    """
    root = tmp_path / "quiet"
    _write(str(root / "util.py"), """
        def to_cents(amount):
            return int(amount * 100)
    """)
    _write(str(root / "test_it.py"), """
        from util import to_cents


        def test_cents():
            assert to_cents(0.125) == 13
    """)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_it.py", "-q", "--tb=" + tb_mode,
         "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=str(root), capture_output=True, text=True)
    assert "1 failed" in proc.stdout, proc.stdout
    frames = [l for l in proc.stdout.splitlines() if "util.py:" in l]
    assert frames == [], proc.stdout
    # The module agrees with that, which is the half that matters: there is
    # nothing here for the dynamic signal to find, whatever it does.
    assert implicated_files(proc.stdout, str(root / "code"), str(root / "t"),
                            str(root)) == []


# --- the sentences -----------------------------------------------------------

def test_no_files_means_no_sentence():
    assert blocked_fault_message([], "outputs/agent_src/code/X") == ""
    assert unreachable_import_hint([], "outputs/agent_src/code/X") == ""
    assert workaround_warning([], "outputs/agent_src/code/X") == ""


def test_each_sentence_names_the_file_and_the_directory():
    for text in (
        blocked_fault_message(["helpers/money.py"], "outputs/agent_src/code/X"),
        unreachable_import_hint(["helpers/money.py"], "outputs/agent_src/code/X"),
        workaround_warning(["helpers/money.py"], "outputs/agent_src/code/X"),
    ):
        assert "helpers/money.py" in text
        assert "outputs/agent_src/code/X" in text


def test_the_warning_says_the_green_may_be_a_workaround():
    text = workaround_warning(["helpers/money.py"], "outputs/agent_src/code/X")
    assert "work around" in text
    assert "still" in text
