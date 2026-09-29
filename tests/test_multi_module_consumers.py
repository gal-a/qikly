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


@pytest.mark.parametrize("seed_path", [
    "outputs/agent_src",          # an ancestor whose basename is ordinary
    "outputs",
    "outputs/agent_src/code",
])
def test_a_seed_containing_the_install_directory_is_refused(tmp_path, monkeypatch, seed_path):
    """
    Found by audit 2026-09-29, and it defeated the first guard entirely.

    That guard rejected a basename of `..`. Pointing the seed at
    `outputs/agent_src` passes that check, since its basename is a perfectly
    ordinary word, and then reproduces the whole defect: the destination lies
    inside the source, so the walk copies what it has just written, pulling
    another task's implementation into the nest on the way. The question is
    the relationship between the two paths, not the spelling of one.
    """
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    os.makedirs(str(code))
    _write(str(root / "outputs" / "agent_src" / "code" / "OTHER" / "theirs.py"), "X = 1\n")
    monkeypatch.chdir(str(root))

    with pytest.raises(ValueError) as raised:
        orch.install_seed(seed_path, str(code), keep_directory_name=True)
    assert "seed.implementation" in str(raised.value)
    assert os.listdir(str(code)) == [], "nothing may be written before the refusal"
    assert os.path.isfile(str(root / "outputs" / "agent_src" / "code" / "OTHER" / "theirs.py"))


def test_a_stray_python_file_in_a_cache_directory_is_not_scored(tmp_path):
    """
    Found by the same audit. `sorted(os.walk(...))` drains the generator
    before the body runs, so the `dirs[:]` pruning that excludes
    `__pycache__` had already been bypassed and was doing nothing.
    """
    from qikly import mutation_score

    root = tmp_path / "code"
    _write(str(root / TASK / "calc.py"), "def f():\n    return 1\n")
    _write(str(root / TASK / "__pycache__" / "stray.py"), "def g():\n    return 2\n")

    found = mutation_score.implementation(TASK, root=str(root))
    assert [os.path.basename(real) for real, _rel in found] == ["calc.py"]


def test_the_scored_file_order_is_stable(tmp_path):
    """The fault sample is seeded, so an unstable order breaks --score-seed."""
    from qikly import mutation_score

    root = tmp_path / "code"
    for name in ("z.py", "a.py", "m.py"):
        _write(str(root / TASK / "pkg" / name), "X = 1\n")
    _write(str(root / TASK / "top.py"), "X = 1\n")

    first = mutation_score.implementation(TASK, root=str(root))
    assert first == mutation_score.implementation(TASK, root=str(root))
    assert [os.path.basename(r) for r, _ in first] == ["top.py", "a.py", "m.py", "z.py"]


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

@pytest.mark.parametrize("roots", [None, [], ()])
def test_no_import_root_means_the_environment_is_untouched(monkeypatch, tmp_path, roots):
    """
    The backward-compatibility guarantee: a file seed and an unseeded run must
    get the environment they always got.

    Rewritten after an audit on 2026-09-29 found the first version vacuous. It
    ran a bare pytest subprocess of its own and asserted that the subprocess
    inherited this process's PYTHONPATH, which is unconditionally true and
    never touched `run_tests` at all. It would have passed with the guarantee
    deleted. `env is None` is the whole claim, so that is what to assert.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env", "absent")
        raise KeyboardInterrupt  # stop before pytest is really launched

    monkeypatch.setattr("qikly.agent_tools.run_tests.subprocess.run", fake_run)
    from qikly.agent_tools.run_tests import run_tests
    with pytest.raises(KeyboardInterrupt):
        run_tests("integration", str(tmp_path), import_roots=roots)

    assert captured["env"] is None, (
        "no import root must mean no env argument, so the subprocess inherits "
        "os.environ exactly as it did before package seeds existed")


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


# --- the header the agent copies into its diff ------------------------------

def test_every_file_header_uses_forward_slashes(packaged):
    r"""
    Found by running a real pandas package through a task on 2026-09-29.

    `os.path.join` on Windows produced a header mixing both separators,
    `outputs/agent_src/code/T\mypkg\pricing.py`, because the left half is a
    literal and the right half is joined. The agent copies that header into
    the `---` and `+++` lines of its diff, and it transcribed the mixed form
    wrong every time: every patch in the run named a path with the task id
    missing, so not one applied, the failure never changed, and the stage
    burned its whole attempt budget. A flat layout hid it by leaving only one
    separator to get wrong.
    """
    text = load_codebase(packaged["code"])
    headers = [l for l in text.split("\n") if l.startswith("# FILE:")]
    assert headers, "no files were loaded, so this test proves nothing"
    assert any("mypkg/utils/rounding.py" in h for h in headers), headers
    for header in headers:
        assert "\\" not in header, (
            "a diff header is forward-slash by convention and a mixed one is "
            "transcribed wrong: %s" % header)


def test_a_scoped_target_header_uses_forward_slashes_too(packaged):
    """The same header, on the path PATCH generation actually reads."""
    target = "outputs/agent_src/code/%s/mypkg/utils/rounding.py" % TASK
    text = load_target_files(packaged["code"], [target])
    headers = [l for l in text.split("\n") if l.startswith("# FILE:")]
    assert headers, "nothing was loaded, so this test proves nothing"
    for header in headers:
        assert "\\" not in header, header
