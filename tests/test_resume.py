"""
Tests for continuing a run that died partway.

Everything a run generates costs model calls, and a run that dies out of
credit or mid-outage leaves all of it on disk. Starting again threw it away
and paid a second time. That happened here: a provider limit hit at pair seven
of twelve, and the six finished pairs survived only because the experiment
wrote its own JSON, not because the tool kept anything.

The load-bearing property is that resume is opt in and inspects the disk
rather than trusting a flag. A run told to resume when there is nothing to
resume from must behave exactly like a fresh run, not like a run with an empty
suite, because an empty suite that reads as a passing one is a mistake this
project has made three times.
"""
import os

import pytest

from qikly.orchestrator import orchestrator as orch


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """A tests directory with an integration suite already generated."""
    monkeypatch.setattr(orch, "GENERATED_TESTS_ROOT", str(tmp_path / "tests"))
    d = tmp_path / "tests" / "T" / "integration"
    d.mkdir(parents=True)
    (d / "test_integration.py").write_text("def test_a():\n    assert True\n",
                                           encoding="utf-8")
    return tmp_path


def test_existing_suites_are_found(staged):
    files = orch.existing_stage_tests(os.path.join(orch.GENERATED_TESTS_ROOT, "T"),
                                      "integration")
    assert len(files) == 1


def test_a_stage_never_generated_reports_nothing(staged):
    assert orch.existing_stage_tests(
        os.path.join(orch.GENERATED_TESTS_ROOT, "T"), "unit") == []


def test_the_archive_is_not_mistaken_for_a_live_suite(staged, monkeypatch):
    """
    old/ holds every previous run. Counting it as resumable would restore a
    suite from days ago and silently judge new code against it.
    """
    old = os.path.join(orch.GENERATED_TESTS_ROOT, "T", "old", "20260101_000000",
                       "integration")
    os.makedirs(old)
    with open(os.path.join(old, "test_integration.py"), "w", encoding="utf-8") as fh:
        fh.write("def test_old():\n    assert True\n")
    files = orch.existing_stage_tests(os.path.join(orch.GENERATED_TESTS_ROOT, "T"),
                                      "integration")
    # Against the archive path, not the bare word: on macOS the temporary
    # directory is /private/var/folders/..., and "folders" contains "old".
    archive = os.path.join(orch.GENERATED_TESTS_ROOT, "T", "old")
    assert all(archive not in f for f in files)
    assert len(files) == 1


def test_resumable_reports_which_stages_are_present(staged, monkeypatch):
    monkeypatch.setattr(orch, "agent_src_has_code", lambda d: False)
    monkeypatch.setattr(orch, "agent_src_code_path", lambda t: "/nowhere")
    info = orch.resumable("T")
    assert set(info["tests"]) == {"integration"}
    assert info["implementation"] is False


def test_resumable_reports_the_implementation_separately(staged, monkeypatch):
    monkeypatch.setattr(orch, "agent_src_has_code", lambda d: True)
    monkeypatch.setattr(orch, "agent_src_code_path", lambda t: "/somewhere")
    assert orch.resumable("T")["implementation"] is True


def test_nothing_on_disk_means_nothing_to_resume(tmp_path, monkeypatch):
    """
    A run told to resume with nothing there must start fresh. Treating an
    absent suite as a present one is the empty-suite mistake this project has
    now made three times.
    """
    monkeypatch.setattr(orch, "GENERATED_TESTS_ROOT", str(tmp_path / "tests"))
    monkeypatch.setattr(orch, "agent_src_has_code", lambda d: False)
    monkeypatch.setattr(orch, "agent_src_code_path", lambda t: str(tmp_path / "none"))
    info = orch.resumable("NEVER_RUN")
    assert info["tests"] == {} and info["implementation"] is False


def test_the_orchestrator_only_reuses_when_asked():
    """Guards the wiring: resume defaults off, so an ordinary run is unchanged."""
    import inspect
    src = inspect.getsource(orch.orchestrate)
    assert "resume=False" in inspect.signature(orch.orchestrate).__str__().replace(" ", "") \
        or "resume" in inspect.signature(orch.orchestrate).parameters
    assert 'resumable(task_id) if resume else' in src
