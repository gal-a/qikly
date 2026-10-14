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
# Probing an import by name cannot see two layouts an audit reproduced on
# 2026-10-08, and in both the tool printed a score that was invented rather
# than refusing. Every mutant ran against untouched code. What is pinned below
# is observation instead of a guess: the suite is run once with a marker in
# each scored file, and a file whose marker never fired was never executed by
# the suite. The second audit's cases, on 2026-10-10, follow at the end.


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


# ------------------------------------------------ the second audit, 10-10 ---

def _two_functions(root):
    """`f` is tested, `g` is not, and both have same-size mutants."""
    _write(os.path.join(root, "calc.py"),
           "def f(x):\n    if x == 3:\n        return 1\n    return 2\n\n\n"
           "def g(y):\n    if y == 5:\n        return 7\n    return 0\n")
    _write(os.path.join(root, "tests", "test_f.py"),
           "from calc import f\n\n\ndef test_f():\n"
           "    assert f(3) == 1\n    assert f(4) == 2\n")
    return mutation_score.from_paths(os.path.join(root, "calc.py"),
                                     os.path.join(root, "tests"))


def test_the_suite_runs_without_a_bytecode_cache(tmp_path):
    """
    Mutants such as `==` to `!=` leave a file the same size, and Python
    accepts a cached .pyc when size and whole-second mtime match. Two written
    within a second, and the second ran the first one's bytecode: four seeds
    gave four different "missed" sets, including faults the tests catch.
    """
    env = mutation_score._suite_env(str(tmp_path), _two_functions(str(tmp_path)))
    assert env.get("PYTHONDONTWRITEBYTECODE") == "1"


def test_only_untested_code_is_ever_reported_missed(tmp_path):
    """The behaviour the cache broke: every miss is in `g`, lines 7 to 10."""
    for seed in (0, 1):
        root = str(tmp_path / str(seed))
        result = mutation_score.score(_two_functions(root), mutants=8,
                                      seed=seed)
        lines = [int(m["change"].rsplit("line ", 1)[1])
                 for m in result["missed"]]
        assert all(line >= 7 for line in lines), result["missed"]


def test_a_failed_watching_run_does_not_print_an_invented_zero(tmp_path,
                                                               monkeypatch):
    """
    The guard used to read a failed watching run as "everything ran". A
    line-length test fails on any marker, and the namespace layout above
    came back as 0 of 3 with no refusal and no caveat.
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
    # Fails on the marker however short it is, as a snapshot test would.
    _write(os.path.join(tests, "test_snapshot.py"),
           "import glob, os\n\nHERE = os.path.dirname(__file__)\n\n\n"
           "def test_untouched():\n"
           "    for p in glob.glob(os.path.join(HERE, '..', 'src', '**', '*.py'),\n"
           "                       recursive=True):\n"
           "        assert 'qkhit' not in open(p, encoding='utf-8').read()\n")
    monkeypatch.setenv("PYTHONPATH", os.path.join(root, "src"))
    target = mutation_score.from_paths(
        os.path.join(root, "src", "acme", "widgets"), tests)
    with pytest.raises(ValueError) as caught:
        mutation_score.score(target, mutants=4, seed=1)
    assert "0 of" not in str(caught.value)


def test_an_unconfirmed_run_is_flagged_above_the_score():
    result = {"task": "t", "baseline": True, "caught": [{"file": "a.py",
              "family": "int", "change": "x"}], "missed": [], "unscorable": 0,
              "total": 1, "generated": False, "unreached": [],
              "unverified": True}
    text = mutation_score.render(result, [])
    assert text.index("Could not confirm") < text.index("planted faults missed")


def test_a_stray_init_in_a_flat_project_still_scores(tmp_path):
    """
    `myrepo/__init__.py`, empty, with a suite doing `from calc import ...`.
    Climbing out of the "package" widened the copy and made `calc`
    unimportable, so untouched code was reported as failing its own suite.
    """
    where = str(tmp_path / "myrepo")
    _write(os.path.join(where, "__init__.py"), "")
    _write(os.path.join(where, "calc.py"),
           "def rate(x):\n    return x if x <= 100 else 100\n")
    tests = os.path.join(where, "tests")
    _write(os.path.join(tests, "test_calc.py"),
           "from calc import rate\n\n\ndef test_caps():\n"
           "    assert rate(150) == 100\n")
    result = mutation_score.score(mutation_score.from_paths(where, tests),
                                  mutants=3, seed=1)
    assert result["baseline"] is True
    assert result["caught"]


def test_a_script_run_as_a_subprocess_counts_as_run(tmp_path):
    """
    A script ending in `sys.exit(main())` exits before an appended marker
    runs, so it was reported as never run while its faults were caught.
    """
    root = str(tmp_path)
    _write(os.path.join(root, "tool", "cli.py"),
           '"""A tiny command."""\nimport sys\n\n\ndef main():\n'
           '    print(int(sys.argv[1]) * 2)\n    return 0\n\n\n'
           'if __name__ == "__main__":\n    sys.exit(main())\n')
    _write(os.path.join(root, "tests", "test_cli.py"),
           "import os, subprocess, sys\n\nHERE = os.path.dirname(__file__)\n\n\n"
           "def test_doubles():\n"
           "    out = subprocess.run([sys.executable, os.path.join(\n"
           "        HERE, '..', 'tool', 'cli.py'), '21'],\n"
           "        capture_output=True, text=True).stdout\n"
           "    assert out.strip() == '42'\n")
    result = mutation_score.score(
        mutation_score.from_paths(os.path.join(root, "tool"),
                                  os.path.join(root, "tests")),
        mutants=4, seed=1)
    assert result["unreached"] == []
    assert result["caught"]


def test_the_marker_keeps_a_coding_line_and_a_future_import_first():
    source = ('# -*- coding: latin-1 -*-\n"""Doc."""\n'
              'from __future__ import annotations\nX = 1\n')
    assert mutation_score._marker_line(source) == 3


def test_the_same_directory_for_code_and_tests_says_so(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "test_calc.py"), "def test_x():\n    pass\n")
    with pytest.raises(ValueError) as caught:
        mutation_score.from_paths(root, root)
    assert "same directory" in str(caught.value)


@pytest.mark.skipif(os.path.normcase("A") == "A",
                    reason="only a case-insensitive filesystem can mismatch")
def test_the_tests_folder_is_excluded_whatever_its_case(tmp_path):
    root = str(tmp_path)
    _pkg(root, "pkg")
    _write(os.path.join(root, "pkg", "Tests", "test_calc.py"),
           "def test_x():\n    pass\n")
    # Lowercase on the command line, capitalised on disk.
    target = mutation_score.from_paths(
        os.path.join(root, "pkg"), os.path.join(root, "pkg", "tests"))
    scored = [os.path.basename(rel) for _, rel in target.files]
    assert "test_calc.py" not in scored


# ------------------------------------------------- the third pass, 10-10 ---

# The suite runs the code in a child with an environment of its own, so the
# child inherits neither PYTHONPATH nor PYTHONDONTWRITEBYTECODE.
_CHILD_TEST = (
    "import os, subprocess, sys\n\nHERE = os.path.dirname(__file__)\n"
    "ENV = {k: os.environ[k] for k in ('SYSTEMROOT', 'PATH') if k in os.environ}\n"
    "\n\ndef run(x):\n"
    "    code = ('import sys; sys.path.insert(0, sys.argv[1]); import calc; '\n"
    "            'print(calc.f(int(sys.argv[2])))')\n"
    "    return subprocess.run([sys.executable, '-c', code,\n"
    "                           os.path.join(HERE, '..'), str(x)],\n"
    "                          capture_output=True, text=True,\n"
    "                          env=ENV).stdout.strip()\n\n\n"
    "def test_f():\n    assert run(3) == '1'\n    assert run(4) == '2'\n")


def test_code_run_by_a_child_with_its_own_env_is_scored(tmp_path):
    """
    Two failures in one layout. The marker used to import a helper off
    PYTHONPATH, which the child never had, so this was refused as "never
    ran"; and the child wrote a bytecode cache that PYTHONDONTWRITEBYTECODE
    could not reach, so same-size mutants ran each other's bytecode.
    """
    for seed in (0, 1):
        root = str(tmp_path / str(seed))
        _write(os.path.join(root, "calc.py"),
               "def f(x):\n    if x == 3:\n        return 1\n    return 2\n\n\n"
               "def g(y):\n    if y == 5:\n        return 7\n    return 0\n")
        _write(os.path.join(root, "tests", "test_f.py"), _CHILD_TEST)
        result = mutation_score.score(
            mutation_score.from_paths(os.path.join(root, "calc.py"),
                                      os.path.join(root, "tests")),
            mutants=8, seed=seed)
        assert result["unreached"] == []
        lines = [int(m["change"].rsplit("line ", 1)[1])
                 for m in result["missed"]]
        assert all(line >= 7 for line in lines), result["missed"]


def test_a_file_saved_with_a_bom_is_watched(tmp_path):
    """ast.parse refused the U+FEFF, the marker went in front of it."""
    root = str(tmp_path)
    with open(os.path.join(root, "calc.py"), "w", encoding="utf-8-sig") as fh:
        fh.write("def cap(x):\n    return x if x <= 100 else 100\n")
    _write(os.path.join(root, "tests", "test_cap.py"),
           "from calc import cap\n\n\ndef test_cap():\n"
           "    assert cap(150) == 100\n")
    result = mutation_score.score(
        mutation_score.from_paths(os.path.join(root, "calc.py"),
                                  os.path.join(root, "tests")),
        mutants=2, seed=1)
    assert result["unverified"] is False


def test_the_marker_steps_over_a_statement_sharing_the_docstring_line():
    source = '"""D."""; X = (1,\n     2)\nY = 3\n'
    assert mutation_score._marker_line(source) == 2


def test_a_namespace_package_with_its_suite_inside_is_refused(tmp_path,
                                                             monkeypatch):
    """
    pytest's collection ran the copy's `widgets/__init__.py` and fired its
    marker, while the test imported `acme.widgets` from the original. Both
    earlier versions printed 0 of 3 for a suite that catches 2 of 3.
    """
    root = str(tmp_path)
    pkg = os.path.join(root, "src", "acme", "widgets")
    _write(os.path.join(pkg, "__init__.py"), "from .calc import rate\n")
    _write(os.path.join(pkg, "calc.py"),
           "def rate(x):\n    return x if x <= 100 else 100\n")
    _write(os.path.join(pkg, "tests", "__init__.py"), "")
    _write(os.path.join(pkg, "tests", "test_calc.py"),
           "from acme.widgets import rate\n\n\ndef test_caps():\n"
           "    assert rate(150) == 100\n    assert rate(5) == 5\n")
    monkeypatch.setenv("PYTHONPATH", os.path.join(root, "src"))
    with pytest.raises(ValueError) as caught:
        mutation_score.score(
            mutation_score.from_paths(pkg, os.path.join(pkg, "tests")),
            mutants=4, seed=1)
    assert "never ran" in str(caught.value)


def test_no_hit_file_is_left_behind(tmp_path):
    root = str(tmp_path)
    where = _pkg(root, "widget")
    mutation_score.score(
        mutation_score.from_paths(where, _suite(root, "widget")),
        mutants=1, seed=1)
    leftovers = [n for _, _, names in os.walk(root) for n in names
                 if n.endswith(mutation_score.HIT)]
    assert leftovers == []


def test_a_non_editable_install_of_the_package_is_caught(tmp_path,
                                                        monkeypatch):
    """
    `pip install .` copies the package to site-packages, so the file the
    suite loads is neither the workspace copy nor the user's own path. The
    release-gate audit found the invented 0 of 3 surviving exactly this.
    """
    import shutil
    root = str(tmp_path)
    pkg = os.path.join(root, "src", "acme", "widgets")
    _write(os.path.join(pkg, "__init__.py"), "from .calc import rate\n")
    _write(os.path.join(pkg, "calc.py"),
           "def rate(x):\n    return x if x <= 100 else 100\n")
    _write(os.path.join(pkg, "tests", "__init__.py"), "")
    _write(os.path.join(pkg, "tests", "test_calc.py"),
           "from acme.widgets import rate\n\n\ndef test_caps():\n"
           "    assert rate(150) == 100\n    assert rate(5) == 5\n")
    site = os.path.join(root, "site-packages")
    shutil.copytree(os.path.join(root, "src", "acme"), os.path.join(site, "acme"),
                    ignore=shutil.ignore_patterns("tests"))
    monkeypatch.setenv("PYTHONPATH", site)
    with pytest.raises(ValueError) as caught:
        mutation_score.score(
            mutation_score.from_paths(pkg, os.path.join(pkg, "tests")),
            mutants=4, seed=1)
    assert "never ran" in str(caught.value)


def test_every_bytecode_cache_is_gone_before_each_suite_run(tmp_path,
                                                            monkeypatch):
    """
    Checked directly rather than through a score, which depends on two
    mutants landing in one second and so only failed some of the time when
    the cleanup was removed.
    """
    ws = str(tmp_path)
    for where in ("__pycache__", os.path.join("pkg", "__pycache__"),
                  os.path.join("pkg", "deep", "__pycache__")):
        _write(os.path.join(ws, where, "calc.cpython-310.pyc"), "stale")
    _write(os.path.join(ws, "tests", "test_x.py"), "def test_x():\n    pass\n")
    seen = []

    def fake_run(*a, **k):
        seen.append([b for b, d, _ in os.walk(ws) if "__pycache__" in d])
        class Done(object):
            returncode = 0
        return Done()

    monkeypatch.setattr(mutation_score.subprocess, "run", fake_run)
    target = mutation_score.Target("t", [], ["tests"], ws)
    assert mutation_score._suite_verdict(ws, target) == "pass"
    assert seen == [[]], "a cache survived into the suite run: %s" % seen
