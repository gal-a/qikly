"""
Building a task from the document you already wrote.

Two of the first three users asked for the same thing from different angles:
the artefact they already have should be the input. Both halves existed and
nobody had joined them, so `--scaffold X --from-doc Y` is the join.

The interesting part is not the join, it is **what it refuses to join**.

`requirements` is the section the coding agent reads. A feature page almost
always restates its own acceptance criteria in the prose above them, so filling
requirements from the document would carry the criteria to the one agent that
must never see them, by a route none of the existing withholding tests watch.
So requirements are left alone, and `restated()` catches the overlap
mechanically if somebody pastes them in later.

That is the same shape as `scaffold` refusing to derive criteria from an
implementation: the convenient thing is the thing that destroys the property.
"""
import io
import os

import pytest

from qikly import from_doc


DOC = """# FPA metric: reject out-of-range readings

## Background
Product wants readings outside the calibrated band flagged while STEADY.

## Acceptance Criteria
- A reading outside the band while state is STEADY is reported as failed
- A reading outside the band while state is CALIBRATING is ignored
- Every reported failure names the reading id and the band it violated
"""

SCAFFOLD = '''task_id: "BAND"

requirements:
  - "TODO: describe what this module must do"

# TODO. The checkable edge cases.
# The coding agent NEVER sees this section.
acceptance_criteria:
  - "TODO: one checkable statement, with its boundary value"

interface:
  module: "band"
'''


# ------------------------------------------------------------- the merge ----

def test_the_documents_criteria_replace_the_placeholder():
    merged, problem = from_doc.merge(SCAFFOLD, ["first thing", "second thing"])
    assert problem is None
    assert '- "first thing"' in merged
    assert '- "second thing"' in merged
    assert "TODO: one checkable statement" not in merged


def test_the_interface_and_requirements_are_left_alone():
    """The criteria come from the document. Nothing else does."""
    merged, _ = from_doc.merge(SCAFFOLD, ["a criterion"])
    assert 'module: "band"' in merged
    assert '- "TODO: describe what this module must do"' in merged


def test_the_explanatory_comments_survive():
    """
    A YAML load-then-dump would be shorter and would throw away every comment.
    Those comments are the only place the file says why a section is what it
    is, which is most of what makes a scaffolded task teach anything.
    """
    merged, _ = from_doc.merge(SCAFFOLD, ["a criterion"])
    assert "The coding agent NEVER sees this section." in merged


def test_a_document_with_no_criteria_is_refused_rather_than_guessed():
    merged, problem = from_doc.merge(SCAFFOLD, [])
    assert problem and "no acceptance criteria" in problem
    assert merged == SCAFFOLD


def test_quotes_in_a_criterion_do_not_break_the_yaml():
    merged, problem = from_doc.merge(SCAFFOLD, ['it rejects "" and accepts "a"'])
    assert problem is None
    import yaml
    parsed = yaml.safe_load(merged)
    assert parsed["acceptance_criteria"] == ['it rejects "" and accepts "a"']


# --------------------------------------------------- the leak this prevents --

def test_a_pasted_criterion_is_detected():
    """The exact accident: paste the criterion into requirements."""
    crit = "A reading outside the band while state is STEADY is reported as failed"
    hits = from_doc.restated([crit], [crit])
    assert hits and hits[0][2] == 1.0


def test_a_reworded_restatement_is_still_detected():
    hits = from_doc.restated(
        ["The module must report a reading outside the band when state is STEADY"],
        ["A reading outside the band while state is STEADY is reported as failed"])
    assert hits, "a reworded restatement is the common case and must be caught"


def test_a_long_requirement_containing_a_short_criterion_is_caught():
    """
    Scoring against the criterion, not the requirement, is what makes this
    work: dividing by the longer text would hide a criterion buried in a
    paragraph, which is precisely how a pasted page looks.
    """
    hits = from_doc.restated(
        ["This module reads sensor data from the pipeline, normalises it, and "
         "a reading outside the band while state is STEADY is reported as "
         "failed, then it writes the result to disk for the downstream job"],
        ["A reading outside the band while state is STEADY is reported as failed"])
    assert hits


def test_a_genuine_requirement_is_not_flagged():
    """A false positive costs a glance. Flagging everything costs the check."""
    hits = from_doc.restated(
        ["Read readings from the input CSVs and write a JSON report"],
        ["A reading outside the band while state is STEADY is reported as failed"])
    assert not hits


def test_a_tasks_own_field_names_are_not_evidence_of_restatement():
    """
    The false positive that made the check hard to read. A criterion built
    almost entirely from two field names scores against every requirement that
    names both fields, none of which contains the bar it actually sets: the
    word carrying the whole criterion is "earlier", and it appears in no
    requirement. Measured on the shipped CALC_CALENDAR task, this one criterion
    produced three warnings, all wrong.
    """
    criteria = [
        "end_date must not be earlier than start_date",
        "start_date must be a calendar date",
        "end_date must be a calendar date",
        "monthly_rate must be a positive dollar amount",
    ]
    bar = criteria[0]
    hits = from_doc.restated(
        ["Validate each billing request: customer_id, start_date "
         "(a calendar date), end_date (a calendar date), monthly_rate"],
        criteria)
    assert not [h for h in hits if h[1] == bar], (
        "shared field names are the subject, not a restatement")


def test_discounting_never_empties_a_criterion_into_a_free_pass():
    """
    The fallback that keeps the fix from disabling the check. Every word of
    this criterion recurs across the set, so discounting leaves nothing to
    score and the raw measure has to take over. Without the fallback a pasted
    criterion would score zero precisely when the paste is most complete.
    """
    crit = "rejected rows appear in rejected with a reason"
    criteria = [crit,
                "rejected rows appear in rejected with a reason for each",
                "a reason names the rejected field",
                "rejected is a list"]
    hits = from_doc.restated([crit], criteria)
    assert hits and hits[0][2] == 1.0


def test_vocabulary_is_undefined_for_a_handful_of_criteria():
    """One criterion has no words 'common to the set' worth the name."""
    assert from_doc.common_vocabulary(["a lone criterion about widgets"]) == set()
    assert from_doc.common_vocabulary([]) == set()


def test_shared_ordinary_words_alone_do_not_trigger_it():
    hits = from_doc.restated(
        ["The module must be fast and it should not fail"],
        ["Every reported failure names the reading id and the band it violated"])
    assert not hits


@pytest.mark.parametrize("requirements,criteria", [
    (None, ["a"]), (["a"], None), ([], []), (None, None),
])
def test_missing_sections_are_not_an_error(requirements, criteria):
    assert from_doc.restated(requirements, criteria) == []


# ------------------------------------------------------ end to end, on disk --

def test_validate_warns_when_a_requirement_restates_a_criterion(tmp_path, monkeypatch):
    """
    The mechanism, reached the way a user reaches it. Without this, the
    separation would depend on the author noticing, which is the 'habit rather
    than a mechanism' failure the README criticises in other approaches.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(tmp_path))
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    crit = "A reading outside the band while state is STEADY is reported as failed"
    (tasks / "BAND.yaml").write_text(
        'task_id: "BAND"\n'
        'requirements:\n  - "%s"\n'
        'acceptance_criteria:\n  - "%s"\n'
        'interface:\n  module: "band"\n  system_entrypoint: "run(a) -> None"\n'
        % (crit, crit), encoding="utf-8")

    from qikly import validate
    errors, warnings = validate.check_task(str(tasks / "BAND.yaml"))
    assert any("restates a criterion" in w for w in warnings), warnings
    assert any("answer key" in w for w in warnings)
