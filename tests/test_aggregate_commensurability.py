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
    Older summaries predate some of these fields.

    Treating absent as a distinct value would report every historical
    aggregate as incommensurable, and a warning that fires on everything is
    one people learn to scroll past.
    """
    assert commensurability(runs(5) + [{"provenance": {}}, {}]) == []
