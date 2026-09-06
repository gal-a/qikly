"""
Small statistical helpers for the research scripts.

Separate from the experiments themselves for one practical reason: the
experiment modules chdir to the project root and import the whole orchestrator
at module scope, so a test that wants to check the arithmetic would drag in a
model client and move the working directory out from under the rest of the
suite. Nothing here imports anything but the standard library, so the parts
that produce the published numbers can be tested directly.
"""
import math
import random


def sign_test_p(pos, neg):
    """
    Exact two sided sign test on paired differences.

    Ties carry no directional information and are excluded, which is both the
    standard treatment and the conservative one here: a pair where both arms
    leak identically is real evidence of no effect, but it cannot say which
    way an effect would run.
    """
    n = pos + neg
    if n == 0:
        return 1.0
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def bootstrap_ci(diffs, iters=20000, seed=0, alpha=0.05):
    """
    Percentile interval for the mean paired difference, resampling whole pairs.

    Resampling pairs rather than observations is what keeps the pairing intact:
    an arm's two counts came from one task at one seed and cannot be shuffled
    apart without destroying the comparison they exist to support.
    """
    if len(diffs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(iters):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(alpha / 2 * iters)]
    hi = means[min(iters - 1, int((1 - alpha / 2) * iters))]
    return (lo, hi)


def wilson(k, n, z=1.96):
    """Binomial interval that stays sane at small n and at k = 0."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))
