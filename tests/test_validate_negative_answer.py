"""
`- -1`: an option number typed after the TODO line's own `- `.

YAML reads it as the number minus one. `--validate` used to report that one
slip as two errors, "criterion 2 is empty" (it is not) and "criterion 2 is -1,
not a sentence", and neither said what had happened. It is the mistake a new
user makes while answering numbered questions for the first time, so it gets
one message that names the fix.
"""
import os

from qikly.score_questions import expand_answers

QUESTION = (
    "acceptance_criteria:\n"
    "  #? What should f(100) do?\n"
    "  #?   1 = f(100) raises ValueError   (as your code does now)\n"
    "  #?   2 = f(100) returns 0\n"
)


def _problems(answer):
    _, _, problems = expand_answers(QUESTION + f"  - {answer}\n")
    return problems


def test_a_minus_option_number_is_read_as_the_slip_it_is():
    problems = _problems("-1")
    assert len(problems) == 1, problems
    assert "did you mean option 1?" in problems[0]
    assert "- 1" in problems[0]


def test_the_slip_is_caught_with_a_space_after_the_second_dash_too():
    assert "did you mean option 2?" in _problems("- 2")[0]


def test_a_minus_number_that_is_no_option_lists_the_options():
    problems = _problems("-7")
    assert len(problems) == 1 and "its options are 1, 2" in problems[0], problems


def test_the_right_answer_still_expands():
    text, expanded, problems = expand_answers(QUESTION + "  - 1\n")
    assert not problems
    assert expanded == [("1", "f(100) raises ValueError")]


def test_a_negative_value_in_a_sentence_is_left_alone():
    assert _problems('"f(-1) raises ValueError"') == []


def test_validate_reports_the_slip_once(tmp_path):
    from qikly.validate import check_task
    path = tmp_path / "F_VERIFY.yaml"
    path.write_text(
        'task_id: "F_VERIFY"\n'
        'task_name: "f"\n'
        'description: "f"\n'
        'requirements: "f returns its input, or raises above 99"\n'
        'interface:\n  integration_functions: ["f"]\n'
        + QUESTION + "  - -1\n"
        + '  - "f(5) returns 5"\n',
        encoding="utf-8")
    errors, _ = check_task(str(path))
    about_it = [e for e in errors if "criterion 1" in e]
    assert len(about_it) == 1, errors
    assert "did you mean option 1?" in about_it[0]
    assert not any("is empty" in e or "not a sentence" in e for e in errors), errors


VALUE_QUESTION = (
    "acceptance_criteria:\n"
    "  #? What should f(100) do?\n"
    '  #?   1 = f(100) returns VALUE   (write "1: <the value>")\n'
    "  #?   2 = f(100) raises ValueError\n"
)


def test_the_slip_on_an_option_that_takes_a_value_is_caught():
    # `- -1: 0.0` reads as a mapping, which crashed --validate before.
    _, _, problems = expand_answers(VALUE_QUESTION + "  - -1: 0.0\n")
    assert len(problems) == 1, problems
    assert "did you mean option 1?" in problems[0] and "- 1: 0.0" in problems[0]


def test_a_quoted_minus_number_gets_the_same_message():
    assert "did you mean option 1?" in _problems('"-1"')[0]


def test_options_are_listed_in_numeric_order():
    many = "".join(f"  #?   {i} = f({i}) returns 0\n" for i in range(1, 13))
    _, _, problems = expand_answers(
        "acceptance_criteria:\n  #? What?\n" + many + "  - -13\n")
    assert "its options are 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12" in problems[0], problems


def test_the_message_numbers_the_criterion_as_validate_does():
    _, _, problems = expand_answers(
        QUESTION + '  - "TODO: pick 1 or 2"\n' + QUESTION.split("\n", 1)[1] + "  - -1\n")
    assert problems and problems[0].startswith("criterion 2 "), problems


def test_a_run_drops_the_slip_rather_than_sending_a_number(tmp_path):
    from qikly.score_questions import drop_question_lines
    import yaml
    text, _, _ = expand_answers(QUESTION + "  - -1\n" + '  - "f(5) returns 5"\n')
    sent = yaml.safe_load(drop_question_lines(text))["acceptance_criteria"]
    from qikly.score_questions import is_todo
    assert [c for c in sent if not is_todo(c)] == ["f(5) returns 5"]
