"""
What a person types that the task file did not expect.

Two kinds of failure, both found by trying the mistakes rather than by
reading the code: an answer that went to test generation as written, as the
criterion "1)" or "option 1", with no error anywhere; and a field of the
wrong kind, `interface: text` or `inputs: 1.5`, that ended `--validate` in a
traceback. Every case here gets one message that names the fix.
"""
import os

import pytest
import yaml

from qikly.score_questions import drop_question_lines, expand_answers
from qikly.validate import check_task

QUESTION = (
    "acceptance_criteria:\n"
    "  #? What should f(100) do?\n"
    "  #?   1 = f(100) raises ValueError   (as your code does now)\n"
    '  #?   2 = f(100) returns VALUE   (write "2: <the value>")\n'
)
OTHER = '  - "f(5) returns 5"\n'
HEAD = ('task_id: "F"\ntask_name: "f"\ndescription: "f"\n'
        'requirements: "f returns its input, or raises above 99"\n'
        'interface:\n  integration_functions: ["f"]\n')


def _errors(tmp_path, body):
    path = tmp_path / "F.yaml"
    path.write_text(HEAD + body, encoding="utf-8")
    return check_task(str(path))[0]


@pytest.mark.parametrize("answer, says", [
    ("1)", "did you mean option 1?"),
    ("(1)", "did you mean option 1?"),
    ("1.", "did you mean option 1?"),
    ("#1", "did you mean option 1?"),
    ("option 1", "did you mean option 1?"),
    ("Option 2: 99", "as  - 2: 99"),
    ("option 2", "as  - 2: <the value>"),
    ("1,2", "a question takes one answer"),
    ("1 2", "a question takes one answer"),
    ("1 or 2", "a question takes one answer"),
    ("option 7", "its options are 1, 2"),
    # From the audit of the first version of this file.
    ("pick 1", "as  - 1"),
    ("2 = 99", "as  - 2: 99"),
    ("2 -> 99", "as  - 2: 99"),
    ("2) 99", "as  - 2: 99"),
    ("2 (99)", "as  - 2: 99"),
    ("2：99", "as  - 2: 99"),
    ("2 99", "as  - 2: 99"),
    ("2, 99", "as  - 2: 99"),
    ("1 = f(100) raises ValueError", "as  - 1"),
    ("2 = f(100) returns VALUE", "as  - 2: <the value>"),
    ("2: <the value>", "replace <the value> with your value"),
    ("1 (current)", "as  - 1"),
    ("1 (as your code does now)", "as  - 1"),
    ("option 1: 5", "as  - 1"),
    ("<1>", "as  - 1"),
    ("first", "does not take as an answer"),
    ("keep it", "does not take as an answer"),
    ("n/a", "does not take as an answer"),
    ("raises ValueError", "does not take as an answer"),
    ("Answer: 1", "does not take as an answer"),
])
def test_an_option_number_written_another_way_is_named(tmp_path, answer, says):
    errors = _errors(tmp_path, QUESTION + f"  - {answer}\n" + OTHER)
    assert len(errors) == 1 and says in errors[0], errors


@pytest.mark.parametrize("answer", ["1)", "option 1", "1,2", "#1"])
def test_a_run_never_sends_the_answer_as_a_criterion(answer):
    text, _, _ = expand_answers(QUESTION + f"  - {answer}\n" + OTHER)
    sent = yaml.safe_load(drop_question_lines(text))["acceptance_criteria"]
    assert sent == ["f(5) returns 5"]


@pytest.mark.parametrize("answer", ["1", "2: 99", "2:99", '"1"', "1   # the current one",
                                    "“1”", "keep", "Keep", '"keep"',
                                    "3 items are returned", "1 and 2 are both rejected",
                                    '"f(100) returns 1 or 2"'])
def test_the_ways_of_writing_an_answer_that_work_still_do(tmp_path, answer):
    assert _errors(tmp_path, QUESTION + f"  - {answer}\n" + OTHER) == []


def test_a_sentence_that_starts_with_a_number_is_left_alone(tmp_path):
    assert _errors(tmp_path, QUESTION + '  - "100 is rejected with ValueError"\n') == []


def test_an_answer_at_the_left_edge_is_caught_before_yaml_joins_it(tmp_path):
    errors = _errors(tmp_path, QUESTION + "- 1\n" + OTHER)
    assert len(errors) == 1 and "starts at the left edge" in errors[0], errors


def test_a_list_written_at_the_left_edge_throughout_is_fine(tmp_path):
    assert _errors(tmp_path, 'acceptance_criteria:\n- "f(5) returns 5"\n') == []


def test_questions_and_answers_all_at_the_left_edge_are_fine(tmp_path):
    # The first version of the left-edge check refused this valid file.
    assert _errors(tmp_path, 'acceptance_criteria:\n#? What?\n#?   1 = a\n#?   2 = b\n'
                             '- "f(100) returns 7"\n- "f(0) returns 0"\n') == []


def test_a_left_edge_answer_under_a_question_with_no_options_is_caught(tmp_path):
    errors = _errors(tmp_path, "acceptance_criteria:\n  #? What should MAX be?\n- 1\n" + OTHER)
    assert len(errors) == 1 and "starts at the left edge" in errors[0], errors


def test_a_comment_on_the_key_line_still_expands_answers(tmp_path):
    body = QUESTION.replace("acceptance_criteria:", "acceptance_criteria:  # the bar")
    text, expanded, _ = expand_answers(body + "  - keep\n")
    assert expanded == [("keep", "f(100) raises ValueError")]


def test_a_file_in_the_local_encoding_is_read_as_a_run_reads_it(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_bytes((HEAD + "# café\n" + QUESTION + "  - 1\n").encode("cp1252"))
    assert check_task(str(path))[0] == []


def test_a_utf16_file_is_named(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_bytes((HEAD + QUESTION + "  - 1\n").encode("utf-16"))
    errors = check_task(str(path))[0]
    assert len(errors) == 1 and "UTF-16" in errors[0], errors


def test_a_bom_does_not_hide_the_criteria_key(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + (QUESTION + "  - 1\n" + HEAD).encode())
    assert check_task(str(path))[0] == []


def test_an_unclosed_quote_names_the_line_it_opened_on(tmp_path):
    errors = _errors(tmp_path, QUESTION + "  - '1\n" + OTHER)
    assert len(errors) == 1 and "never closed" in errors[0] and "line 11" in errors[0], errors


def test_the_quotes_advice_keeps_the_text_as_typed(tmp_path):
    errors = _errors(tmp_path, "acceptance_criteria:\n  - café('a') returns: yes\n")
    assert "- \"café('a') returns: yes\"" in errors[0], errors


def test_a_number_typed_below_the_todo_line_says_where_it_goes(tmp_path):
    errors = _errors(tmp_path, QUESTION + '  - "TODO: pick 1 or 2"\n  - 1\n' + OTHER)
    assert len(errors) == 1 and "in place of that question's TODO line" in errors[0], errors


def test_an_unreadable_answer_is_not_also_called_a_todo_left(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_text(HEAD + QUESTION + "  - first\n" + OTHER, encoding="utf-8")
    errors, warnings = check_task(str(path))
    assert len(errors) == 1, errors
    assert not any("still left as TODO" in w for w in warnings), warnings


def test_a_run_says_what_validate_finds_before_it_starts(tmp_path, monkeypatch):
    from qikly.orchestrator import orchestrator
    path = tmp_path / "F.yaml"
    path.write_text(HEAD + QUESTION + "  - 1)\n" + OTHER, encoding="utf-8")
    monkeypatch.setattr(orchestrator, "task_config_path", lambda task_id: str(path))
    said = []
    errors = orchestrator._say_what_validate_finds("F", printer=said.append)
    assert len(errors) == 1
    assert "left out of it" in said[0] and "did you mean option 1?" in said[1], said


def test_a_clean_file_makes_a_run_say_nothing(tmp_path, monkeypatch):
    from qikly.orchestrator import orchestrator
    path = tmp_path / "F.yaml"
    path.write_text(HEAD + QUESTION + "  - 1\n" + OTHER, encoding="utf-8")
    monkeypatch.setattr(orchestrator, "task_config_path", lambda task_id: str(path))
    said = []
    assert orchestrator._say_what_validate_finds("F", printer=said.append) == []
    assert said == []


def test_an_empty_file_is_named(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_text("", encoding="utf-8")
    assert check_task(str(path))[0] == ["F.yaml: is empty. Start from  qikly --scaffold <your module>"]


def test_an_unquoted_colon_names_the_quotes_and_does_not_crash(tmp_path):
    errors = _errors(tmp_path, "acceptance_criteria:\n  - f(100) returns: 0\n")
    assert len(errors) == 1, errors
    assert 'in quotes:  - "f(100) returns: 0"' in errors[0]


def test_a_bare_number_is_reported_once_and_names_the_missing_question(tmp_path):
    errors = _errors(tmp_path, "acceptance_criteria:\n  - 1\n" + OTHER)
    assert len(errors) == 1 and "the #? lines above it are gone" in errors[0], errors


def test_a_tab_is_named_as_the_cause(tmp_path):
    errors = _errors(tmp_path, QUESTION + "\t- 1\n")
    assert len(errors) == 1 and "tab" in errors[0], errors


def test_a_yaml_error_quotes_the_line_as_the_person_wrote_it(tmp_path):
    errors = _errors(tmp_path, QUESTION + "      - 1\n" + OTHER)
    assert "'- 1'" in errors[0] and "indent" in errors[0], errors


BASE = {"task_id": "F", "task_name": "f", "description": "f",
        "requirements": ["f returns x"],
        "interface": {"integration_functions": ["f"]},
        "acceptance_criteria": ["f(1) returns 1"], "inputs": ["data/in.csv"],
        "seed": {"implementation": "f.py"}}
WRONG = [None, "", 0, 1.5, True, [], {}, "text", [1, 2], [None], [{"a": 1}],
         {"a": 1}, {"a": [1]}]
CASES = ([(f, w) for f in BASE for w in WRONG]
         + [("interface", {"integration_functions": w}) for w in WRONG]
         + [("interface", {"system_entrypoint": w}) for w in WRONG]
         + [("seed", {"implementation": w, "tests": w}) for w in WRONG])


@pytest.mark.parametrize("field, value", CASES, ids=[f"{f}={v!r}" for f, v in CASES])
def test_a_field_of_the_wrong_kind_is_reported_not_crashed_on(tmp_path, field, value):
    path = tmp_path / "F.yaml"
    path.write_text(yaml.safe_dump(dict(BASE, **{field: value})), encoding="utf-8")
    errors, warnings = check_task(str(path))
    assert all(isinstance(e, str) for e in errors + list(warnings))


@pytest.mark.parametrize("field, value, says", [
    ("interface", "text", "interface should be a mapping"),
    ("inputs", "data/in.csv", "inputs should be a list"),
    ("inputs", 1.5, "inputs should be a list of file paths"),
    ("acceptance_criteria", True, "acceptance_criteria should be a list"),
    ("requirements", {"a": 1}, "requirements should be a list"),
    ("task_name", ["a"], "task_name should be one line of text"),
    ("seed", {"implementation": 3}, "seed.implementation should be a file path"),
])
def test_the_wrong_kind_is_named(tmp_path, field, value, says):
    path = tmp_path / "F.yaml"
    path.write_text(yaml.safe_dump(dict(BASE, **{field: value})), encoding="utf-8")
    errors, _ = check_task(str(path))
    assert any(says in e for e in errors), errors


def test_one_requirement_as_a_string_is_still_checked_for_restating(tmp_path):
    # Read letter by letter before, so the restatement check found nothing.
    task = dict(BASE, requirements="f(1) returns 1", acceptance_criteria=["f(1) returns 1"])
    task.pop("inputs")
    path = tmp_path / "F.yaml"
    path.write_text(yaml.safe_dump(task), encoding="utf-8")
    _, warnings = check_task(str(path))
    assert any("a requirement restates a criterion" in w for w in warnings), warnings


# Found by editing every answer line of the pricing example ~700 ways each.
@pytest.mark.parametrize("answer", ["yes (x)", "(first", "(null)", "one (x)", "(keep", "<Keep (x)"])
def test_a_bracket_does_not_make_a_short_answer_a_sentence(tmp_path, answer):
    errors = _errors(tmp_path, QUESTION + f"  - {answer}\n" + OTHER)
    assert len(errors) == 1 and "does not take as an answer" in errors[0], errors


def test_a_call_in_a_short_answer_is_still_a_sentence(tmp_path):
    assert _errors(tmp_path, QUESTION + '  - "f(100) is 0"\n' + OTHER) == []


@pytest.mark.parametrize("edit", ["", "  # - 1\n"])
def test_a_deleted_or_commented_answer_line_is_named(tmp_path, edit):
    errors = _errors(tmp_path, QUESTION + edit + QUESTION.split("\n", 1)[1] + "  - 1\n")
    assert len(errors) == 1 and "has no answer line under it" in errors[0], errors


def test_the_last_question_without_an_answer_is_named(tmp_path):
    errors = _errors(tmp_path, 'acceptance_criteria:\n  - "f(5) returns 5"\n'
                     + QUESTION.split("\n", 1)[1])
    assert len(errors) == 1 and "has no answer line under it" in errors[0], errors


# From an audit of 0.6.3: these were criteria in 0.6.2, and the first
# version of the answer checks refused them and dropped them from the run.
THREE = ("acceptance_criteria:\n  #? What?\n  #?   1 = f(100) raises ValueError\n"
         "  #?   2 = f(100) returns VALUE\n  #?   3 = f(100) returns 0\n")


@pytest.mark.parametrize("answer", [
    '"1.5 is returned for f(100)"', "2-digit codes are rejected by f(100)",
    "3 - 1 equals f(2)", "1 > 0 holds and f(100) returns 100", "2.0 is what f(100) returns",
    "MAX_RATE=100", "rate==0.5", "result>=100",
])
def test_a_sentence_that_starts_with_a_number_or_compares_is_a_criterion(tmp_path, answer):
    assert _errors(tmp_path, THREE + f"  - {answer}\n") == []


def test_an_unquoted_signature_names_the_quotes(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_text('task_id: "F"\nrequirements: "r"\ninterface:\n  integration_functions:\n'
                    '    - fee(amount: int) -> float\nacceptance_criteria:\n  - "fee(1) is 1"\n')
    errors = check_task(str(path))[0]
    assert len(errors) == 1 and '- "fee(amount: int) -> float"' in errors[0], errors


def test_a_description_written_as_a_list_is_fine(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_text('task_id: "F"\ndescription:\n  - "one"\n  - "two"\nrequirements: "r"\n'
                    'interface:\n  integration_functions: ["f(x)"]\n'
                    'acceptance_criteria:\n  - "f(1) returns 1"\n')
    assert check_task(str(path))[0] == []


def test_a_bare_number_is_not_also_reported_as_a_handover_problem(tmp_path):
    errors = _errors(tmp_path, "acceptance_criteria:\n  - 1\n" + OTHER)
    assert len(errors) == 1, errors


def test_the_run_warning_never_stops_a_run_on_a_cp1252_stream(tmp_path, monkeypatch):
    import io
    import sys
    from qikly.orchestrator import orchestrator
    path = tmp_path / "F.yaml"
    path.write_text(HEAD + "acceptance_criteria:\n  - fee(100) returns: 101 \u2192 up\n",
                    encoding="utf-8")
    monkeypatch.setattr(orchestrator, "task_config_path", lambda task_id: str(path))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    orchestrator._say_what_validate_finds("F")  # must not raise


# From the review of the audit fixes.
@pytest.mark.parametrize("answer", [
    "2 = [1, 2, 3]", "2 = 0.5 per cent", "2 -> not a number", "2 = 99 (ninety nine)",
    "1 = fee(100) raises TypeError", "option=2", "answer=2", "keep=1", "yes=1",
    "opt>2", "<2>99", "<Keep>x", "a<b>", "x=-", "x='", "x !y", "n/a=1",
])
def test_slips_the_comparison_and_length_rules_used_to_let_through(tmp_path, answer):
    errors = _errors(tmp_path, QUESTION + f"  - {answer}\n" + OTHER)
    assert len(errors) == 1, errors


def test_the_handover_error_still_shows_beside_an_unrelated_one(tmp_path):
    path = tmp_path / "F.yaml"
    path.write_text('task_id: "F"\ndescription: "fee(1) returns 1"\nrequirements: "r"\n'
                    'interface:\n  integration_functions: ["fee(x)"]\n'
                    'acceptance_criteria:\n  - "fee(1) returns 1"\n  - 7\n')
    errors = check_task(str(path))[0]
    assert any("criterion 2 is 7" in e for e in errors), errors
    assert any("cannot be stripped safely" in e for e in errors), errors


@pytest.mark.parametrize("value", ["{a: 1}", "[{a: 1}]"])
def test_a_description_that_is_not_text_is_named(tmp_path, value):
    path = tmp_path / "F.yaml"
    path.write_text(f'task_id: "F"\ndescription: {value}\nrequirements: "r"\n'
                    'interface:\n  integration_functions: ["f(x)"]\n'
                    'acceptance_criteria:\n  - "f(1) returns 1"\n')
    assert any("description should be text" in e for e in check_task(str(path))[0])


def test_both_spec_checks_read_a_list_description_as_lines():
    from qikly.orchestrator.tuning import check_criteria, check_suites
    assert "one\ntwo" in check_criteria.build_prompt(["r"], ["c"], ["one", "two"])
    assert "one\ntwo" in check_suites.build_prompt(["r"], ["c"], [], ["one", "two"])
