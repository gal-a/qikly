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
    for field in ("task_name", "description", "interface"):
        assert "TODO" not in str(task[field]), field
    # Marked, so it is read before a run; still never a rule from the code.
    assert task["requirements"][0].startswith("TODO: MODIFY THIS: pricing.py ")
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


# ------------------------------------------- the Fable audit of bdb698a --

def test_a_boundary_is_never_probed_in_a_function_that_writes_files(tmp_path):
    from qikly import start_options as so
    marker = tmp_path / "marker.txt"
    source = ("def record(n, log=%r):\n"
              "    with open(log, 'a') as handle:\n"
              "        handle.write('called with %%s' %% n)\n"
              "    if n > 10:\n"
              "        raise ValueError(n)\n"
              "    return n\n") % str(marker)
    (tmp_path / "iomod.py").write_text(source, encoding="utf-8")
    question = {"function": "record", "edge": "10", "line": 4,
                "path": str(tmp_path / "iomod.py")}
    tests = ["from iomod import record\n\ndef test_r():\n    assert record(3) == 3\n"]
    assert so.boundary_options(question, source, tests, str(tmp_path)) is None
    assert not marker.exists()


def test_a_package_init_is_named_for_its_package(tmp_path, monkeypatch):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def top(x):\n    return x\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold(os.path.join("mypkg", "__init__.py"), None) == 0
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    assert os.listdir(tasks) == ["MYPKG_VERIFY.yaml"]
    assert cli._task_ids_for(os.path.join("mypkg", "__init__.py")) == "MYPKG_VERIFY"


def test_two_modules_of_one_name_never_share_a_task(tmp_path, monkeypatch):
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "util.py").write_text("def f(x):\n    return x\n",
                                                   encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold(os.path.join("a", "util.py"), None) == 0
    assert cli._do_scaffold(os.path.join("b", "util.py"), None) == 0
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    assert sorted(os.listdir(tasks)) == ["B_UTIL_VERIFY.yaml", "UTIL_VERIFY.yaml"]
    assert cli._task_ids_for(os.path.join("a", "util.py")) == "UTIL_VERIFY"
    assert cli._task_ids_for(os.path.join("b", "util.py")) == "B_UTIL_VERIFY"
    # The same module again is refused, not renamed.
    assert cli._do_scaffold(os.path.join("b", "util.py"), None) == 2


def test_a_task_id_task_is_found_by_its_path_and_named_after_a_run(
        scored, capsys, monkeypatch):
    assert cli._do_scaffold("pricing.py", "SHOP") == 0
    assert cli._task_ids_for("pricing.py") == "SHOP_VERIFY"
    from qikly.agent_api import agent_interface
    tasks = scored / "inputs_private" / "config" / "tasks"
    monkeypatch.setattr(agent_interface, "task_config_path",
                        lambda task_id: str(tasks / f"{task_id}.yaml"))
    cli._do_scaffold("pricing.py", None)
    capsys.readouterr()
    # Two tasks name pricing.py now, so the path would run both: the id.
    cli._say_take_tests(["SHOP_VERIFY"])
    assert "Next: qikly --take-tests SHOP_VERIFY" in capsys.readouterr().out


def test_validate_and_the_run_agree_on_what_a_todo_is(scored):
    from qikly.agent_api.agent_interface import read_acceptance_criteria
    from qikly.validate import check_task
    cli._do_scaffold("pricing.py", None)
    path = scored / TASK
    text = path.read_text(encoding="utf-8")
    text = text.replace('"TODO: what apply_discount(100, 0) should do"',
                        '"TODO apply_discount(100, 0) returns 5"')
    text = text.replace('"TODO: what label(\'VIP\') should do"',
                        '"label(\'VIP\') returns \'gold\' (TODO: confirm with sales)"')
    path.write_text(text, encoding="utf-8")
    sent = read_acceptance_criteria("PRICING_VERIFY")
    assert sent == ["label('VIP') returns 'gold' (TODO: confirm with sales)"]
    errors, warnings = check_task(str(path))
    assert not errors and any("1 of its 6" in w for w in warnings), (errors, warnings)


@pytest.mark.parametrize("text, kept", [
    ('acceptance_criteria: ["TODO: a", "f(1) returns 2"]\n', ["TODO: a", "f(1) returns 2"]),
    ('acceptance_criteria:\n  -\n    "TODO: a"\n  - "f(1) returns 2"\n', ["f(1) returns 2"]),
    ('acceptance_criteria:\n  - "TODO-list f(2) returns 3"\n', ["TODO-list f(2) returns 3"]),
    ('acceptance_criteria:\n  - &x "TODO: a"\n  - "f(1) returns 2"\nother: *x\n',
     ["TODO: a", "f(1) returns 2"]),
    ('acceptance_criteria:\n  - |\n    TODO: a\n  - "f(1) returns 2"\n', ["f(1) returns 2"]),
])
def test_a_todo_goes_whole_and_nothing_else_does(text, kept):
    assert (yaml.safe_load(score_questions.drop_todo_criteria(text))
            ["acceptance_criteria"]) == kept


def test_copied_tests_are_numbered_as_test_generation_saw_the_criteria(
        scored, monkeypatch):
    from qikly import take_tests
    cli._do_scaffold("pricing.py", None)
    path = scored / TASK
    path.write_text(path.read_text(encoding="utf-8").replace(
        '"TODO: what label(\'VIP\') should do"', '"label(\'VIP\') returns \'gold\'"'),
        encoding="utf-8")
    seen = {}
    monkeypatch.setattr(take_tests, "_run",
                        lambda cwd, written, count=0: seen.setdefault("count", count))
    (scored / "outputs" / "tests" / "PRICING_VERIFY" / "integration").mkdir(parents=True)
    (scored / "outputs" / "tests" / "PRICING_VERIFY" / "integration" /
     "test_integration.py").write_text(
        "from outputs.agent_src.code.PRICING_VERIFY.pricing import label\n\n"
        "def test_vip():\n    assert label('VIP') == 'gold'\n", encoding="utf-8")
    take_tests.take(str(scored), "PRICING_VERIFY", str(scored / "tests"), say=lambda *a: None)
    assert seen["count"] == 1


def test_a_run_with_nothing_answered_is_not_started(scored, monkeypatch):
    cli._do_scaffold("pricing.py", None)
    from qikly.agent_api import agent_interface
    monkeypatch.setattr(agent_interface, "task_config_path",
                        lambda task_id: str(scored / TASK))
    assert cli._all_todo(["PRICING_VERIFY"]) == ["PRICING_VERIFY"]


# --------------------------------------- the Fable re-audit of 67b6756 --

def test_a_renamed_task_keeps_the_documents_criteria(tmp_path, monkeypatch):
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "util.py").write_text("def double(x):\n    return 2 * x\n",
                                                   encoding="utf-8")
    (tmp_path / "feature.md").write_text(
        "## Acceptance criteria\n\n- double(2) returns 4\n- double(0) returns 0\n",
        encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    for folder in ("a", "b"):
        assert cli._do_scaffold(os.path.join(folder, "util.py"), None, "feature.md") == 0
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    for name in ("UTIL_VERIFY.yaml", "B_UTIL_VERIFY.yaml"):
        criteria = yaml.safe_load((tasks / name).read_text(encoding="utf-8"))[
            "acceptance_criteria"]
        assert "double(2) returns 4" in criteria, (name, criteria)


def test_a_renamed_task_never_starts_with_a_digit(tmp_path, monkeypatch):
    for folder in ("a", "2024"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "util.py").write_text("def f(x):\n    return x\n",
                                                   encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    cli._do_scaffold(os.path.join("a", "util.py"), None)
    assert cli._do_scaffold(os.path.join("2024", "util.py"), None) == 0
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    assert "DIR_2024_UTIL_VERIFY.yaml" in os.listdir(tasks)


def test_validate_numbers_criteria_as_test_generation_does(scored):
    from qikly import fixture_reach
    from qikly.validate import check_task
    cli._do_scaffold("pricing.py", None)
    seen = {}
    real = fixture_reach.describe
    path = scored / TASK
    path.write_text(path.read_text(encoding="utf-8").replace(
        '"TODO: what apply_discount(100, 100) should do"',
        '"apply_discount(100, 100) raises ValueError"'), encoding="utf-8")

    def spy(task, name, read):
        seen["criteria"] = task.get("acceptance_criteria")
        return real(task, name, read)
    import qikly.fixture_reach
    qikly.fixture_reach.describe = spy
    try:
        check_task(str(path))
    finally:
        qikly.fixture_reach.describe = real
    assert seen["criteria"] == ["apply_discount(100, 100) raises ValueError"]


# ------------------------------------------ the Fable audit of 0cdd358 --

def test_the_requirements_mark_never_reaches_an_agent(scored):
    """
    Left in place, "TODO: MODIFY THIS:" read as an order to the coding agent
    to modify the code; the line goes to the agents without it, so it still
    says to keep what the code does.
    """
    from qikly.agent_api.agent_interface import _read_task
    cli._do_scaffold("pricing.py", None)
    assert "TODO: MODIFY THIS:" in (scored / TASK).read_text(encoding="utf-8")
    sent = _read_task("PRICING_VERIFY")
    assert "MODIFY THIS" not in sent
    assert '- "pricing.py does what its code does now; keep that' in sent
