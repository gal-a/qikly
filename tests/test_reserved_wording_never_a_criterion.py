"""
The reserved wording ("doesn't matter ..." and the "other" template) must
never reach the test agent as a criterion. Each of these used to become one
with no problem and no --validate warning.
"""
import pytest

from qikly.score_questions import DOESNT_MATTER, OTHER, expand_answers

QUESTION = (
    "acceptance_criteria:\n"
    "  #? What should f(2) do?\n"
    "  #?   1 = f(2) returns 2\n"
    "  #?   2 = f(2) returns 3\n"
    f"  #?   3 = {DOESNT_MATTER}\n"
    f"  #?   4 = {OTHER}\n"
)


def _read(answer):
    return expand_answers(QUESTION + f"  - {answer}\n")


def _criteria(text):
    import yaml
    return yaml.safe_load(text)["acceptance_criteria"]


@pytest.mark.parametrize("answer", [
    DOESNT_MATTER,
    f'"{DOESNT_MATTER}"',
    "Either is fine",
    "either one",
    "Either way is fine.",
    "I don't care",
    "I don\u2019t care",
    "it doesn\u2019t matter",
    "doesn't matter here",
    "Doesn't matter",
])
def test_reserved_wording_means_doesnt_matter(answer):
    text, expanded, problems = _read(answer)
    assert not problems, problems
    assert expanded and expanded[0][1] is None
    assert _criteria(text) is None or _criteria(text) == [], text


@pytest.mark.parametrize("answer", [
    '"4: doesn\'t matter"', "4: either", "4: 3", '"4: I don\'t care"',
    f'"4: {DOESNT_MATTER}"',
])
def test_other_with_reserved_wording_or_a_number_is_refused(answer):
    text, expanded, problems = _read(answer)
    assert len(problems) == 1, problems
    assert "write 3" in problems[0] or "doesn't matter" in problems[0]
    assert all(c is not None and "either" not in c for _, c in expanded), expanded
    assert all(str(c).startswith("TODO:") for c in _criteria(text))


@pytest.mark.parametrize("answer", [
    OTHER,
    f'"{OTHER}"',
    '"N: <your sentence>"',
])
def test_the_other_template_pasted_is_refused(answer):
    text, _, problems = _read(answer)
    assert len(problems) == 1, problems
    assert all(str(c).startswith("TODO:") for c in _criteria(text))


@pytest.mark.parametrize("sentence", [
    "it doesn't matter which currency is shown only when the amount is zero",
    "f(2) returns 2, and either way it never raises",
    "either currency is accepted when the amount is zero",
    "I don't care about the case of the code, f('VIP') returns 'gold'",
])
def test_a_longer_real_sentence_is_not_swallowed(sentence):
    text, expanded, problems = _read(f'"{sentence}"')
    assert not problems and expanded == []
    assert _criteria(text) == [sentence]


def test_other_with_a_real_sentence_still_works():
    _, expanded, problems = _read('"4: f(2) returns 7"')
    assert not problems and expanded == [("4: f(2) returns 7", "f(2) returns 7")]
