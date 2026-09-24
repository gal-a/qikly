"""
A pooled rate has to be a rate of one thing.

The sweep accounting already refuses to quote a convergence rate computed over
zero runs, and that guard earned its place the day `run_all` shelled out to a
file that exists only in a clone: 130 runs failed instantly, and the report
said "computed over 0 runs, not 130" instead of printing 0%. Read as a number,
that would have looked like this release destroying convergence.

This is the same idea pointed at the other way an aggregate goes quietly wrong.
The runs complete, the arithmetic is correct, and the things pooled were not
the same system: a different model, a different attempt budget, a different
commit. Every positive result this project has withdrawn was withdrawn for
that reason, so the check belongs in the code rather than in the discipline of
whoever runs it.
"""
import pytest

from qikly.orchestrator.reports.aggregate_report import commensurability

BASE = {
    "diagnostic_feedback": "full",
    "traceability_markers_visible": False,
    "qikly_version": "0.5.1",
    "git_commit": "abc123456789",
    "provider": "gemini",
    "model": "gemini-3.5-flash-lite",
    "max_retries_per_stage": 10,
    "criteria_per_batch": 0,
    "git_dirty": False,
}


def runs(count, **overrides):
    return [{"provenance": dict(BASE, **overrides)} for _ in range(count)]


def test_one_system_produces_no_warnings():
    """The common case has to stay quiet, or the loud case gets ignored."""
    assert commensurability(runs(10)) == []


@pytest.mark.parametrize("field,other,phrase", [
    ("qikly_version", "0.5.0", "qikly version"),
    ("git_commit", "def987654321", "commit"),
    ("model", "gemini-3.5-pro", "model"),
    ("provider", "anthropic", "provider"),
    ("max_retries_per_stage", 4, "max_retries_per_stage"),
    ("criteria_per_batch", 4, "criteria_per_batch"),
    ("diagnostic_feedback", "staged", "diagnostic_feedback"),
    ("traceability_markers_visible", True, "traceability_markers_visible"),
])
def test_each_thing_that_changes_the_outcome_is_checked(field, other, phrase):
    """
    Every field here decides how often a task converges.

    A model or a provider decides how well anything is written. The two budgets
    decide how many attempts a task gets before it is recorded as a failure, so
    halving one lowers the rate without anything about the bar or the code
    changing. And the version and commit decide what produced all of it.
    """
    mixed = runs(8) + runs(2, **{field: other})
    found = commensurability(mixed)

    assert found, "a sweep spanning two values of %s was reported as one rate" % field
    assert any(phrase in w for w in found), found
    assert any("8 run" in w and "2 run" in w for w in found), (
        "say how the runs split, or the reader cannot tell a stray run from "
        "half the sweep: %s" % found)


def test_a_dirty_tree_is_named_because_the_number_cannot_be_reproduced():
    """
    The rate describes code that is in no commit.

    Not a hypothetical: every run in this project's own 0.5.1 sweep carried
    git_dirty, because the sweep was taken while the release was being
    prepared. That is fine to do and not fine to quote six months later as
    though the commit it names produced it.
    """
    found = commensurability(runs(3) + runs(7, git_dirty=True))
    assert any("uncommitted" in w for w in found)
    assert any("7 of 10" in w for w in found), found


def test_several_differences_are_all_reported():
    """One warning per difference. The first one found is not the only one."""
    found = commensurability(
        runs(5) + runs(5, model="gemini-3.5-pro", git_commit="def987654321"))
    assert len(found) >= 2, found


def test_a_missing_provenance_block_does_not_invent_a_difference():
    """
    Absent is reported as absent, never as a disagreement.

    This test used to assert silence here, on the reasoning that treating
    absent as a distinct value would flag every historical aggregate and a
    warning firing on everything is one people scroll past. The reasoning was
    right and the conclusion was not: staying silent meant a run recording
    nothing pooled as though it agreed with whatever the rest of the group
    said, which is the failure the whole guard exists to prevent.

    Both concerns are met by warning only when a field is missing from SOME of
    the runs. An archive where none of them has it says nothing, and the
    wording says the comparison could not be made rather than that the values
    differ.
    """
    found = commensurability(runs(5) + [{"provenance": {}}, {}])

    assert found, "runs recording nothing pooled silently"
    assert all("record no" in w for w in found), (
        "a missing field must read as not compared, not as a difference: %s"
        % found)
    assert not any("do not share" in w for w in found), found


def test_a_narrow_arm_and_a_wide_one_are_not_one_rate():
    """
    The comparison the guard exists for, which it could not see.

    `diagnostic_feedback` decides how much of a failing test the coding agent
    is shown, so running one arm narrow and one wide is the whole point of
    having the setting. Neither it nor `traceability_markers_visible` was in
    the provenance block, so an aggregate pooled the two arms into one rate
    and reported nothing at all. Found by asking whether a sweep had measured
    what narrowing costs: it had not, and no artifact said so either way.
    """
    pooled = runs(65) + runs(65, diagnostic_feedback="staged")
    found = commensurability(pooled)
    assert any("diagnostic_feedback" in w for w in found), found
    assert any("65 run" in w for w in found), found


def test_a_run_that_recorded_nothing_is_not_counted_as_agreeing():
    """
    "Absent" and "agrees" are different, and pooling read them the same.

    A summary written before a field existed, or one whose provenance
    collection failed partway through its own broad try/except, contributes
    None to every comparison and was filtered out before the count. It then
    pooled as though it matched whatever the rest of the group said. Schema 3
    predates the provenance block entirely and is still accepted, so this is
    reachable from real archived runs rather than only in principle.
    """
    pooled = runs(8) + [{"provenance": {}}, {"provenance": {}}]
    found = commensurability(pooled)

    assert found, "two runs with no provenance pooled silently"
    assert any("record no" in w and "2 of 10" in w for w in found), found


def test_a_group_that_all_predates_tracking_says_nothing():
    """
    Nothing to compare is not a disagreement.

    An archive of old runs is a legitimate thing to aggregate, and a warning
    on every row of it is a warning nobody reads.
    """
    assert commensurability([{"provenance": {}}] * 5) == []
