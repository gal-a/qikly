"""
The figures in the public documents, checked against the run data.

Every number in README.md and design_2_performance.md came from a sweep, but
a number in
prose has no link back to the runs it came from. It survives edits, gets
rounded twice, and outlives the measurement. One of these figures did exactly
that: integration+system was quoted for a week with no artifact behind it, and
recomputing it took an afternoon of working out which runs the sweep counted.

So the sweep's own aggregate is the source, `research/stage_breakdown.py`
derives the stage figures from it, and this test asserts the documents agree
with that derivation.

Skipped when the outputs tree is absent, which is the normal state of a fresh
clone. This guards the maintainer's copy, not the user's.
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGGREGATE = os.path.join(ROOT, "outputs", "reports", "aggregate",
                         "aggregate_remeasure_20260831.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(AGGREGATE),
    reason="the sweep's outputs tree is not present in this checkout")


@pytest.fixture(scope="module")
def figures():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "research"))
    from stage_breakdown import breakdown

    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        return breakdown(AGGREGATE)
    finally:
        os.chdir(cwd)


def _doc(name):
    path = os.path.join(ROOT, name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_the_third_sweep_is_the_size_the_documents_claim(figures):
    assert figures["runs"] == 400
    assert figures["missing_summaries"] == 0, (
        "run summaries are missing, so the rates below are over a subset and "
        "the documents would be quoting a different denominator")


def test_design_quotes_the_derived_rates(figures):
    """
    The exact percentages, as the sweep table in design_2_performance.md
    prints them.
    """
    design = _doc(os.path.join("docs", "design_2_performance.md"))
    converged = round(100 * figures["converged_rate"])
    cleared = round(100 * figures["cleared_rate"])
    row = f"| 400 | {cleared}% | {converged}% |"
    assert row in design, (
        f"the sweep table's 31 August row should read {row!r}, from "
        f"{figures['converged']} and {figures['cleared_integration_and_system']} "
        f"of {figures['runs']} runs")


def test_the_rounded_claims_in_readme_match_the_same_data(figures):
    """
    README rounds to "roughly 8 in 10" and "roughly 6 in 10". Those are claims
    about the same two rates, and rounding is where a stale number hides.
    """
    readme = _doc("README.md")
    assert round(10 * figures["cleared_rate"]) == 8, (
        "integration+system no longer rounds to 8 in 10")
    assert round(10 * figures["converged_rate"]) == 6, (
        "end-to-end convergence no longer rounds to 6 in 10")
    assert "8 runs in 10" in readme or "8 in 10" in readme
    assert "6 in 10" in readme


def test_the_unit_stage_gap_is_the_one_the_argument_uses(figures):
    """
    design_2_performance.md argues that nearly the whole gap is the unit
    stage. If that gap
    changes materially the argument needs rewriting, not just the number.
    """
    design = _doc(os.path.join("docs", "design_2_performance.md"))
    gap = figures["unit_stage_gap_points"]
    assert 15 <= gap <= 25, f"the unit-stage gap moved to {gap} points"
    assert "unit stage" in design.lower()
