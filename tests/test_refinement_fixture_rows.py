"""
The refinement loop proposes fixture rows for the criteria it adds.

Refinement reads converged code and adds criteria about what that code could
still get wrong, which is often an input the fixtures do not contain. A
criterion no row reaches yields a test that passes whatever the code does, so a
sharper bar used to arrive partly unmeasurable.

Nothing here spends a model call. The refinement module is never imported at
collection time, because it moves the working directory when imported, which
would move it out from under every other test in the session.
"""
import contextlib
import importlib
import io
import os
import sys

import pytest

from qikly.orchestrator.tuning import propose_fixtures as pf

_REFINE_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "qikly", "orchestrator", "tuning", "refine_acceptance_criteria.py")

CRITERIA = ["old one", "old two", "added three", "added four"]


def _proposal(n, covered=False):
    if covered:
        return {"criterion": n, "covered": True}
    return {"criterion": n, "covered": False, "file": "input_01.csv",
            "row": "row-%d" % n, "outcome": "rejected"}


# --------------------------------------------------- the proposal function ----

def test_rows_are_proposed_and_counted_for_what_refinement_added(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "agent_propose_fixture_rows",
                        lambda t, c, seed=None: [_proposal(1),
                                                 _proposal(3, covered=True),
                                                 _proposal(4)])
    path, unreachable, added = pf.propose_for_refinement(
        "T", CRITERIA, 3, out_dir=str(tmp_path))

    assert (unreachable, added) == (1, 2), "only criterion 4 is both added and unreached"
    assert os.path.dirname(path) == str(tmp_path)
    with open(path, encoding="utf-8") as handle:
        report = handle.read()
    assert report.index("## Criterion 4") < report.index("## Criterion 1"), (
        "the added criteria come first, so the per-round cap is spent on them")


def test_the_proposer_judges_against_the_whole_refined_bar(tmp_path, monkeypatch):
    """Whether data already reaches a criterion depends on all of it, not the tail."""
    seen = {}

    def fake(task_id, criteria, seed=None):
        seen["criteria"] = list(criteria)
        return []

    monkeypatch.setattr(pf, "agent_propose_fixture_rows", fake)
    pf.propose_for_refinement("T", CRITERIA, 3, out_dir=str(tmp_path))
    assert seen["criteria"] == CRITERIA


def test_nothing_added_costs_no_model_call_and_writes_nothing(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no criteria were added, so the proposer must not run")

    monkeypatch.setattr(pf, "agent_propose_fixture_rows", refuse)
    result = pf.propose_for_refinement("T", CRITERIA, len(CRITERIA) + 1,
                                       out_dir=str(tmp_path))
    assert result == (None, 0, 0)
    assert os.listdir(str(tmp_path)) == []


# ------------------------------------ the wiring, on the real refine() loop ----

@pytest.fixture
def refine_module(tmp_path, monkeypatch):
    """
    refine_acceptance_criteria, imported fresh with its working-directory move
    disabled, and every model call and convergence it makes stubbed.
    """
    monkeypatch.setattr("qikly.paths.chdir_to_project_root", lambda: os.getcwd())
    name = "qikly.orchestrator.tuning.refine_acceptance_criteria"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)

    from qikly.agent_api import agent_interface as ai
    from qikly.agent_api.code_loader import code_loader
    from qikly.orchestrator import orchestrator as orch

    monkeypatch.setattr(ai, "agent_generate_acceptance_criteria",
                        lambda t, seed=None: ["old one", "old two"])
    monkeypatch.setattr(ai, "agent_generate_acceptance_criteria_review",
                        lambda t, c, code, seed=None: [("other", "added three")])
    monkeypatch.setattr(ai, "agent_src_code_path", lambda t: str(tmp_path))
    monkeypatch.setattr(code_loader, "load_codebase", lambda p: "code")
    monkeypatch.setattr(orch, "orchestrate", lambda t, seed=None: None)
    monkeypatch.setattr(orch, "criteria_batching_disabled", contextlib.nullcontext)
    monkeypatch.setattr(module, "_write_draft_task",
                        lambda t, c: str(tmp_path / "draft.yaml"))
    return module


def test_refinement_reports_rows_for_the_criteria_it_added(refine_module, monkeypatch):
    calls = {}

    def fake(task_id, criteria, first_new, seed=None):
        calls["args"] = (task_id, list(criteria), first_new)
        return "report.md", 1, 1

    monkeypatch.setattr(pf, "propose_for_refinement", fake)
    log = io.StringIO()
    criteria, _ = refine_module.refine("T", 1, log, seed=None)

    assert criteria == ["old one", "old two", "added three"]
    assert calls["args"] == ("T", criteria, 3), "the added criteria start at number 3"
    assert "1 of 1 have no data that reaches them" in log.getvalue()
    assert "no fixture was changed" in log.getvalue()


def test_a_failed_proposal_does_not_cost_the_refined_criteria(refine_module, monkeypatch):
    """Every convergence above produced those criteria. A proposal call is not worth them."""
    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(pf, "propose_for_refinement", boom)
    log = io.StringIO()
    criteria, _ = refine_module.refine("T", 1, log, seed=None)

    assert criteria == ["old one", "old two", "added three"]
    assert "fixture proposals failed" in log.getvalue()


def test_a_refinement_that_adds_nothing_asks_for_no_rows(refine_module, monkeypatch):
    from qikly.agent_api import agent_interface as ai

    monkeypatch.setattr(ai, "agent_generate_acceptance_criteria_review",
                        lambda *a, **k: [])
    monkeypatch.setattr(pf, "propose_for_refinement",
                        lambda *a, **k: pytest.fail("nothing was added, so no rows"))
    criteria, _ = refine_module.refine("T", 1, io.StringIO(), seed=None)
    assert criteria == ["old one", "old two"]


def test_refinement_still_writes_no_fixture():
    """
    Its only writes are its own scratch task and its log. Read as text rather
    than imported, for the working-directory reason above.
    """
    with open(_REFINE_SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    writes = [line.strip() for line in source.splitlines()
              if "open(" in line and '"w"' in line]
    assert len(writes) == 2, writes
