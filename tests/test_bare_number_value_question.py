"""
A question with no behaviour to pick carries only the two reserved options,
`1 = doesn't matter` and `2 = other`. A bare number under it is most likely
the person's own value ("it should be 1"); reading it as option 1 made the
value silently become "doesn't matter". It is refused with a message that
names the two safe ways to answer.
"""
import pytest
import yaml

from qikly import score_questions as sq
from qikly.score_questions import expand_answers

VALUE_QUESTION = (
    "acceptance_criteria:\n"
    "  #? Your tests pass whether this number is 0 or 1. What should it be?\n"
    "  #?   1 = doesn't matter, so no test for this\n"
    "  #?   2 = other: write  N: <your sentence>, or just the sentence\n"
)


@pytest.mark.parametrize("answer", ["1", "2", "0", "100", "1.5", "-1"])
def test_a_bare_number_is_refused_not_read_as_doesnt_matter(answer):
    _, expanded, problems = expand_answers(VALUE_QUESTION + f"  - {answer}\n")
    assert len(problems) == 1, problems
    assert "no behaviours to pick" in problems[0]
    assert "doesn't matter" in problems[0]
    assert all(criterion is not None for _, criterion in expanded), expanded


def test_the_words_and_a_sentence_still_answer_it():
    _, expanded, problems = expand_answers(VALUE_QUESTION + "  - doesn't matter\n")
    assert not problems and expanded == [("doesn't matter", None)]
    _, expanded, problems = expand_answers(VALUE_QUESTION + '  - "MAX_RATE is 1"\n')
    assert not problems and expanded == []  # a sentence is left as written
    _, expanded, problems = expand_answers(VALUE_QUESTION + '  - "2: MAX_RATE is 1"\n')
    assert not problems and expanded == [("2: MAX_RATE is 1", "MAX_RATE is 1")]


def test_a_number_under_a_question_with_behaviours_is_unchanged():
    text = ("acceptance_criteria:\n"
            "  #?   1 = f(2) returns 2\n"
            "  #?   2 = f(2) returns 3\n"
            "  #?   3 = doesn't matter, so no test for this\n"
            "  #?   4 = other: write  N: <your sentence>, or just the sentence\n")
    _, expanded, problems = expand_answers(text + "  - 3\n")
    assert not problems and expanded == [("3", None)]


def test_the_scaffolded_line_does_not_invite_a_bare_number():
    block = sq.yaml_block([{"file": "m.py", "path": "/x/m.py", "line": 1,
                            "function": "f", "code": "MAX = 1",
                            "question": sq.ask("guard disabled")}])
    answer = yaml.safe_load("task_id: X\n" + block)["acceptance_criteria"][0]
    assert answer.startswith("TODO:") and "pick" not in answer
    assert "doesn't matter" in answer


NEW_VALUE_QUESTION = (
    "acceptance_criteria:\n"
    "  #? Your tests pass whether this number is 0 or 1. What should it be?\n"
    "  #? Write a sentence that names the value, or the words  doesn't matter  "
    "to skip it.\n"
)
_NUMBER_ADVICE = ("write just", "did you mean option", "Write an option number",
                  "write 1 or", "write 2 or", "Write it as  - 1")


def _value_block():
    return sq.yaml_block([{"file": "m.py", "path": "/x/m.py", "line": 1,
                           "function": "f", "code": "MAX = 1",
                           "question": sq.ask("guard disabled")}])


def test_a_value_question_is_not_numbered_in_a_new_file():
    block = _value_block()
    assert "To answer with a number" not in block
    assert "#?   1 =" not in block and "#?   2 =" not in block
    assert sq.DOESNT_MATTER not in block
    assert "names the value, or the words" in block and "doesn't matter" in block


@pytest.mark.parametrize("answer", ["1", "2", "0", "90", "-1", "1.5"])
def test_a_bare_number_is_refused_under_the_unnumbered_question(answer):
    _, expanded, problems = expand_answers(NEW_VALUE_QUESTION + f"  - {answer}\n")
    assert len(problems) == 1, problems
    assert "doesn't matter" in problems[0]
    assert not any(advice in problems[0] for advice in _NUMBER_ADVICE), problems


def test_the_words_answer_the_unnumbered_question():
    _, expanded, problems = expand_answers(NEW_VALUE_QUESTION + "  - doesn't matter\n")
    assert not problems and expanded == [("doesn't matter", None)]


@pytest.mark.parametrize("answer", [
    "1: 90", "2: 90", "-1: 90", "1)", "1 = doesn't matter, so no test for this",
    "1 2", "yes", "option 1"])
def test_no_message_sends_the_person_back_to_a_number_under_a_value_question(answer):
    """In a file whose two reserved options are numbered, every message about a
    number-like answer names the words, never the number of 'doesn't matter'."""
    _, expanded, problems = expand_answers(VALUE_QUESTION + f'  - "{answer}"\n')
    assert len(problems) == 1, problems
    assert "doesn't matter" in problems[0]
    assert not any(advice in problems[0] for advice in _NUMBER_ADVICE), problems
    assert all(criterion is not None for _, criterion in expanded), expanded
