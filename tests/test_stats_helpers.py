"""
Tests for the statistics behind the research numbers.

These functions are short enough to look obviously right and are exactly the
kind that end up quietly wrong: an off by one in a binomial tail, or a
percentile index that walks off the end of the array, produces a p value or an
interval that is plausible, publishable, and false.

The sign test is checked against values that can be computed by hand, so the
test does not merely restate the implementation.
"""
import math

import pytest

from stats_helpers import bootstrap_ci, sign_test_p, wilson


# ----------------------------------------------------------- sign test ----

def test_no_pairs_is_no_evidence():
    assert sign_test_p(0, 0) == 1.0


def test_a_perfect_split_is_no_evidence():
    assert sign_test_p(5, 5) == 1.0


def test_known_values_by_hand():
    # n = 5 all one way: 2 * (1/32) = 0.0625
    assert sign_test_p(5, 0) == pytest.approx(0.0625)
    # n = 6 all one way: 2 * (1/64) = 0.03125
    assert sign_test_p(6, 0) == pytest.approx(0.03125)
    # n = 6, one dissenter: 2 * (1 + 6)/64 = 0.21875
    assert sign_test_p(5, 1) == pytest.approx(0.21875)
    # n = 7, one dissenter: 2 * (1 + 7)/128 = 0.125
    assert sign_test_p(6, 1) == pytest.approx(0.125)


def test_the_test_is_symmetric():
    """Which arm leaked more cannot change how surprising the split is."""
    for a, b in ((7, 2), (9, 1), (4, 3)):
        assert sign_test_p(a, b) == sign_test_p(b, a)


def test_p_never_exceeds_one():
    """Doubling a one sided tail can overshoot; the cap is not cosmetic."""
    for a in range(0, 8):
        for b in range(0, 8):
            assert 0.0 <= sign_test_p(a, b) <= 1.0


def test_more_agreement_means_a_smaller_p():
    assert sign_test_p(8, 0) < sign_test_p(7, 1) < sign_test_p(6, 2)


def test_ten_pairs_one_way_is_significant_at_five_percent():
    """The smallest run size that could produce a headline claim."""
    assert sign_test_p(10, 0) < 0.05
    assert sign_test_p(4, 0) > 0.05, "four pairs cannot reach significance"


# ----------------------------------------------------------- bootstrap ----

def test_too_few_pairs_returns_nan_rather_than_a_fake_interval():
    lo, hi = bootstrap_ci([3])
    assert math.isnan(lo) and math.isnan(hi)


def test_identical_differences_give_a_zero_width_interval():
    lo, hi = bootstrap_ci([4, 4, 4, 4], iters=500)
    assert lo == hi == 4


def test_the_interval_brackets_the_mean():
    diffs = [1, 3, -2, 5, 0, 2, 7, -1]
    mean = sum(diffs) / len(diffs)
    lo, hi = bootstrap_ci(diffs, iters=4000, seed=7)
    assert lo <= mean <= hi


def test_the_interval_is_reproducible_for_a_given_seed():
    diffs = [1, 3, -2, 5, 0]
    assert bootstrap_ci(diffs, iters=2000, seed=3) == bootstrap_ci(diffs, iters=2000, seed=3)
    assert bootstrap_ci(diffs, iters=2000, seed=3) != bootstrap_ci(diffs, iters=2000, seed=4)


def test_a_wider_spread_gives_a_wider_interval():
    tight = bootstrap_ci([2, 2, 3, 3, 2, 3], iters=4000, seed=1)
    loose = bootstrap_ci([-9, 14, 2, -6, 11, 3], iters=4000, seed=1)
    assert (loose[1] - loose[0]) > (tight[1] - tight[0])


def test_the_percentile_index_stays_in_range():
    """alpha near zero pushes the upper index to iters, one past the end."""
    lo, hi = bootstrap_ci([1, 2, 3, 4], iters=100, seed=0, alpha=0.0001)
    assert not math.isnan(lo) and not math.isnan(hi)


# -------------------------------------------------------------- wilson ----

def test_wilson_handles_the_empty_and_the_zero_cases():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(0, 20)
    assert lo == 0.0 and 0.0 < hi < 0.25, "zero caught is not zero risk"


def test_wilson_stays_inside_the_unit_interval():
    for n in (1, 5, 40):
        for k in range(n + 1):
            lo, hi = wilson(k, n)
            assert 0.0 <= lo <= hi <= 1.0


def test_wilson_narrows_as_n_grows():
    wide = wilson(5, 10)
    narrow = wilson(500, 1000)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])
