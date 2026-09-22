"""
Drawing a stage's suite more than once and keeping the draft the others agree
with.

The failure being attacked is measured. On a following-distance task whose
criterion says a headway of exactly 2.00 seconds raises no warning, seven runs
in ten wrote a test that warns at 2.00 anyway, and the coding agent cannot
recover from that: it sees only failure output, so it flips the comparison back
and forth until the budget is gone.

The two halves pinned here are the ones that make the technique work or make it
worthless. Drafts that differ only in naming must compare equal, or every
comparison is contested and the vote is noise. Drafts that assert opposite
things about a boundary must compare different, or the one failure this exists
to catch passes straight through.
"""
# consensus.py left the shipped package on 2026-09-22 and lives in research/
# now. These tests came with it, and still run in CI, because the comparison
# is the part that has to be retuned before the idea can be revisited and a
# retuning with no tests around it would just reproduce the 2026-09-20 result.
#
# research/ is already on sys.path: tests/conftest.py puts it there for the
# whole session. An insert here as well was redundant and is gone.
import consensus

RIGHT = '''
def test_boundary_is_not_flagged():
    """At exactly 2.00 s, no warning.
    # Criteria: 1
    """
    row = transform([{"gap_m": "40.0", "ego_speed_mps": "20.0"}])["accepted"][0]
    assert row["warning"] is False
'''

# The same assertion, written by someone who names things differently.
RIGHT_RENAMED = '''
def test_exactly_two_seconds_does_not_warn():
    """Same rule, different words.
    # Criteria: 1
    """
    sample = transform([{"gap_m": "40.0", "ego_speed_mps": "20.0"}])["accepted"][0]
    assert sample["warning"] is False
'''

# The measured failure: the boundary read the opposite way.
WRONG = '''
def test_two_second_rule():
    """Warns at the two second rule.
    # Criteria: 1
    """
    out = transform([{"gap_m": "40.0", "ego_speed_mps": "20.0"}])["accepted"][0]
    assert out["warning"] is True
'''


# ------------------------------------------------- what must compare equal ----

def test_drafts_differing_only_in_naming_are_unanimous():
    """
    If naming counted, every comparison would be contested and the vote would
    carry no information at all.
    """
    report = consensus.compare([RIGHT, RIGHT_RENAMED])
    assert report["unanimous"]
    assert report["contested"] == []


def test_the_signature_ignores_the_test_name_and_local_variables():
    a = consensus.assertions_by_criterion(RIGHT)
    b = consensus.assertions_by_criterion(RIGHT_RENAMED)
    assert a == b
    assert list(a) == [1]


# --------------------------------------------- what must compare different ----

def test_the_opposite_reading_of_a_boundary_is_contested():
    report = consensus.compare([WRONG, RIGHT, RIGHT_RENAMED])
    assert report["contested"] == [1]
    assert not report["unanimous"]


def test_the_majority_reading_is_the_one_kept():
    report = consensus.compare([WRONG, RIGHT, RIGHT_RENAMED])
    assert report["chosen"] in (1, 2)
    assert report["scores"][0] == 0


def test_the_minority_still_wins_when_it_is_the_majority():
    """Nothing here privileges the first draft, or the correct one."""
    report = consensus.compare([WRONG, WRONG.replace("test_two_second_rule",
                                                     "test_other_name"), RIGHT])
    assert report["chosen"] in (0, 1)
    assert report["contested"] == [1]


# ------------------------------------------------------------- the edges ----

def test_a_single_sample_is_unanimous_and_chosen():
    report = consensus.compare([RIGHT])
    assert report["chosen"] == 0 and report["unanimous"]
    assert consensus.describe(report) == "", "nothing to say about one draft"


def test_a_draft_that_does_not_parse_is_silence_rather_than_a_vote():
    """
    An unparseable draft has no reading to contribute. Counting it as a
    dissenting vote would report a disagreement nobody actually had.
    """
    report = consensus.compare([RIGHT, "def test_broken(:\n"])
    assert report["chosen"] == 0
    assert report["contested"] == []
    assert report["covered"] == [1, 0]


def test_a_draft_that_labelled_nothing_does_not_win_by_having_no_opinion():
    """
    Silence agrees with everyone. Without a tiebreak on how much each draft
    actually labelled and tested, a draft that covered nothing could be kept
    over one that did the work.
    """
    unlabelled = 'def test_x():\n    """No marker."""\n    assert 1 == 1\n'
    signature = consensus.assertions_by_criterion(unlabelled)
    assert list(signature) == [consensus.UNLABELLED]

    report = consensus.compare([unlabelled, RIGHT])
    assert report["covered"] == [0, 1]
    assert report["chosen"] == 1


def test_a_test_naming_two_criteria_counts_for_both():
    two = RIGHT.replace("# Criteria: 1", "# Criteria: 1, 4")
    assert sorted(consensus.assertions_by_criterion(two)) == [1, 4]


def test_describe_names_the_contested_criteria():
    line = consensus.describe(consensus.compare([WRONG, RIGHT, RIGHT_RENAMED]))
    assert "disagreed on criterion 1" in line
    line = consensus.describe(consensus.compare([RIGHT, RIGHT_RENAMED]))
    assert "agreed on every criterion" in line


# ------------------------------------------- found in review, 2026-09-20 ----

def _draft(setup, assertion, criterion=1):
    return ('def test_x():\n    """T.\n    # Criteria: %d\n    """\n    %s\n    %s\n'
            % (criterion, setup, assertion))


def test_two_drafts_calling_the_function_with_different_inputs_disagree():
    """
    The first version compared only assert statements, and in ordinary
    arrange-act-assert style the value a test is about sits in the call, not
    the assertion. So these two compared as agreement, which defeats the
    technique on the most common way anyone writes a test.
    """
    a = _draft("result = check_headway(2.00)", "assert result.warning is False")
    b = _draft("other = check_headway(1.50)", "assert other.warning is False")
    assert not consensus.compare([a, b])["unanimous"]


def test_two_drafts_calling_different_functions_disagree():
    """
    Generalising every name erased the callee, so a draft testing the wrong
    function passed consensus unnoticed.
    """
    a = _draft("r = check_headway(2.00)", "assert r.warning is False")
    b = _draft("r = compute_alert(2.00)", "assert r.warning is False")
    assert not consensus.compare([a, b])["unanimous"]


def test_naming_alone_still_does_not_count_as_disagreement():
    """The guard on the fix: comparing whole bodies must not undo this."""
    a = _draft("result = check_headway(2.00)", "assert result.warning is False")
    b = _draft("sample = check_headway(2.00)", "assert sample.warning is False")
    assert consensus.compare([a, b])["unanimous"]


def test_an_even_split_is_reported_as_tied_rather_than_decided():
    """
    At two samples every disagreement is one against one. Counter breaks that
    by insertion order, so the first draft always won and nothing was
    outvoted. Saying so is the difference between a vote and a coin flip.
    """
    wrong = _draft("r = f(2.0)", "assert r is True")
    right = _draft("r = f(2.0)", "assert r is False")
    report = consensus.compare([wrong, right])
    assert report["tied"] == [1]
    assert "nothing was outvoted" in consensus.describe(report)


def test_three_samples_with_a_real_majority_are_not_tied():
    wrong = _draft("r = f(2.0)", "assert r is True")
    right = _draft("r = f(2.0)", "assert r is False")
    right_again = _draft("out = f(2.0)", "assert out is False")
    report = consensus.compare([wrong, right, right_again])
    assert report["tied"] == []
    assert report["chosen"] in (1, 2)


def test_a_criterion_only_one_draft_covered_is_not_outvoted_by_silence():
    """
    Counting "nobody wrote a test" as a vote meant a draft that uniquely
    covered a criterion scored zero for the extra work it had done.
    """
    only = _draft("r = f(1)", "assert r == 1", criterion=5)
    others = _draft("r = f(1)", "assert r == 1", criterion=1)
    report = consensus.compare([only, others, others])
    assert report["scores"] == [1, 1, 1]
    assert report["contested"] == []
