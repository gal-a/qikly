"""
Fixture proposals: a fifth agent that may suggest data and may not write it.

A criterion no input row can trigger produces a test that passes whatever the
code does. Two thirds of the faults planted in this project's own measurements
were caught by nobody for that reason, so the bar was unmeasurable rather than
wrong.

The agent that closes that gap is the only one that proposes changes to the
inputs, which makes two properties load-bearing rather than nice to have. It
must never write to a fixture file, and it must be capped, because the failure
mode is volume rather than any single bad row: every row looks reasonable on
the way to a fixture set that no longer resembles real data.
"""
import os

import pytest

from qikly.agent_api.agent_interface import _extract_fixture_proposals
from qikly.orchestrator.tuning import propose_fixtures as pf


# ------------------------------------------------------------- the parser ----

SAMPLE = """- [criterion 4] [input_02.csv] TXN-1099,1e2,2026-01-05 | rejected: amount is not a plain decimal
- [criterion 2] covered
- [criterion 7] [input_01.csv] WIDGET-3,receive,0,2026-01-04 09:00 | rejected: quantity must be positive
"""


def test_a_proposal_carries_its_criterion_file_row_and_expected_outcome():
    """
    All four parts or it cannot be reviewed. A row with no expected outcome is
    an input, not a test case, and a row with no criterion cannot be judged at
    all, because its correctness is relative to the rule it exists to reach.
    """
    proposals = _extract_fixture_proposals(SAMPLE, 10)
    first = proposals[0]
    assert first["criterion"] == 4
    assert first["file"] == "input_02.csv"
    assert first["row"] == "TXN-1099,1e2,2026-01-05"
    assert "plain decimal" in first["outcome"]


def test_covered_is_a_real_answer_not_a_missing_one():
    """
    A criterion the data already reaches needs no row. Treating that as a
    failure to find work is how a fixture set grows for no reason.
    """
    covered = [p for p in _extract_fixture_proposals(SAMPLE, 10) if p.get("covered")]
    assert [p["criterion"] for p in covered] == [2]


def test_a_malformed_line_is_dropped_rather_than_guessed_at():
    """
    These end up in a file a person pastes from. Half a row is worse than no
    row, because it looks like something they can use.
    """
    assert _extract_fixture_proposals("- [criterion 1] no pipe here at all", 5) == []
    assert _extract_fixture_proposals("just some prose the model added", 5) == []


def test_a_criterion_number_outside_the_list_is_dropped():
    """It could not be reviewed against anything."""
    assert _extract_fixture_proposals(
        "- [criterion 99] [x.csv] junk | nope", 5) == []


# --------------------------------------------------- it may not write data ----

def test_the_module_never_opens_a_fixture_for_writing():
    """
    The property everything else here depends on. If this agent could edit
    fixtures, it would be choosing the data its own criteria are measured
    against, which is a milder version of the failure the whole project is
    about.
    """
    import inspect

    source = inspect.getsource(pf)
    writes = [line.strip() for line in source.splitlines()
              if "open(" in line and '"w"' in line]
    assert len(writes) == 1, f"more than one write path: {writes}"
    assert "handle.write(render(" in source, "the only write is the proposal file"
    assert "OUT_DIR" in source, "the single write goes to the proposals directory"


def test_the_agent_function_returns_proposals_rather_than_applying_them():
    import inspect

    from qikly.agent_api import agent_interface

    source = inspect.getsource(agent_interface.agent_propose_fixture_rows)
    assert "open(" in source, "it reads the task config"
    assert '"w"' not in source, "the agent function must not write anything"


# ----------------------------------------------------------- the drift cap ----

def test_one_round_cannot_rewrite_the_fixtures():
    """
    The cap exists because the hazard is volume. A loop left running appends
    until the data is mostly machine written, and no single row ever looks
    wrong on the way there.
    """
    criteria = [f"criterion {i}" for i in range(1, 21)]
    proposals = [{"criterion": i, "covered": False, "file": "input_01.csv",
                  "row": f"row-{i}", "outcome": "rejected"} for i in range(1, 21)]
    out = pf.render("T", criteria, proposals)
    assert out.count("Add to ") == pf.MAX_PROPOSALS
    assert "withheld" in out


def test_each_proposal_is_shown_under_the_criterion_it_is_for():
    """
    A row is only right or wrong relative to its criterion, so the two have to
    be read together. Listing rows separately would invite waving them
    through.
    """
    out = pf.render("T", ["amount 0 is rejected"],
                    [{"criterion": 1, "covered": False, "file": "input_01.csv",
                      "row": "X,0", "outcome": "rejected"}])
    assert out.index("amount 0 is rejected") < out.index("X,0")


def test_nothing_to_propose_is_said_plainly():
    out = pf.render("T", ["c"], [{"criterion": 1, "covered": True}])
    assert "Nothing to propose" in out
    assert "Add to " not in out


# --------------------------------------------------- it is a separate agent ----

def test_the_proposer_is_addressable_on_its_own_model():
    """
    Five agents, five settings keys. This one runs rarely and is asked to
    invent data, which is exactly the sort of job someone may want on a
    different model from the one doing repairs.
    """
    from qikly.agent_api.providers.router import _MODE_ROLE

    assert _MODE_ROLE["fixture_proposal"] == "fixtures"


def test_the_settings_file_documents_the_new_agent():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "qikly", "inputs_public", "config", "settings.yaml")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "fixtures: {}" in text
    assert "never edits your fixtures" in text


def test_a_description_of_a_row_is_not_a_row():
    """
    A reply once proposed the literal text "(empty file)" to mean "a log with
    no events at all". It was pasted into a .jsonl as a line and broke the
    fixture. A proposal has to be data that can be appended without further
    interpretation, so anything wrapped in parentheses is dropped.
    """
    assert _extract_fixture_proposals(
        "- [criterion 1] [x.jsonl] (empty file) | accepted: no events", 5) == []
    assert _extract_fixture_proposals(
        "- [criterion 2] [x.csv] (a row with no timestamp) | rejected", 5) == []


def test_a_real_row_is_still_accepted():
    kept = _extract_fixture_proposals("- [criterion 1] [x.csv] A,1,2 | rejected: bad", 5)
    assert len(kept) == 1 and kept[0]["row"] == "A,1,2"


def test_the_prompt_says_data_not_description():
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "qikly", "inputs_public",
                        "agent_defs", "fixture_proposal_prompt.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "never a description of it" in text
