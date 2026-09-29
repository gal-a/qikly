"""
Everything downstream of a package-seeded implementation.

The first matrix, `test_multi_module_seed.py`, asks whether a package installs
and imports. This one asks the question that actually caused a defect: a
package puts `.py` files one level deeper than anything in this project had
ever seen, and **every consumer of the task's code directory is a place that
could still be assuming they sit directly in it**.

One such place was found by audit rather than by test: `mutation_score` listed
one directory level, so a package-seeded implementation scored nothing at all
and reported it the same way it reports a trivial module. This file exists so
the next one is found here instead.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from qikly.agent_api.code_loader.code_loader import load_codebase, load_target_files
from qikly.agent_tools.apply_patch import apply_patch
from qikly.orchestrator import orchestrator as orch


TASK = "T"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    """A task whose implementation is a package two levels deep."""
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "mypkg" / "__init__.py"), "")
    _write(str(code / "mypkg" / "pricing.py"), """
        from mypkg.utils.rounding import half_up


        def total(x):
            return half_up(x)
    """)
    _write(str(code / "mypkg" / "utils" / "rounding.py"), """
        def half_up(x):
            return round(x, 2)
    """)
    monkeypatch.chdir(str(root))
    return {"root": str(root), "code": str(code)}


# --- consumers of the code directory ----------------------------------------

def test_the_agent_is_shown_every_module_however_deep(packaged):
    text = load_codebase(packaged["code"])
    assert "def total" in text
    assert "def half_up" in text


def test_a_patch_can_be_scoped_to_a_file_inside_a_subpackage(packaged):
    """
    `load_target_files` takes the paths a FIX named. A nested one has to
    resolve, or the PATCH prompt silently arrives with no code in it and the
    model invents a file it has never seen.
    """
    target = "outputs/agent_src/code/%s/mypkg/utils/rounding.py" % TASK
    text = load_target_files(packaged["code"], [target])
    assert "def half_up" in text
    assert "def total" not in text, "scoping should exclude the other module"


def test_a_patch_still_cannot_escape_through_a_subpackage(packaged):
    """The traversal guard has to survive the extra directory level."""
    text = load_target_files(
        packaged["code"], ["outputs/agent_src/code/%s/mypkg/../../../../secret.py" % TASK])
    assert text.strip() == "" or "secret" not in text


def test_a_repair_lands_in_a_nested_helper(packaged):
    """The half of multi-module repair that has to work end to end."""
    diff = _write(os.path.join(packaged["root"], "fix.diff"), """
        --- a/outputs/agent_src/code/T/mypkg/utils/rounding.py
        +++ b/outputs/agent_src/code/T/mypkg/utils/rounding.py
        @@ -1,2 +1,2 @@
         def half_up(x):
        -    return round(x, 2)
        +    return round(x, 3)
    """)
    apply_patch(diff)
    landed = open(os.path.join(packaged["code"], "mypkg", "utils", "rounding.py"),
                  encoding="utf-8").read()
    assert "round(x, 3)" in landed


def test_the_workspace_reset_clears_a_package_wholesale(packaged):
    """A leftover module from a previous run must not survive into the next."""
    assert orch.agent_src_has_code(packaged["code"])
    orch.backup_and_clear_agent_src("20260929_120000", packaged["code"])
    assert not orch.agent_src_has_code(packaged["code"])
    assert not os.path.exists(os.path.join(packaged["code"], "mypkg"))


def test_an_empty_package_directory_does_not_count_as_code(tmp_path, monkeypatch):
    """
    `agent_src_has_code` decides whether the bootstrap attempt runs. A folder
    with no Python in it is not an implementation.
    """
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    os.makedirs(str(code / "mypkg"))
    monkeypatch.chdir(str(root))
    assert not orch.agent_src_has_code(str(code))


# --- what install_seed carries, and what it leaves behind -------------------

def test_a_package_keeps_its_data_files_and_drops_its_caches(tmp_path):
    """
    A real package has more in it than modules. Data travels, because the
    code may open it; compiled caches do not, because they are stale copies
    of the very files about to be rewritten.
    """
    src = tmp_path / "mypkg"
    _write(str(src / "pricing.py"), "X = 1\n")
    _write(str(src / "rates.csv"), "a,b\n1,2\n")
    _write(str(src / "__pycache__" / "pricing.cpython-310.pyc"), "junk")
    _write(str(src / "stale.pyc"), "junk")
    dest = tmp_path / "code" / TASK
    orch.install_seed(str(src), str(dest), keep_directory_name=True)

    assert os.path.isfile(str(dest / "mypkg" / "rates.csv"))
    assert not os.path.exists(str(dest / "mypkg" / "__pycache__"))
    assert not os.path.exists(str(dest / "mypkg" / "stale.pyc"))


def test_a_package_three_levels_deep_arrives_intact(tmp_path):
    src = tmp_path / "mypkg"
    _write(str(src / "a" / "b" / "c" / "deep.py"), "X = 1\n")
    dest = tmp_path / "code" / TASK
    orch.install_seed(str(src), str(dest), keep_directory_name=True)
    assert os.path.isfile(str(dest / "mypkg" / "a" / "b" / "c" / "deep.py"))


def test_two_tasks_seeded_from_the_same_package_do_not_share_a_directory(tmp_path):
    """Each task owns its own copy, so one run's repair cannot reach another."""
    src = tmp_path / "mypkg"
    _write(str(src / "pricing.py"), "X = 1\n")
    first = tmp_path / "code" / "TASK_A"
    second = tmp_path / "code" / "TASK_B"
    orch.install_seed(str(src), str(first), keep_directory_name=True)
    orch.install_seed(str(src), str(second), keep_directory_name=True)

    with open(str(first / "mypkg" / "pricing.py"), "w", encoding="utf-8") as handle:
        handle.write("X = 99\n")
    assert "X = 1" in open(str(second / "mypkg" / "pricing.py"), encoding="utf-8").read()


# --- the import root, which is the part that can reach outside the run ------

def test_no_import_root_means_the_environment_is_untouched(tmp_path):
    """
    The backward-compatibility guarantee, checked by running a subprocess and
    asking it what it sees rather than by reading the code that builds it.
    """
    probe = _write(str(tmp_path / "test_probe.py"), """
        import os


        def test_probe():
            print("PYTHONPATH=[%s]" % os.environ.get("PYTHONPATH", ""))
    """)
    before = os.environ.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", probe, "-q", "-s", "-p", "no:cacheprovider",
         "-o", "addopts="], capture_output=True, text=True, cwd=str(tmp_path))
    assert "PYTHONPATH=[%s]" % before in result.stdout, result.stdout


def test_an_import_root_is_prepended_and_keeps_what_was_there(monkeypatch, tmp_path):
    """
    Prepended, so the package wins over a same-named one already on the path,
    and appended-to rather than replacing, so a user's own PYTHONPATH is not
    silently dropped for the run.
    """
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "theirs"))
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        raise KeyboardInterrupt  # stop before pytest is really launched

    monkeypatch.setattr("qikly.agent_tools.run_tests.subprocess.run", fake_run)
    from qikly.agent_tools.run_tests import run_tests
    with pytest.raises(KeyboardInterrupt):
        run_tests("integration", str(tmp_path), import_roots=[str(tmp_path / "code")])

    path = captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert path[0] == os.path.abspath(str(tmp_path / "code"))
    assert str(tmp_path / "theirs") in path


def test_an_import_root_on_an_empty_pythonpath_leaves_no_blank_entry(monkeypatch, tmp_path):
    """A trailing separator puts the working directory on the path by accident."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        raise KeyboardInterrupt

    monkeypatch.setattr("qikly.agent_tools.run_tests.subprocess.run", fake_run)
    from qikly.agent_tools.run_tests import run_tests
    with pytest.raises(KeyboardInterrupt):
        run_tests("integration", str(tmp_path), import_roots=[str(tmp_path / "code")])

    assert captured["env"]["PYTHONPATH"] == os.path.abspath(str(tmp_path / "code"))


def test_a_package_named_like_a_standard_library_module_is_refused(tmp_path):
    """
    The one real hazard of putting a directory on the path. A package called
    `json` would shadow the standard library for the whole test subprocess,
    and the failures that follow look like anything except their cause.
    """
    src = tmp_path / "json"
    _write(str(src / "pricing.py"), "X = 1\n")
    dest = tmp_path / "code" / TASK
    with pytest.raises(ValueError) as raised:
        orch.install_seed(str(src), str(dest), keep_directory_name=True)
    assert "json" in str(raised.value)
