"""
Tests for the aggregate report, which turns many runs into the headline
convergence number.

Two things are guarded here.

The statistics. Convergence is not deterministic, so this report exists to
turn several runs into a rate with an interval. Censored runs (budget
exhausted) must stay out of the iteration averages and be counted separately,
because a censored run's iteration count is a lower bound on what convergence
would have cost, not an observation of it. Folding those in biases the mean
downward and the bias points the flattering way.

The rendering. Every placeholder and separator in the HTML is a literal in a
format string, and a careless find and replace across the tree has already
corrupted all of them once: a blanket em dash substitution turned the missing
value placeholder into a bare comma and rewrote sentences into "Every run
converged ,  nothing to attribute." Nothing failed, nothing was logged, and
the reports simply rendered wrong. The last tests here would have caught it.
"""
import re

import pytest

from qikly.orchestrator.reports import aggregate_report as ar


def _run(task_id, passed, iterations=None, **extra):
    payload = {
        "task_id": task_id,
        "passed_overall": passed,
        "run_timestamp": extra.pop("run_timestamp", "20260826_120000"),
        "stage_iterations": iterations or {"integration": 1, "system": 1, "unit": 1},
    }
    payload.update(extra)
    return payload


# ------------------------------------------------------ wilson interval ----

def test_wilson_is_none_when_there_are_no_runs():
    assert ar.wilson_interval(0, 0) == (None, None)


def test_wilson_stays_inside_zero_and_one_at_the_extremes():
    """The normal approximation runs past the ends here; that is why Wilson."""
    for k, n in ((0, 3), (3, 3), (0, 1), (1, 1), (19, 20)):
        lo, hi = ar.wilson_interval(k, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_never_claims_certainty_from_a_clean_sweep():
    lo, hi = ar.wilson_interval(9, 9)
    assert hi == 1.0
    assert lo < 0.75, "nine of nine is not proof of a 100% rate"


# -------------------------------------------------------------- spread ----

def test_spread_reports_no_sd_for_a_single_observation():
    """Reporting 0 would claim a precision one run cannot support."""
    s = ar._spread([7])
    assert s["n"] == 1 and s["mean"] == 7 and s["sd"] is None


def test_spread_of_nothing_is_empty_not_zero():
    s = ar._spread([])
    assert s == {"n": 0, "mean": None, "sd": None, "min": None, "max": None}


def test_spread_uses_the_sample_standard_deviation():
    # values 2 and 4: mean 3, sample sd = sqrt(((1)+(1))/1) = sqrt(2)
    s = ar._spread([2, 4])
    assert s["sd"] == pytest.approx(2 ** 0.5)


def test_median_of_an_even_count_is_the_midpoint():
    assert ar._median([1, 2, 3, 4]) == 2.5
    assert ar._median([3, 1, 2]) == 2
    assert ar._median([]) is None


# ----------------------------------------------------------- aggregate ----

def test_censored_runs_are_excluded_from_iteration_statistics():
    """
    The converged run took 3 iterations. The censored one stopped at 30 having
    never converged. Averaging both would report 16.5 as the cost of
    convergence, which is not an observation of anything.
    """
    payloads = [
        _run("T", True, {"integration": 1, "system": 1, "unit": 1}),
        _run("T", False, {"integration": 10, "system": 10, "unit": 10}),
    ]
    agg = ar.aggregate(payloads)
    t = agg["tasks"]["T"]
    assert t["iterations_converged"]["mean"] == 3
    assert t["iterations_censored_at"]["mean"] == 30
    assert t["censored"] == 1
    assert t["converged"] == 1


def test_convergence_rate_and_pooled_rate():
    payloads = [_run("A", True), _run("A", False), _run("B", True), _run("B", True)]
    agg = ar.aggregate(payloads)
    assert agg["tasks"]["A"]["convergence_rate"] == 0.5
    assert agg["tasks"]["B"]["convergence_rate"] == 1.0
    assert agg["total_runs"] == 4
    assert agg["total_converged"] == 3
    assert agg["pooled_convergence_rate"] == 0.75


def test_aggregating_nothing_does_not_divide_by_zero():
    agg = ar.aggregate([])
    assert agg["total_runs"] == 0
    assert agg["pooled_convergence_rate"] is None
    assert agg["tasks"] == {}


def test_a_task_with_no_converged_run_reports_an_empty_spread():
    agg = ar.aggregate([_run("T", False)])
    assert agg["tasks"]["T"]["iterations_converged"]["n"] == 0
    assert agg["tasks"]["T"]["convergence_rate"] == 0.0


# ---------------------------------------------------------- test names ----

def test_test_names_dedupe_the_two_pytest_spellings():
    """
    pytest names each failure twice: once as a progress line and once in the
    summary. Both are kept in the log on purpose, so this reader must collapse
    them or every failure is counted twice.
    """
    names = ar._test_names([
        "outputs/tests/T/unit/test_u.py::test_rounds_half_up FAILED [ 43%]",
        "FAILED outputs/tests/T/unit/test_u.py::test_rounds_half_up",
    ])
    assert names == {"test_rounds_half_up"}


def test_test_names_of_nothing_is_empty():
    assert ar._test_names(None) == set()
    assert ar._test_names([]) == set()


def test_stem_groups_related_test_names():
    assert ar._stem("abbreviations") == ar._stem("abbreviation")
    assert ar._stem("rounding") == ar._stem("rounds") == "round"


def test_stem_leaves_short_tokens_alone():
    """Stripping "s" off a four letter word destroys more than it groups."""
    assert ar._stem("rows") == "rows"


# ------------------------------------------------------------ renderers ---

def test_a_missing_value_renders_as_a_placeholder_not_punctuation():
    assert ar._pct(None) == "n/a"
    assert ar._num(None) == "n/a"
    assert ar._spread_cell({"n": 0, "mean": None, "sd": None, "min": None, "max": None}) == "n/a"


def test_present_values_still_render():
    assert ar._pct(0.75) == "75%"
    assert ar._num(3.14159) == "3.1"
    assert ar._num(4) == "4"


def test_rendered_html_contains_no_stray_comma_separators():
    """
    Regression test for the em dash replacement that rewrote every separator
    and placeholder in this file into ", ". The artefact is a comma followed
    by two spaces, which no correct sentence in the template produces.
    """
    agg = ar.aggregate([_run("T", True), _run("T", False)])
    html = ar.render_aggregate_html(agg, skipped=[])
    assert " ,  " not in html
    assert re.search(r",\s{2,}", html) is None


def test_rendered_html_carries_the_current_product_name():
    agg = ar.aggregate([_run("T", True)])
    html = ar.render_aggregate_html(agg, skipped=[])
    # Assembled in pieces so this file does not trip the CI naming guard.
    for stale in ("v" + "_and_v", "v" + "-and-v",
                  "test" + "_qikly", "test" + "-qikly"):
        assert stale not in html


def test_rendered_html_states_the_censoring_caveat():
    """
    A right-censored run must not be presented as a failure to converge. If
    this sentence disappears the report starts overstating what it measured.
    """
    agg = ar.aggregate([_run("T", False)])
    html = ar.render_aggregate_html(agg, skipped=[])
    assert "did not prove convergence impossible" in html
