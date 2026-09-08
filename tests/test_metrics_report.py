"""
Tests for the numbers on the metrics report and the labels on the timeline.

Everything here reads a transaction log and turns it into something a person
will quote: how many patches applied, how many iterations a stage took, how
long a run lasted. Two properties matter more than the arithmetic.

The first is precedence. A single fix cycle can log several actions, and a
cycle that produced a patch which then failed to apply has both patch_created
and patch_apply_failed in it. Classifying that as "applied" inflates the
success bucket with the exact cases the report exists to surface. The order of
the checks is the whole behaviour, so it is tested directly.

The second is that regression checks are not iterations. A stage re-runs
earlier stages' tests after each fix, and counting those re-runs as iterations
would roughly double the reported cost of every stage after the first.
"""
from datetime import timedelta

import pytest

from qikly.orchestrator.reports import metrics_report as mr
from qikly.orchestrator.reports import report as rp


def _cycle(*actions):
    return {"type": "fix_cycle", "steps": [{"action": a} for a in actions]}


def _test_run(status="pass", regression=False):
    return {"type": "test_run", "status": status, "is_regression_check": regression}


# ------------------------------------------------- fix cycle outcomes ----

def test_a_clean_cycle_is_applied():
    assert mr._classify_fix_cycle_outcome(
        _cycle("agent_fix_generated", "patch_created")) == "applied"


def test_a_patch_that_did_not_apply_is_not_counted_as_applied():
    """
    patch_created and patch_apply_failed appear together in exactly the case
    the report exists to surface. Order of the checks decides which wins.
    """
    assert mr._classify_fix_cycle_outcome(
        _cycle("patch_created", "patch_apply_failed")) == "apply_failed"


def test_generation_failure_outranks_everything_else():
    assert mr._classify_fix_cycle_outcome(
        _cycle("fix_generation_failed", "patch_created")) == "generation_failed"
    assert mr._classify_fix_cycle_outcome(
        _cycle("patch_generation_failed", "patch_too_large")) == "generation_failed"


def test_too_large_outranks_apply_failure():
    assert mr._classify_fix_cycle_outcome(
        _cycle("patch_too_large", "patch_apply_failed")) == "too_large"


def test_a_cycle_that_produced_nothing_is_a_generation_failure():
    """Silence is a failure, not an unclassified success."""
    assert mr._classify_fix_cycle_outcome(_cycle("agent_fix_generated")) == "generation_failed"
    assert mr._classify_fix_cycle_outcome(_cycle()) == "generation_failed"


def test_patch_outcomes_ignore_blocks_that_are_not_fix_cycles():
    blocks = [
        _cycle("patch_created"),
        _cycle("patch_apply_failed"),
        _test_run(),
        {"type": "tests_generated", "steps": []},
    ]
    counts = mr.compute_patch_outcomes(blocks)
    assert counts == {"applied": 1, "apply_failed": 1, "too_large": 0,
                      "generation_failed": 0}


def test_patch_outcomes_of_nothing_are_all_zero():
    assert set(mr.compute_patch_outcomes([]).values()) == {0}


# ------------------------------------------------------------ duration ----

def test_duration_spans_first_to_last_event():
    events = [{"ts": "2026-08-26T10:00:00"}, {"ts": "2026-08-26T10:02:30"},
              {"ts": "2026-08-26T10:41:07"}]
    assert mr.compute_duration(events) == timedelta(minutes=41, seconds=7)


def test_duration_is_unknown_rather_than_zero_when_it_cannot_be_computed():
    """
    Logs from before the ts field existed, and runs too short to have two
    events, must not report 0s: that is a measurement, and this is its absence.
    """
    assert mr.compute_duration([]) is None
    assert mr.compute_duration([{"ts": "2026-08-26T10:00:00"}]) is None
    assert mr.compute_duration([{"a": 1}, {"b": 2}]) is None


def test_a_malformed_timestamp_does_not_take_the_report_down():
    assert mr.compute_duration([{"ts": "not a date"}, {"ts": "also not"}]) is None


def test_duration_formats_by_magnitude():
    assert mr._format_duration(None) == "unknown"
    assert mr._format_duration(timedelta(seconds=45)) == "45s"
    assert mr._format_duration(timedelta(minutes=2, seconds=5)) == "2m 5s"
    assert mr._format_duration(timedelta(hours=1, minutes=3, seconds=9)) == "1h 3m 9s"


# ------------------------------------------------------ stage details ----

def test_regression_checks_are_not_counted_as_iterations():
    """
    Later stages re-run earlier stages' tests after every fix. Counting those
    as iterations roughly doubles the reported cost of every stage after the
    first.
    """
    groups = {"system": [
        _test_run("fail"), _test_run("pass"),
        _test_run("pass", regression=True), _test_run("fail", regression=True),
    ]}
    d = mr.compute_stage_details(groups)["system"]
    assert d["iterations"] == 2
    assert d["regression_checks"] == 2
    assert d["regression_failures"] == 1


def test_first_attempt_pass_reads_the_first_primary_run():
    passed = mr.compute_stage_details({"unit": [_test_run("pass"), _test_run("fail")]})
    failed = mr.compute_stage_details({"unit": [_test_run("fail"), _test_run("pass")]})
    assert passed["unit"]["first_attempt_pass"] is True
    assert failed["unit"]["first_attempt_pass"] is False


def test_a_stage_with_no_primary_run_did_not_pass_first_time():
    """Absence of evidence must not read as a first attempt success."""
    d = mr.compute_stage_details({"unit": [_test_run("pass", regression=True)]})["unit"]
    assert d["iterations"] == 0
    assert d["first_attempt_pass"] is False


def test_stage_order_is_preserved():
    """The report presents stages in the order they ran, not alphabetically."""
    groups = {"integration": [_test_run()], "system": [_test_run()],
              "unit": [_test_run()]}
    assert list(mr.compute_stage_details(groups)) == ["integration", "system", "unit"]


# -------------------------------------------------- timeline rendering ----

def test_timeline_outcome_labels_follow_the_same_precedence():
    """
    report.py classifies the same blocks independently of metrics_report.py.
    If the two disagree, the timeline and the KPI row describe the same run
    differently.
    """
    for actions, expected in (
        (("patch_created",), "outcome-ok"),
        (("patch_created", "patch_apply_failed"), "outcome-warn"),
        (("patch_too_large", "patch_apply_failed"), "outcome-warn"),
        (("fix_generation_failed", "patch_created"), "outcome-error"),
        ((), "outcome-error"),
    ):
        assert rp._fix_cycle_outcome(_cycle(*actions))[1] == expected


def test_the_two_classifiers_agree_on_success():
    """The only case where a disagreement would overstate the tool."""
    good = _cycle("agent_fix_generated", "patch_created")
    assert mr._classify_fix_cycle_outcome(good) == "applied"
    assert rp._fix_cycle_outcome(good)[1] == "outcome-ok"


def test_model_written_text_cannot_inject_markup():
    """
    Task names, test names and diffs are model output and go straight into the
    report. quote=False is correct only while _esc is used in element text and
    never inside an attribute.
    """
    assert rp._esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert rp._esc("a & b") == "a &amp; b"


def test_escaping_a_missing_value_is_empty_not_the_word_none():
    assert rp._esc(None) == ""


def test_an_absent_diff_says_so_rather_than_rendering_an_empty_block():
    assert "no diff captured" in rp._diff_html("")
    assert "no diff captured" in rp._diff_html(None)


def test_diff_content_is_escaped_and_classified():
    html = rp._diff_html("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old <b>\n+new\n")
    assert "<b>" not in html, "diff text is model output"
    assert "&lt;b&gt;" in html
    assert "diff-file" in html
