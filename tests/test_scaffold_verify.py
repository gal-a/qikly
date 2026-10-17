"""
Step 2 for code you already have: `qikly --scaffold PATH` after `qikly
--score PATH`, then `--validate`, `--tasks` and `--take-tests` on the same
PATH.

What these pin, in order of how much a failure would cost a first-time user:

- the task file leaves only the questions to answer: nothing qikly can read
  from the code is a TODO, and the data file is never only a header;
- each question says what the code does beside the value in question, never
  at it, and none of that reaches either agent;
- a question left as TODO is skipped, not sent as a criterion, and a file
  with nothing answered is stopped before a paid run;
- the path given to --score names the task in every later step, for a file
  and for a folder.
"""
import os

import pytest
import yaml

from qikly import cli, score_questions

PRICING = ('def apply_discount(price, rate):\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n'
           '\n'
           '\n'
           'def label(code):\n'
           '    if code.strip().lower() == "vip":\n'
           '        return "gold"\n'
           '    return "standard"\n')
TESTS = ('from pricing import apply_discount, label\n'
         '\n'
         '\n'
         'def test_discount():\n'
         '    assert apply_discount(100, 10) == 90.0\n'
         '\n'
         '\n'
         'def test_label():\n'
         '    assert label("vip") == "gold"\n')
TASK = os.path.join("inputs_private", "config", "tasks", "PRICING_VERIFY.yaml")


def _project(root, name="pricing.py"):
    (root / name).write_text(PRICING, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    stem = os.path.splitext(name)[0]
    (root / "tests" / f"test_{stem}.py").write_text(
        TESTS.replace("from pricing", f"from {stem}"), encoding="utf-8")


@pytest.fixture
def scored(tmp_path, monkeypatch):
    """A project scored the way step 1 scores it, run from its folder."""
    _project(tmp_path)
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    assert cli._do_score_suite(None, None, None, code="pricing.py", tests=None) == 0
    return tmp_path


def _task(root):
    return (root / TASK).read_text(encoding="utf-8")


def test_only_the_questions_are_left_to_answer(scored):
    assert cli._do_scaffold("pricing.py", None) == 0
    text = _task(scored)
    task = yaml.safe_load(text)
    for field in ("task_name", "description", "interface", "requirements"):
        assert "TODO" not in str(task[field]), field
    criteria = task["acceptance_criteria"]
    assert criteria and all(c.startswith("TODO: what ") for c in criteria), criteria
    assert task["seed"]["implementation"] == "pricing.py"
    data = (scored / "inputs_private" / "data" / "PRICING" / "input_01.csv").read_text()
    assert data.splitlines()[0] == "price,rate,code"
    assert len(data.splitlines()) > 1, "the data file is only a header"


def test_each_question_says_what_the_code_does_beside_the_value(scored):
    cli._do_scaffold("pricing.py", None)
    text = _task(scored)
    assert "#? What should apply_discount(100, 100) do?" in text
    assert "raise ValueError, as rate 101 does now" in text
    assert "as rate 99 does now (it returns 1.0)" in text
    # Never at the value itself: that is the question.
    assert "as rate 100 does now" not in text
    assert '- "TODO: what apply_discount(100, 100) should do"' in text


def test_neither_agent_reads_the_notes(scored):
    from qikly.agent_api.agent_interface import _read_task
    cli._do_scaffold("pricing.py", None)
    sent = _read_task("PRICING_VERIFY")
    assert "#?" not in sent and "Found by running your code" not in sent
    assert "rate 101" not in sent


def test_a_question_left_as_todo_is_skipped(scored):
    from qikly.agent_api.agent_interface import read_acceptance_criteria
    cli._do_scaffold("pricing.py", None)
    path = scored / TASK
    text = path.read_text(encoding="utf-8").replace(
        '"TODO: what apply_discount(100, 100) should do"',
        '"apply_discount(100, 100) raises ValueError"')
    path.write_text(text, encoding="utf-8")
    assert read_acceptance_criteria("PRICING_VERIFY") == [
        "apply_discount(100, 100) raises ValueError"]


def test_validate_stops_a_file_with_nothing_answered(scored):
    from qikly.validate import check_task
    cli._do_scaffold("pricing.py", None)
    errors, warnings = check_task(str(scored / TASK))
    assert any("none of its" in e for e in errors), errors
    path = scored / TASK
    path.write_text(path.read_text(encoding="utf-8").replace(
        '"TODO: what label(\'VIP\') should do"', '"label(\'VIP\') returns \'gold\'"'),
        encoding="utf-8")
    errors, warnings = check_task(str(path))
    assert not errors, errors
    assert any("a run skips" in w for w in warnings), warnings


def test_the_path_names_the_task_in_every_later_step(scored, capsys):
    assert cli._task_ids_for("pricing.py") is None
    assert "qikly --scaffold pricing.py" in capsys.readouterr().err
    cli._do_scaffold("pricing.py", None)
    assert cli._task_ids_for("pricing.py") == "PRICING_VERIFY"
    assert cli._task_ids_for(".") == "PRICING_VERIFY"
    # A task id still works as one, as before.
    assert cli._task_ids_for("PRICING_VERIFY,OTHER") == "PRICING_VERIFY,OTHER"


def test_the_step_after_a_run_names_the_module(scored, capsys, monkeypatch):
    cli._do_scaffold("pricing.py", None)
    from qikly.agent_api import agent_interface
    monkeypatch.setattr(agent_interface, "task_config_path",
                        lambda task_id: str(scored / TASK))
    cli._say_take_tests(["PRICING_VERIFY"])
    assert "Next: qikly --take-tests pricing.py" in capsys.readouterr().out


def test_scaffold_says_the_same_path_for_the_next_steps(scored, capsys):
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    out = capsys.readouterr().out
    assert "qikly --validate pricing.py" in out
    assert "qikly --tasks pricing.py" in out


def test_a_folder_gets_a_task_file_for_each_module_it_was_asked_about(tmp_path, monkeypatch):
    shop = tmp_path / "shop"
    shop.mkdir()
    _project(shop, "pricing.py")
    _project(shop, "prices2.py")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(shop))
    assert cli._scaffold_folder(str(shop)) == 2, "nothing scored yet"
    assert cli._do_score_suite(None, None, None, code="shop", tests="shop/tests") == 0
    assert cli._do_scaffold("shop", None) == 0
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    assert sorted(os.listdir(tasks)) == ["PRICES2_VERIFY.yaml", "PRICING_VERIFY.yaml"]
    assert cli._task_ids_for("shop") == "PRICES2_VERIFY,PRICING_VERIFY"


def test_score_points_at_scaffold(tmp_path):
    questions = [{"path": str(tmp_path / "pricing.py"), "question": "q"}]
    (tmp_path / "pricing.py").write_text(PRICING)
    advice = score_questions.advice(questions, str(tmp_path))
    assert advice == ["Next: `qikly --scaffold pricing.py` writes the task file, "
                      "with these questions in it to answer."]
