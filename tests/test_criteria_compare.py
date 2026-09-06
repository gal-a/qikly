"""
Measuring a generated bar against the one you wrote.

The question this answers: if I let qikly draft my acceptance criteria, what
would I have lost? Your criteria are the ground truth, they are never modified,
and they are never shown to the drafting agent.

A tool for this already existed and produced two lists side by side with no
verdict, on the stated grounds that scoring needs a human. That was right about
the difficulty and wrong about the consequence: a reader handed twenty criteria
in two columns does the matching in their head, badly, and keeps an impression
rather than a finding. A stated judgement they can argue with beats an unstated
one they have to construct.

What is tested here is the parsing and the arithmetic, which must be exactly
right, and the framing, which must never let a model's opinion read as a
measurement.
"""
import pytest

from qikly.criteria_compare import parse_coverage, render, summarise

REFERENCE = ["all valid rows accepted",
             "amount above 100 rejected",
             "dates must be YYYY-MM-DD",
             "output has accepted and rejected keys"]
DRAFT = [f"draft criterion {i}" for i in range(1, 8)]


def test_a_full_reply_parses_into_verdicts_and_extras():
    verdicts, extra = parse_coverage(
        "[1] COVERED by draft 3\n"
        "[2] PARTIAL by draft 5 | the draft omits the boundary value\n"
        "[3] MISSED\n"
        "[4] COVERED by draft 1\n"
        "EXTRA: 2, 7\n", 4)
    assert verdicts[1]["status"] == "COVERED" and verdicts[1]["draft"] == 3
    assert verdicts[2]["status"] == "PARTIAL"
    assert verdicts[2]["note"] == "the draft omits the boundary value"
    assert verdicts[3]["status"] == "MISSED" and verdicts[3]["draft"] is None
    assert extra == [2, 7]


def test_a_criterion_with_no_verdict_counts_as_unjudged_not_covered():
    """
    The one that must not go the other way. Silence reading as success would
    make a truncated or lazy reply look like a perfect draft, on the exact
    command whose job is to find what was missed.
    """
    verdicts, _ = parse_coverage("[1] COVERED by draft 1\n", 4)
    summary = summarise(REFERENCE, DRAFT, verdicts, [])
    assert summary["covered"] == 1
    assert summary["unjudged"] == 3
    assert summary["missed"] == 0, "unjudged is not missed, and neither is covered"


def test_a_verdict_for_a_criterion_that_does_not_exist_is_dropped():
    verdicts, _ = parse_coverage("[1] COVERED by draft 1\n[99] MISSED\n", 4)
    assert set(verdicts) == {1}


def test_a_reply_that_is_nothing_but_prose_produces_no_verdicts():
    verdicts, extra = parse_coverage(
        "I compared them and they look broadly similar.", 4)
    assert verdicts == {} and extra == []
    assert summarise(REFERENCE, DRAFT, verdicts, extra)["unjudged"] == 4


def test_the_counts_add_up_to_the_number_of_reference_criteria():
    verdicts, extra = parse_coverage(
        "[1] COVERED by draft 3\n[2] PARTIAL by draft 5\n[3] MISSED\n", 4)
    s = summarise(REFERENCE, DRAFT, verdicts, extra)
    assert s["covered"] + s["partial"] + s["missed"] + s["unjudged"] == len(REFERENCE)
    assert s["reference_count"] == 4 and s["draft_count"] == 7


# ------------------------------------------------------------ the framing ---

def _rendered(raw):
    verdicts, extra = parse_coverage(raw, len(REFERENCE))
    return render("T", REFERENCE, DRAFT, verdicts, extra,
                  summarise(REFERENCE, DRAFT, verdicts, extra))


def test_the_gaps_are_quoted_in_full_rather_than_numbered():
    """
    "criterion 3 was missed" sends a reader back to a file to look it up. The
    text of the rule they would have lost is the thing worth reading.
    """
    out = _rendered("[1] COVERED by draft 1\n[2] MISSED\n[3] MISSED\n[4] COVERED by draft 2\n")
    assert "amount above 100 rejected" in out
    assert "dates must be YYYY-MM-DD" in out


def test_it_never_presents_the_matching_as_a_measurement():
    """
    Deciding whether two differently worded criteria mean the same thing is a
    reading, done here by a model. Printing a percentage without saying that
    would be the exact error this project has withdrawn results for.
    """
    out = _rendered("[1] MISSED\n")
    assert "judgement, not a measurement" in out
    assert "disagree with any line of it" in out


def test_it_says_coverage_is_not_test_quality():
    """
    Two bars can describe the same rule and produce suites that catch different
    faults. This project measures a bar by what its tests detect, and a command
    that let coverage stand in for quality would contradict its own research.
    """
    out = _rendered("[1] COVERED by draft 1\n")
    assert "says nothing about test quality" in out or "test quality" in out


def test_a_clean_result_says_so_plainly():
    out = _rendered("[1] COVERED by draft 1\n[2] COVERED by draft 2\n"
                    "[3] COVERED by draft 3\n[4] COVERED by draft 4\n")
    assert "Nothing of yours was missed" in out


def test_draft_criteria_with_no_counterpart_are_shown_as_worth_reading():
    """
    An extra is not automatically noise. It is often a rule the author knows
    and never wrote down, which is the most valuable thing this can surface.
    """
    out = _rendered("[1] COVERED by draft 1\nEXTRA: 2\n")
    assert "no counterpart" in out.lower()
    # The phrase wraps across two output lines, so match on the rendered text
    # rather than on a sentence that never appears contiguously.
    assert "written down yet" in out
    assert DRAFT[1] in out, "the extra criterion itself has to be shown"


# --------------------------------------------------------------- the CLI ----

def test_a_task_with_no_criteria_is_refused_with_a_reason(monkeypatch, tmp_path):
    """
    This command answers "what would qikly have written instead of what I
    wrote", so it needs what you wrote. Falling back to drafting alone would
    answer a different question silently.
    """
    from qikly import criteria_compare

    monkeypatch.setattr("qikly.agent_api.agent_interface._read_task",
                        lambda task_id: 'task_id: "T"\nrequirements: "r"\n')
    with pytest.raises(ValueError) as caught:
        criteria_compare.compare("T")
    assert "nothing to compare" in str(caught.value)


def test_it_exits_non_zero_when_a_rule_would_have_been_lost(monkeypatch, capsys):
    """
    A missed criterion is the finding, so it is also the exit code: this can
    gate a pipeline that is considering trusting generated criteria.
    """
    from qikly import cli

    monkeypatch.setattr(
        "qikly.criteria_compare.compare",
        lambda task_id, seed=None: {
            "task_id": task_id, "reference": REFERENCE, "draft": DRAFT,
            "verdicts": {"1": {"status": "MISSED", "draft": None, "note": None}},
            "extra": [],
            "summary": {"reference_count": 4, "draft_count": 7, "covered": 0,
                        "partial": 0, "missed": 1, "unjudged": 3, "extra": []},
        })
    assert cli._do_compare_criteria("T", False) == 1


def test_it_exits_zero_when_nothing_was_missed(monkeypatch, capsys):
    from qikly import cli

    monkeypatch.setattr(
        "qikly.criteria_compare.compare",
        lambda task_id, seed=None: {
            "task_id": task_id, "reference": REFERENCE, "draft": DRAFT,
            "verdicts": {}, "extra": [],
            "summary": {"reference_count": 4, "draft_count": 7, "covered": 4,
                        "partial": 0, "missed": 0, "unjudged": 0, "extra": []},
        })
    assert cli._do_compare_criteria("T", False) == 0


def test_your_criteria_are_never_written_to():
    """
    The ground truth has to stay the ground truth. A command that could edit
    the thing it measures against would be measuring itself.
    """
    import inspect

    from qikly import criteria_compare

    source = inspect.getsource(criteria_compare)
    assert '"w"' not in source, "this module must never open a file for writing"
