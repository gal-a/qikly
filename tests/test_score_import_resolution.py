# -*- coding: utf-8 -*-
"""
Scoring must refuse when the suite imports a copy it is not mutating.

Found on 2026-10-07 scoring a src/ layout project with an editable install.
The workspace copy sat at `ws/src/<pkg>`, pytest ran with `cwd=ws` so only
`ws` was on sys.path, and the import fell through to the original source.
All 36 mutants ran against untouched code and the tool reported 0%.

A src/ layout is the modern packaging default, so the failure was both likely
and maximally alarming: the user is told their suite catches nothing. These
tests pin the guard that turns it into an error.
"""
import os

import pytest

from qikly import mutation_score


def _pkg(root, name, under=None):
    """A package with one module, optionally nested under a directory."""
    parent = os.path.join(root, under) if under else root
    where = os.path.join(parent, name)
    os.makedirs(where, exist_ok=True)
    with open(os.path.join(where, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write("from .calc import rate\n")
    with open(os.path.join(where, "calc.py"), "w", encoding="utf-8") as fh:
        fh.write("def rate(x):\n    return x if x <= 100 else 100\n")
    return where


def _suite(root, name):
    tests = os.path.join(root, "tests")
    os.makedirs(tests, exist_ok=True)
    with open(os.path.join(tests, "test_calc.py"), "w", encoding="utf-8") as fh:
        fh.write("from %s import rate\n\n\n"
                 "def test_caps():\n    assert rate(150) == 100\n" % name)
    return tests


def test_import_roots_sees_through_a_src_layout(tmp_path):
    """
    The climb has to stop at the package, not at the repository root.

    `src/pkg/calc.py` is imported as `pkg` from `src`, and getting this wrong
    in either direction makes the guard either useless or permanently angry.
    """
    root = str(tmp_path)
    _pkg(root, "widget", under="src")
    target = mutation_score.from_paths(os.path.join(root, "src", "widget"),
                                       _suite(root, "widget"))
    roots = mutation_score._import_roots(target)
    assert ("widget", "src") in roots, roots


def test_import_roots_handles_a_flat_layout(tmp_path):
    """A flat package imports from the workspace root, so the parent is empty."""
    root = str(tmp_path)
    _pkg(root, "widget")
    target = mutation_score.from_paths(os.path.join(root, "widget"),
                                       _suite(root, "widget"))
    assert ("widget", "") in mutation_score._import_roots(target)


def test_a_flat_layout_scores_rather_than_refusing(tmp_path):
    """
    The guard must not fire on the case that already worked.

    A false positive here would stop every correct score, which is worse than
    the bug it was added for.
    """
    root = str(tmp_path)
    _pkg(root, "widget")
    result = mutation_score.score(
        mutation_score.from_paths(os.path.join(root, "widget"),
                                  _suite(root, "widget")),
        mutants=2, seed=1)
    assert result is not None
    assert result["baseline"] is True


def test_a_src_layout_scores_instead_of_being_refused(tmp_path, monkeypatch):
    """
    The fix, stated as behaviour: a src/ layout gets a real score.

    pytest runs with cwd=workspace, so `ws/src/pkg` is invisible under its own
    name and the import used to fall through to whatever was installed. The
    runner now puts the workspace's own source roots on PYTHONPATH, which is
    all a flat layout ever got for free.

    An importable copy is planted outside the workspace first, because without
    one the suite would simply fail to import and the test would pass for the
    wrong reason.
    """
    root = str(tmp_path)
    _pkg(root, "widget", under="src")
    target = mutation_score.from_paths(os.path.join(root, "src", "widget"),
                                       _suite(root, "widget"))
    monkeypatch.setenv("PYTHONPATH", os.path.join(root, "src"))

    result = mutation_score.score(target, mutants=2, seed=1)

    assert result is not None, "a src/ layout must be scoreable"
    assert result["baseline"] is True
    # The mutants ran against the workspace copy, so the suite had a chance to
    # notice them. Scoring nothing at all is the symptom this fix removes.
    # Deliberately not "caught or missed or unscorable": that passes
    # even with the fix removed, because the broken case still reports
    # every mutant as missed. A fault the suite can see must be caught.
    assert result["caught"], "a fault the suite can see must be caught"


def test_a_non_package_directory_is_not_put_ahead_of_the_stdlib(tmp_path):
    """
    The regression the first version of this fix introduced.

    A flat project with a non-package `utils/` holding both calc.py and a
    module named like a standard library one scored correctly before the fix.
    Prepending every source root put that directory ahead of the standard
    library for the whole pytest process, so pytest itself died importing
    `logging` and the baseline came back red. Breaking a layout that already
    worked is worse than the src/ case the fix exists for, so only roots the
    suite cannot already reach may be prepended.
    """
    root = str(tmp_path)
    utils = os.path.join(root, "utils")
    os.makedirs(utils, exist_ok=True)
    with open(os.path.join(utils, "calc.py"), "w", encoding="utf-8") as fh:
        fh.write("def cap(x):" + chr(10) +
                 "    return x if x <= 100 else 100" + chr(10))
    # The trap: a module whose name the standard library also uses.
    with open(os.path.join(utils, "logging.py"), "w", encoding="utf-8") as fh:
        fh.write("LEVEL = 1" + chr(10))
    tests = os.path.join(root, "tests")
    os.makedirs(tests, exist_ok=True)
    with open(os.path.join(tests, "test_cap.py"), "w", encoding="utf-8") as fh:
        fh.write("from calc import cap" + chr(10) * 3 +
                 "def test_cap():" + chr(10) +
                 "    assert cap(150) == 100" + chr(10))

    target = mutation_score.from_paths(utils, tests)
    ws = str(tmp_path / "ws")
    os.makedirs(ws, exist_ok=True)
    env = mutation_score._suite_env(ws, target)
    added = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    assert not any(p.endswith("utils") for p in added), (
        "a non-package directory holding a standard library name was put "
        "ahead of the standard library: %s" % added)


# ------------------------------------------- what the suite actually ran ---
#
# The checks above probe an import by name. That cannot see two layouts an
# audit reproduced on 2026-10-08, and in both the tool printed a score that
# was invented rather than refusing. Every mutant ran against untouched code.
# What is pinned below is the observation that replaced the guess: the suite
# is run once with a marker in each scored file, and a file whose marker never
# fired was never executed by the suite.


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_a_namespace_package_on_an_installed_copy_is_refused(tmp_path,
                                                             monkeypatch):
    """
    `src/acme/widgets/calc.py` with no `__init__.py` in `acme`.

    The name climb stops at `widgets`, the probe `import widgets` lands in the
    workspace, and the guard passed. The suite imports `acme.widgets`, which
    came from the original. Before the fix: caught 0, missed 4, no refusal.
    """
    root = str(tmp_path)
    _write(os.path.join(root, "src", "acme", "widgets", "__init__.py"),
           "from .calc import rate\n")
    _write(os.path.join(root, "src", "acme", "widgets", "calc.py"),
           "def rate(x):\n    return x if x <= 100 else 100\n")
    tests = os.path.join(root, "tests")
    _write(os.path.join(tests, "test_calc.py"),
           "from acme.widgets import rate\n\n\n"
           "def test_caps():\n    assert rate(150) == 100\n")
    monkeypatch.setenv("PYTHONPATH", os.path.join(root, "src"))
    target = mutation_score.from_paths(
        os.path.join(root, "src", "acme", "widgets"), tests)

    with pytest.raises(ValueError) as caught:
        mutation_score.score(target, mutants=4, seed=1)
    message = str(caught.value)
    assert "never ran" in message
    # The workspace copy is already first on the path by then, so advice to
    # set PYTHONPATH would send the reader in a circle.
    assert "PYTHONPATH" not in message
    assert "0 of" not in message, "never phrase a refusal as a score"


def test_a_suite_inside_the_package_is_scored_against_the_copy(tmp_path,
                                                               monkeypatch):
    """
    `--score-code src/widget --score-tests src/widget/tests`.

    The directory holding both was the package itself, so the workspace had no
    `widget` in it and the suite imported the original. The test file was also
    mutated, and its mutants were counted as caught. Before the fix the tool
    printed 4 of 6 caught, and every number in that was bogus.
    """
    root = str(tmp_path)
    where = _pkg(root, "widget", under="src")
    tests = os.path.join(where, "tests")
    _write(os.path.join(tests, "__init__.py"), "")
    _write(os.path.join(tests, "test_calc.py"),
           "from widget.calc import rate\n\n\n"
           "def test_caps():\n    assert rate(150) == 100\n")
    monkeypatch.setenv("PYTHONPATH", os.path.join(root, "src"))
    target = mutation_score.from_paths(where, tests)

    scored = [rel.replace(os.sep, "/") for _, rel in target.files]
    assert not any("/tests/" in "/" + rel for rel in scored), (
        "the suite's own files were planted with faults: %s" % scored)

    result = mutation_score.score(target, mutants=6, seed=1)
    assert result["baseline"] is True
    assert result["caught"], "a fault the suite can see must be caught"


def test_a_file_the_suite_never_runs_is_named(tmp_path):
    """
    Some files go untested, and their misses mean something different.

    A fault in a module the suite never imports cannot be caught by any
    assertion, so those misses are kept in the score, which stays a floor,
    and the file is named so the reader knows why.
    """
    root = str(tmp_path)
    where = _pkg(root, "widget")
    _write(os.path.join(where, "unused.py"),
           "def spare(x):\n    return x + 1\n")
    result = mutation_score.score(
        mutation_score.from_paths(where, _suite(root, "widget")),
        mutants=20, seed=1)
    assert result["baseline"] is True
    assert [os.path.basename(p) for p in result["unreached"]] == ["unused.py"]
    assert "unused.py" in mutation_score.render(result, [])
