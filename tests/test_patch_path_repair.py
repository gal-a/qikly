"""
Resolving a diff that names a file which is not there.

Small models drop a directory from a path they were asked to copy. With a
package-seeded implementation there is one more directory to drop, and on a
real pandas task **ten of ten patches were rejected** with `can't find file to
patch`: every one named `outputs/agent_src/code/salespkg/etl.py`, with the
task's own directory missing. The failure never changed and the stage spent
its whole attempt budget on it.

**The first two tests are the point of this file.** The repair is reachable
only from the state where the patch was going to be discarded anyway, so the
single-file case that has worked all along cannot be touched by it. If those
two ever fail, the repair has grown a reach it was not meant to have.
"""
import os
import textwrap

import pytest

from qikly.agent_tools.apply_patch import (
    _existing_files,
    _repair_destination,
    apply_patch,
)


TASK = "T"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "salespkg" / "etl.py"), "VALUE = 1\n")
    _write(str(code / "salespkg" / "utils" / "money.py"), "VALUE = 2\n")
    # A second task, which nothing here may ever reach.
    _write(str(root / "outputs" / "agent_src" / "code" / "OTHER" / "theirs.py"), "VALUE = 3\n")
    monkeypatch.chdir(str(root))
    return {"root": str(root), "code": str(code)}


def _diff(project, named, old="VALUE = 1", new="VALUE = 11"):
    return _write(os.path.join(project["root"], "p.diff"), """
        --- a/%s
        +++ b/%s
        @@ -1 +1 @@
        -%s
        +%s
    """ % (named, named, old, new))


# --- the no-regression guarantee, which is why the repair is shaped this way -

def test_a_diff_whose_paths_all_resolve_is_untouched(project):
    """
    The single-file case, and every correct diff. No `.resolved` copy is
    written, because the repair is never entered: it is gated on a path that
    does not exist, and here they all do.
    """
    named = "outputs/agent_src/code/%s/salespkg/etl.py" % TASK
    diff = _diff(project, named)
    apply_patch(diff, code_dir=project["code"])

    assert "VALUE = 11" in open(os.path.join(project["code"], "salespkg", "etl.py"),
                                encoding="utf-8").read()
    assert not os.path.exists(diff + ".resolved"), (
        "a diff that resolved on its own must not go near the repair path")


def test_without_a_code_dir_nothing_is_repaired(project):
    """
    The old signature, and any caller that has not opted in, behaves exactly
    as it did: a diff naming a missing file fails.
    """
    diff = _diff(project, "outputs/agent_src/code/salespkg/etl.py")
    with pytest.raises(RuntimeError):
        apply_patch(diff)
    assert not os.path.exists(diff + ".resolved")


# --- what the repair is for --------------------------------------------------

def test_a_dropped_task_directory_is_resolved(project):
    """The exact shape observed on the pandas run, ten times out of ten."""
    diff = _diff(project, "outputs/agent_src/code/salespkg/etl.py")
    apply_patch(diff, code_dir=project["code"])
    assert "VALUE = 11" in open(os.path.join(project["code"], "salespkg", "etl.py"),
                                encoding="utf-8").read()


def test_a_bare_package_relative_path_is_resolved(project):
    diff = _diff(project, "salespkg/etl.py")
    apply_patch(diff, code_dir=project["code"])
    assert "VALUE = 11" in open(os.path.join(project["code"], "salespkg", "etl.py"),
                                encoding="utf-8").read()


def test_a_nested_helper_is_resolved(project):
    diff = _diff(project, "salespkg/utils/money.py", old="VALUE = 2", new="VALUE = 22")
    apply_patch(diff, code_dir=project["code"])
    assert "VALUE = 22" in open(
        os.path.join(project["code"], "salespkg", "utils", "money.py"),
        encoding="utf-8").read()


def test_the_diff_the_model_wrote_stays_on_disk(project):
    """A run's record shows what was generated, not what was salvaged."""
    diff = _diff(project, "salespkg/etl.py")
    before = open(diff, encoding="utf-8").read()
    apply_patch(diff, code_dir=project["code"])
    assert open(diff, encoding="utf-8").read() == before


# --- what it refuses to do ---------------------------------------------------

def test_an_ambiguous_name_is_refused_rather_than_guessed(tmp_path, monkeypatch):
    """Two files called money.py, so there is no answer and none is invented."""
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "a" / "money.py"), "VALUE = 1\n")
    _write(str(code / "b" / "money.py"), "VALUE = 1\n")
    monkeypatch.chdir(str(root))

    assert _repair_destination("money.py", _existing_files(str(code))) is None
    diff = _write(str(root / "p.diff"), """
        --- a/money.py
        +++ b/money.py
        @@ -1 +1 @@
        -VALUE = 1
        +VALUE = 11
    """)
    with pytest.raises(RuntimeError):
        apply_patch(diff, code_dir=str(code))


def test_a_name_matching_nothing_is_refused(project):
    diff = _diff(project, "salespkg/invented.py")
    with pytest.raises(RuntimeError):
        apply_patch(diff, code_dir=project["code"])


def test_the_repair_cannot_reach_another_task(project):
    """It searches `code_dir` and only `code_dir`."""
    existing = _existing_files(project["code"])
    assert all("OTHER" not in f for f in existing)
    assert _repair_destination("theirs.py", existing) is None

    diff = _diff(project, "theirs.py", old="VALUE = 3", new="VALUE = 33")
    with pytest.raises(RuntimeError):
        apply_patch(diff, code_dir=project["code"])
    assert "VALUE = 3\n" == open(
        os.path.join(project["root"], "outputs", "agent_src", "code", "OTHER", "theirs.py"),
        encoding="utf-8").read()


def test_a_partly_resolvable_diff_is_refused_whole(project):
    """
    Repairing some paths and not others would apply some hunks and not
    others, which is the non-atomic state the dry run exists to prevent.
    """
    diff = _write(os.path.join(project["root"], "p.diff"), """
        --- a/salespkg/etl.py
        +++ b/salespkg/etl.py
        @@ -1 +1 @@
        -VALUE = 1
        +VALUE = 11
        --- a/salespkg/invented.py
        +++ b/salespkg/invented.py
        @@ -1 +1 @@
        -VALUE = 9
        +VALUE = 99
    """)
    with pytest.raises(RuntimeError):
        apply_patch(diff, code_dir=project["code"])
    assert "VALUE = 1\n" == open(os.path.join(project["code"], "salespkg", "etl.py"),
                                 encoding="utf-8").read()


# --- the matcher on its own --------------------------------------------------

def test_the_longest_unique_suffix_wins(project):
    existing = _existing_files(project["code"])
    resolved = _repair_destination("wrong/prefix/salespkg/utils/money.py", existing)
    assert resolved.endswith("/salespkg/utils/money.py")


def test_a_windows_separator_in_the_named_path_is_understood(project):
    existing = _existing_files(project["code"])
    assert _repair_destination(r"salespkg\utils\money.py", existing).endswith("money.py")


def test_caches_are_not_candidates(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "__pycache__" / "etl.py"), "VALUE = 1\n")
    _write(str(code / "old" / "etl.py"), "VALUE = 1\n")
    monkeypatch.chdir(str(root))
    assert _existing_files(str(code)) == []
    assert _repair_destination("etl.py", _existing_files(str(code))) is None
