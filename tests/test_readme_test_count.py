"""
The test count on the README's CI badge is a real number, and stays one.

The badge reads "1,180 tests" beside CI's live pass or fail status. A count
nobody checks drifts: tests get deleted and the badge overstates, or a few
hundred get added and it undersells. This compares the badge with the number of
tests pytest collected in the run it is part of.

It only judges a full run. A single file or a -k selection collects far fewer
tests, which says nothing about the badge, so those runs skip it.
"""
import os
import re
from urllib.parse import unquote

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Room for growth before the badge must be updated. Past this, it undersells.
STALE_MARGIN = 0.15

# Set the badge from what CI collects, not from what your machine does. The
# two differ: this tree collects five more tests on Windows than on the Linux
# runner, so a badge written from a local run is above the CI count and turns
# the release red on a number that was right where it was measured. The badge
# links to CI, so CI's count is the one it should claim.


def _badge_count():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    found = re.search(r"workflow/status/gal-a/qikly/ci\.yml\?[^)\s]*label=([^&)\s]+)", readme)
    assert found, "the README's CI badge no longer carries a test count label"
    label = unquote(found.group(1))
    number = re.match(r"([\d,]+) tests$", label)
    assert number, "the CI badge label should read like '1,180 tests', got %r" % label
    return int(number.group(1).replace(",", ""))


def test_the_readme_badge_counts_the_tests_this_run_collected(request):
    badge = _badge_count()
    collected = request.session.testscollected
    if collected < badge // 2 or request.config.option.keyword or request.config.option.markexpr:
        pytest.skip("a partial run (%d tests collected) cannot check the badge" % collected)
    assert collected >= badge, (
        "the README badge says %d tests but this full run collected %d; lower the "
        "number in the badge label" % (badge, collected))
    assert collected <= badge * (1 + STALE_MARGIN), (
        "the README badge says %d tests but this run collected %d; raise the "
        "number in the badge label" % (badge, collected))
