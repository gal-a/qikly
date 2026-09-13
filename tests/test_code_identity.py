"""
Recording which code produced a run.

`qikly_version` is exact for an install from PyPI and misleading for a source
checkout: it only moves on release day, so 420 runs in this project's own
history are stamped 0.1.0 across weeks of changing code. The commit closes
that gap, and the guard below is the part that has to be right, because the
failure it prevents is a confident wrong answer rather than a missing one.
"""
import os

from qikly import code_identity


def test_an_installed_package_records_the_version_and_python(monkeypatch):
    """No git anywhere: still enough to identify a release."""
    monkeypatch.setattr(code_identity, "_git", lambda args, cwd: None)
    info = code_identity.identity(refresh=True)
    assert info["qikly_version"]
    assert info["python_version"]
    assert "git_commit" not in info and "git_dirty" not in info


def test_a_venv_inside_someone_elses_repo_is_not_mistaken_for_qikly(tmp_path, monkeypatch):
    """
    The trap. A virtual environment often sits inside the user's own
    repository, so git answers about *their* project. Recording their commit
    as qikly's would be worse than recording nothing.
    """
    their_repo = tmp_path / "their-project"
    package = their_repo / ".venv" / "Lib" / "site-packages" / "qikly"
    package.mkdir(parents=True)
    monkeypatch.setattr(code_identity, "_git",
                        lambda args, cwd: str(their_repo) if args[0] == "rev-parse" else None)
    assert code_identity.checkout_root(str(package)) is None


def test_qiklys_own_checkout_is_recognised(tmp_path, monkeypatch):
    """The same call, with the package where qikly's own layout puts it."""
    root = tmp_path / "qikly"
    package = root / "src" / "qikly"
    package.mkdir(parents=True)
    monkeypatch.setattr(code_identity, "_git",
                        lambda args, cwd: str(root) if args[0] == "rev-parse" else None)
    assert code_identity.checkout_root(str(package)) == str(root)


def test_this_checkout_reports_its_commit():
    """
    Not mocked. Running from the repository, the real answer must include a
    commit, or the feature does nothing where it matters most.
    """
    import qikly

    package_dir = os.path.dirname(os.path.abspath(qikly.__file__))
    if code_identity.checkout_root(package_dir) is None:
        import pytest
        pytest.skip("not running from a qikly checkout")
    info = code_identity.identity(refresh=True)
    assert len(info["git_commit"]) == 12
    assert isinstance(info["git_dirty"], bool)


def test_describe_reads_as_one_line():
    plain = {"qikly_version": "0.4.3"}
    assert code_identity.describe(plain) == "qikly 0.4.3"
    tagged = dict(plain, git_tag="v0.4.3", git_commit="abcdef123456")
    assert code_identity.describe(tagged) == "qikly 0.4.3 (tag v0.4.3)"
    untagged = dict(plain, git_commit="abcdef123456", git_dirty=True)
    assert code_identity.describe(untagged) == (
        "qikly 0.4.3 (commit abcdef123456), uncommitted changes")


def test_the_cache_is_a_copy_a_caller_cannot_corrupt():
    first = code_identity.identity(refresh=True)
    first["qikly_version"] = "tampered"
    assert code_identity.identity()["qikly_version"] != "tampered"


def test_a_run_summary_carries_the_identity(monkeypatch):
    """The point of all of it: the numbers and the code arrive together."""
    from qikly.orchestrator import run_summary

    prov = run_summary._provenance()
    assert prov["qikly_version"]
    assert prov["python_version"]
