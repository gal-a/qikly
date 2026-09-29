"""
Making the task's own copy of a package win over the user's original.

`python -m pytest` puts the working directory at the front of `sys.path`, and
the working directory is the project root where the user's own code lives. So
a package-seeded task imported the user's `mypkg/` instead of the copy in
`outputs/agent_src/code/<task_id>/`. The suite tested code the run could not
change, the agent repaired a copy nobody imported, and every patch applied
cleanly while no test outcome ever moved. Found by running a real pandas task
on 2026-09-29, after three audits and nine offline test files had missed it.

**The first three tests are the regression guard.** A flat, single-file task
must take none of this: no plugin on the command line, no environment
variable, no `env` argument at all. If those fail, the mechanism has grown a
reach beyond the case it was built for.
"""
import os
import subprocess
import sys

import pytest

from qikly._pytest_import_roots import ENV_VAR, _install


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _captured_invocation(monkeypatch, tmp_path, **kwargs):
    """The command and environment run_tests would have used."""
    seen = {}

    def fake_run(cmd, **called):
        seen["cmd"] = cmd
        seen["env"] = called.get("env")
        raise KeyboardInterrupt

    monkeypatch.setattr("qikly.agent_tools.run_tests.subprocess.run", fake_run)
    from qikly.agent_tools.run_tests import run_tests
    with pytest.raises(KeyboardInterrupt):
        run_tests("integration", str(tmp_path), **kwargs)
    return seen


# --- the regression guard ----------------------------------------------------

def test_a_flat_task_gets_no_plugin_and_no_environment(monkeypatch, tmp_path):
    seen = _captured_invocation(monkeypatch, tmp_path)
    assert seen["env"] is None
    assert "qikly._pytest_import_roots" not in seen["cmd"]


def test_an_empty_root_list_is_the_same_as_none(monkeypatch, tmp_path):
    seen = _captured_invocation(monkeypatch, tmp_path, import_roots=[])
    assert seen["env"] is None
    assert "qikly._pytest_import_roots" not in seen["cmd"]


def test_the_plugin_does_nothing_without_its_variable(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    before = list(sys.path)
    assert _install(os.environ.get(ENV_VAR)) == []
    assert sys.path == before


def test_importing_the_plugin_module_changes_nothing(monkeypatch):
    """
    Found by audit 2026-09-29. This module used to call `_install` at import
    time, and `run_tests` imported it to read its name, and the orchestrator
    imports `run_tests`, so every qikly command imported it. An ambient
    `QIKLY_IMPORT_ROOTS`, which the fixtures in this very file export, then
    reordered `sys.path` in the CLI's own process on `--version`.
    """
    import importlib

    monkeypatch.setenv(ENV_VAR, os.path.abspath("should-not-be-installed"))
    before = list(sys.path)
    importlib.reload(importlib.import_module("qikly._pytest_import_roots"))
    assert sys.path == before, "importing the plugin must have no side effect"


def test_run_tests_names_the_plugin_without_importing_it():
    """
    The two strings are literals in `run_tests`, so nothing about a normal
    qikly process pulls the plugin in. Pinned here so a rename cannot quietly
    break the link that is no longer an import.
    """
    from qikly.agent_tools import run_tests as rt
    from qikly import _pytest_import_roots as plugin

    assert rt.IMPORT_ROOTS_PLUGIN == plugin.__name__
    assert rt.IMPORT_ROOTS_ENV == plugin.ENV_VAR
    assert not hasattr(rt, "import_roots_plugin"), (
        "run_tests must name the plugin, not import it")


def test_the_plugin_exposes_pytest_s_own_hook():
    """It is a hook that installs the roots, which is why an import cannot."""
    from qikly import _pytest_import_roots as plugin

    assert callable(plugin.pytest_configure)


# --- what it does when it is on ----------------------------------------------

def test_a_package_task_names_the_plugin_and_sets_the_variable(monkeypatch, tmp_path):
    code = str(tmp_path / "code")
    seen = _captured_invocation(monkeypatch, tmp_path, import_roots=[code])
    assert "-p" in seen["cmd"]
    assert "qikly._pytest_import_roots" in seen["cmd"]
    assert seen["env"][ENV_VAR] == os.path.abspath(code)
    # PYTHONPATH is still set, as a second line of defence if the plugin
    # cannot be imported for any reason.
    assert os.path.abspath(code) in seen["env"]["PYTHONPATH"]


def test_roots_go_in_front_in_the_order_given(monkeypatch):
    before = list(sys.path)
    try:
        _install(os.pathsep.join(["first", "second"]))
        assert sys.path[0] == os.path.abspath("first")
        assert sys.path[1] == os.path.abspath("second")
    finally:
        sys.path[:] = before


def test_installing_twice_does_not_grow_sys_path(monkeypatch):
    """A run makes many pytest calls; sys.path must not accumulate."""
    before = list(sys.path)
    try:
        _install("once")
        _install("once")
        assert sys.path.count(os.path.abspath("once")) == 1
    finally:
        sys.path[:] = before


# --- the behaviour that matters, in a real subprocess ------------------------

@pytest.fixture
def shadowed(tmp_path):
    """A user's own package at the project root, and the run's copy of it."""
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / "T"
    _write(str(root / "mypkg" / "__init__.py"), 'ORIGIN = "theirs"\n')
    _write(str(code / "mypkg" / "__init__.py"), 'ORIGIN = "the run"\n')
    _write(str(root / "outputs" / "tests" / "T" / "integration" / "test_which.py"),
           "from mypkg import ORIGIN\n\n\n"
           "def test_which():\n"
           "    assert ORIGIN == 'the run', ORIGIN\n")
    return {"root": str(root), "code": str(code)}


def _run_pytest(shadowed, with_plugin):
    env = dict(os.environ)
    src = os.path.dirname(os.path.dirname(os.path.abspath(
        __import__("qikly").__file__)))
    parts = [shadowed["code"], src]
    env["PYTHONPATH"] = os.pathsep.join(parts + [env.get("PYTHONPATH", "")])
    cmd = [sys.executable, "-m", "pytest", "outputs/tests/T/integration", "-q",
           "--tb=line", "-p", "no:cacheprovider", "-o", "addopts="]
    if with_plugin:
        env[ENV_VAR] = shadowed["code"]
        cmd += ["-p", "qikly._pytest_import_roots"]
    else:
        env.pop(ENV_VAR, None)
    return subprocess.run(cmd, cwd=shadowed["root"], env=env,
                          capture_output=True, text=True)


def test_without_the_plugin_the_users_copy_wins(shadowed):
    """
    The defect, pinned. If this ever passes, `python -m pytest` has stopped
    putting the working directory first and the plugin is no longer needed.
    """
    assert "1 failed" in _run_pytest(shadowed, with_plugin=False).stdout


def test_with_the_plugin_the_runs_copy_wins(shadowed):
    """The fix, in the arrangement that actually occurs."""
    result = _run_pytest(shadowed, with_plugin=True)
    assert "1 passed" in result.stdout, result.stdout
