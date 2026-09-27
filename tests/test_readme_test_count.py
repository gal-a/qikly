"""
The test count on the README's CI badge is a real number, and stays one.

The badge reads "1,500+ tests" beside CI's live pass or fail status. A count
nobody checks drifts: tests get deleted and the badge overstates, or a few
hundred get added and it undersells.

## Why a floor and not a count

It used to claim an exact number, and that asked for a number nobody can
observe. The badge has to be true of CI, because it links to CI, but the only
count you ever see is your own: this tree collects a handful more tests on
Windows than the Linux runner does, since a module needing the `mcp` extra is
skipped at import there. So every update was a guess at a number below a number
you could not see, and when the guess was wrong the release turned red on a
figure that was right where it was measured.

A floor is true of both. Round it down to the hundred and it stays true through
ordinary growth, needs changing only when you cross the next hundred, and can
never overstate. The only thing it must not do is undersell badly, so this also
fails when the floor falls more than `STALE_BY` behind.
"""
import os
import re
from urllib.parse import unquote

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# How far the floor may fall behind before it is underselling the suite.
# Bigger than a release's worth of tests, small enough that the badge is still
# roughly informative.
STALE_BY = 250


def _badge_floor():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    found = re.search(r"workflow/status/gal-a/qikly/ci\.yml\?[^)\s]*label=([^&)\s]+)",
                      readme)
    assert found, "the README's CI badge no longer carries a test count label"
    label = unquote(found.group(1))
    number = re.match(r"([\d,]+)\+ tests$", label)
    assert number, (
        "the CI badge label should read like '1,500+ tests', with the plus, "
        "because it is a floor and not a count. Got %r" % label)
    return int(number.group(1).replace(",", ""))


def test_the_readme_badge_is_a_floor_this_run_clears(request):
    """
    Judged only on a full run: a single file or a -k selection collects far
    fewer tests, which says nothing about the badge.
    """
    floor = _badge_floor()
    collected = request.session.testscollected
    # A subset run says nothing about the badge, and there are three ways to
    # ask for one: -k, -m, and naming files.
    #
    # Read the command line, not `config.args`. `pyproject.toml` sets
    # `testpaths = ["tests"]`, which pytest puts into `config.args` on every
    # invocation including a bare `pytest`, so a check written against that
    # skipped itself on the full run, on CI, and inside the release gate. The
    # count said 1619 collected and the skip reason said "partial".
    typed = list(getattr(request.config.invocation_params, "args", ()))
    named_paths = [arg for arg in typed
                   if not arg.startswith("-")
                   and (os.path.exists(arg.split("::")[0]) or arg.endswith(".py"))]
    if (collected < floor // 2 or request.config.option.keyword
            or request.config.option.markexpr or named_paths):
        pytest.skip("a partial run (%d tests collected) cannot check the badge"
                    % collected)

    assert collected >= floor, (
        "the README badge claims more than %d tests but this full run collected "
        "%d. Lower the badge to the hundred below %d; it is a floor, so it must "
        "be true on every machine and on CI." % (floor, collected, collected))
    assert collected - floor < STALE_BY, (
        "the README badge floor of %d is %d tests behind this run's %d. Raise it "
        "to the hundred below %d." % (floor, collected - floor, collected, collected))


def test_the_badge_floor_is_a_round_number():
    """
    A floor of 1,573 is a count wearing a plus sign, and it will be wrong
    again next week. Rounding to a hundred is what makes it stable.
    """
    assert _badge_floor() % 100 == 0, (
        "round the badge floor down to a hundred, so ordinary growth does not "
        "need a README edit")


def test_the_badge_check_actually_runs_on_a_full_run(request):
    """
    The guard on the guard, because this check has already been dead once.

    It skipped itself on every invocation this project uses, including its own
    release gate, while reporting 1619 collected tests as a partial run. A
    skip is invisible in a green suite, so nothing noticed.

    This asserts the skip condition is false for the run it is part of, which
    is the one thing the check above cannot say about itself.
    """
    typed = list(getattr(request.config.invocation_params, "args", ()))
    named = [arg for arg in typed
             if not arg.startswith("-")
             and (os.path.exists(arg.split("::")[0]) or arg.endswith(".py"))]
    if named or request.config.option.keyword or request.config.option.markexpr:
        pytest.skip("this run did name a subset, so the badge check is right "
                    "to skip and there is nothing to assert")
    assert request.session.testscollected > 1000, (
        "a full run collected %d tests, which is too few for the badge check "
        "to be meaningful" % request.session.testscollected)
