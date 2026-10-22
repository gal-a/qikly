"""
The questions `--score-code` asks about the faults a suite missed, and how
they reach the task file.

The step new users stopped at was the blank task file after a score. These
guard the bridge across it: each missed fault becomes a question a person can
answer, `--scaffold` writes the questions into `acceptance_criteria` each above
a TODO, and nothing on the way guesses an answer or calls a model.

## What would quietly break it

Code becoming a criterion. The first version collected answers in a markdown
file read by `--criteria-from`, whose Gherkin detection took a dataclass field
`example: int = 3` for a scenario. Code now only ever appears as a comment.

The questions reaching the coding agent. They sit inside the criteria block,
which the cut removes whole, and a test here holds that.

A question that does not say where. `if rate < 0 or rate > 100:` holds two
comparisons, and the questions name the expression rather than the operator.
"""
import os
import subprocess
import sys

import pytest
import yaml

from qikly import score_questions as sq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

MODULE = '''def apply_discount(price, rate):
    if rate < 0 or rate > 100:
        raise ValueError("rate out of range")
    return round(price * (1 - rate / 100), 2)


def label(code):
    if code.strip().lower() == "vip":
        return "gold"
    return "standard"
'''

WEAK_SUITE = '''from pricing import apply_discount, label


def test_discount():
    assert apply_discount(100, 10) == 90


def test_label():
    assert label("vip") == "gold"
'''


def _run(arguments, cwd):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "qikly"] + arguments,
                          cwd=cwd, env=environment, capture_output=True,
                          text=True, timeout=600)


@pytest.fixture
def scored(tmp_path):
    (tmp_path / "pricing.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "test_pricing.py").write_text(WEAK_SUITE, encoding="utf-8")
    done = _run(["--score-code", "pricing.py", "--score-tests",
                 "test_pricing.py", "--score-mutants", "12",
                 "--score-seed", "1"], str(tmp_path))
    asked = list((tmp_path / "qikly-suite-score").glob("*" + sq.QUESTIONS_SUFFIX))
    return tmp_path, done, asked


# ---------------------------------------------------------------- wording --

def test_the_line_number_is_split_from_the_change():
    assert sq.split_change(">= became >, line 12") == (">= became >", 12)
    assert sq.split_change("guard disabled") == ("guard disabled", None)


def test_a_boundary_question_names_the_comparison_and_its_value():
    source = "def f(rate):\n    if rate < 0 or rate > 100:\n        raise ValueError\n"
    question = sq.ask("> became >=", source, 2)
    assert "`rate > 100`" in question and "`rate >= 100`" in question
    assert "exactly `100`" in question


def test_without_the_source_it_still_asks_about_the_operators():
    question = sq.ask("> became >=")
    assert "`>`" in question and "`>=`" in question


@pytest.mark.parametrize("kind, words", [
    ("and became or", "uses `and` or `or`"),
    ("== became !=", "inverted"),
    ("int 2 -> 3", "2 or 3"),
    ("bool True -> False", "flipped"),
    ("guard disabled", "check switched off"),
    ("regex anchors stripped", "only part of a value"),
    (".strip() dropped", "spaces"),
    (".lower() dropped", "letter case"),
    ("raise swallowed", "never raised"),
    ("something new", "this change: something new"),
])
def test_every_kind_of_planted_change_gets_a_question(kind, words):
    question = sq.ask(kind)
    assert words in question
    assert question.rstrip().endswith("?")


def test_no_question_suggests_its_own_answer():
    """
    The answer is the user's. A question that proposed "should be rejected"
    would be a criterion read off the code wearing a question mark.
    """
    for kind in ("> became >=", "guard disabled", "raise swallowed",
                 "int 100 -> 101", ".strip() dropped"):
        question = sq.ask(kind).lower()
        for leading in ("should be rejected", "should be accepted",
                        "must be rejected", "must raise"):
            assert leading not in question, (kind, question)


# ------------------------------------------------------------------ build --

def test_build_shows_the_line_and_its_function(tmp_path):
    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    missed = [{"file": "pricing.py", "change": "> became >=, line 2",
               "family": "arithmetic", "path": str(path)}]
    (q,) = sq.build(missed)
    assert q["function"] == "apply_discount"
    assert q["code"] == "if rate < 0 or rate > 100:"
    assert q["line"] == 2


def test_the_same_question_twice_on_one_line_is_asked_once(tmp_path):
    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    item = {"file": "pricing.py", "change": "guard disabled, line 2",
            "family": "validation", "path": str(path)}
    assert len(sq.build([item, dict(item)])) == 1


def test_a_fault_with_no_readable_path_still_gets_a_question():
    (q,) = sq.build([{"file": "gone.py", "change": "raise swallowed, line 9"}])
    assert q["code"] is None and "never raised" in q["question"]


def test_two_files_with_one_name_keep_their_own_questions(tmp_path):
    """Audit finding: pkg/x/util.py and pkg/y/util.py merged into one."""
    for part in ("x", "y"):
        (tmp_path / part).mkdir()
        (tmp_path / part / "util.py").write_text("def f(v):\n    return v > 0\n",
                                                 encoding="utf-8")
    questions = sq.build([
        {"file": "util.py", "change": "> became >=, line 2",
         "path": str(tmp_path / part / "util.py")} for part in ("x", "y")])
    assert len(questions) == 2
    assert {q["file"] for q in questions} == {"x/util.py", "y/util.py"}


def test_a_constant_already_asked_about_as_a_boundary_is_not_asked_twice(tmp_path):
    """`rate > 100` and `100 -> 101` are one rule, and read as a duplicate."""
    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    questions = sq.build([
        {"file": "pricing.py", "change": "> became >=, line 2", "path": str(path)},
        {"file": "pricing.py", "change": "int 100 -> 101, line 2", "path": str(path)},
        {"file": "pricing.py", "change": "int 2 -> 3, line 4", "path": str(path)}])
    numbers = [q for q in questions if "number is" in q["question"]]
    assert len(numbers) == 1 and "2 or 3" in numbers[0]["question"]


# ------------------------------------------------ in the task file ---------

def _questions(tmp_path, source=MODULE):
    path = tmp_path / "pricing.py"
    path.write_text(source, encoding="utf-8")
    return sq.build([
        {"file": "pricing.py", "change": "> became >=, line 2", "path": str(path)},
        {"file": "pricing.py", "change": "raise swallowed, line 3", "path": str(path)}])


def test_the_block_is_valid_yaml_with_one_todo_per_question(tmp_path):
    questions = _questions(tmp_path)
    data = yaml.safe_load(sq.yaml_block(questions, "2026-10-13 10:00"))
    assert data["acceptance_criteria"] == [
        "TODO: your answer to the question above"] * len(questions)


@pytest.mark.parametrize("code", [
    'example: int = 3',
    'x = "a # b"  # trailing',
    "return {'k': 1, \"q\": [1, 2]}",
    'if s == "Scenario: x":',
    'label = `odd`',
    'name = "café ✓"',
])
def test_no_line_of_code_can_become_a_criterion_or_break_the_file(code):
    """
    The audit's worst finding, closed by construction: code is only ever a
    comment, so whatever it contains, the criteria are exactly the TODOs.
    """
    q = {"file": "m.py", "path": "/x/m.py", "line": 1, "function": "f",
         "code": code, "question": sq.ask("guard disabled")}
    data = yaml.safe_load("task_id: X\n" + sq.yaml_block([q]))
    assert data["acceptance_criteria"] == ["TODO: your answer to the question above"]


def _scaffold_text(tmp_path):
    from qikly.scaffold import build_task

    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    text, problem = build_task(str(path), str(tmp_path), seed="existing")
    assert problem is None
    return text


def test_the_questions_never_reach_the_coding_agent(tmp_path):
    """Comments inside acceptance_criteria are cut out with the criteria."""
    from qikly.agent_api.agent_interface import without_acceptance_criteria
    from qikly.scaffold import with_questions

    questions = _questions(tmp_path)
    text, used = with_questions(_scaffold_text(tmp_path), questions)
    assert used
    handed_over = without_acceptance_criteria(text)
    for q in questions:
        assert q["question"] not in handed_over
    assert "rate > 100" not in handed_over.split("interface:")[0]
    assert "TODO: your answer" not in handed_over


def test_without_questions_the_scaffold_is_unchanged(tmp_path):
    from qikly.scaffold import with_questions

    text = _scaffold_text(tmp_path)
    assert with_questions(text, []) == (text, False)


# ------------------------------------------------------- saved and found ---

def _q(path, question, line=2, code="if rate < 0 or rate > 100:"):
    return {"file": os.path.basename(str(path)), "path": str(path), "line": line,
            "function": "apply_discount", "code": code, "question": question}


def test_scaffold_finds_the_newest_questions_about_that_file(tmp_path):
    import time

    folder = tmp_path / "qikly-suite-score"
    folder.mkdir()
    module = tmp_path / "pricing.py"
    module.write_text(MODULE, encoding="utf-8")
    other = tmp_path / "other.py"
    sq.save([_q(module, "old?")], str(folder / ("a" + sq.QUESTIONS_SUFFIX)),
            "pricing.py", [str(module)])
    time.sleep(0.05)
    sq.save([_q(module, "new?"), _q(other, "elsewhere?")],
            str(folder / ("b" + sq.QUESTIONS_SUFFIX)), "pkg",
            [str(module), str(other)])
    (folder / ("c" + sq.QUESTIONS_SUFFIX)).write_text("not json", encoding="utf-8")
    found, written = sq.latest_for(str(module), str(folder))
    assert [q["question"] for q in found] == ["new?"]
    assert written


def test_no_score_means_no_questions(tmp_path):
    assert sq.latest_for(str(tmp_path / "m.py"), str(tmp_path / "none")) == ([], None)


# --------------------------------------------------------------- advice ----

def test_one_file_is_told_the_exact_command(tmp_path):
    questions = _questions(tmp_path)
    (line,) = sq.advice(questions, str(tmp_path))
    assert "`qikly --scaffold pricing.py`" in line


def test_several_files_are_not_given_a_command_that_guesses(tmp_path):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(MODULE, encoding="utf-8")
    qs = [{"path": str(tmp_path / n)} for n in ("a.py", "b.py")]
    (line,) = sq.advice(qs, str(tmp_path))
    # The folder, which --scaffold takes, and the modules it is about.
    assert "`qikly --scaffold .`" in line and "2 modules" in line


def test_a_module_of_classes_is_sent_to_scaffold(tmp_path):
    """--scaffold takes a class as its constructor and methods now."""
    path = tmp_path / "box.py"
    path.write_text("class Box:\n    def put(self, v):\n        return v > 0\n",
                    encoding="utf-8")
    (line,) = sq.advice([{"path": str(path)}], str(tmp_path))
    assert "Next: `qikly --scaffold" in line


def test_a_module_of_private_helpers_is_sent_to_init(tmp_path):
    """Audit finding: --scaffold refuses a module with nothing public to call."""
    path = tmp_path / "_box.py"
    path.write_text("def _put(v):\n    return v > 0\n", encoding="utf-8")
    (line,) = sq.advice([{"path": str(path)}], str(tmp_path))
    assert "--init" in line


def test_a_second_round_does_not_scaffold_again(tmp_path):
    questions = _questions(tmp_path)
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "PRICING_VERIFY.yaml").write_text("task_id: PRICING_VERIFY\n",
                                               encoding="utf-8")
    (line,) = sq.advice(questions, str(tmp_path))
    assert "already exists" in line and "Next: `qikly --scaffold" not in line
    assert "move it aside" in line


def test_a_path_with_a_space_is_quoted_and_uses_forward_slashes(tmp_path):
    """Audit finding: an unquoted path split into two arguments when pasted."""
    folder = tmp_path / "my proj"
    folder.mkdir()
    (folder / "pricing.py").write_text(MODULE, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (line,) = sq.advice([{"path": str(folder / "pricing.py")}], str(elsewhere))
    command = line.split("`")[1]
    assert '"' in command and "\\" not in command


def test_task_for_matches_scaffold():
    from qikly.scaffold import VERIFY_SUFFIX

    assert sq.task_for("/x/my-pricing.py") == "MY_PRICING" + VERIFY_SUFFIX


# --------------------------------------------------- written only when ---

def test_no_questions_for_a_suite_qikly_wrote(tmp_path):
    """A qikly task already has criteria, so questions would lead nowhere."""
    from qikly.mutation_score import write

    result = {"task": "CALC_TAX", "baseline": True, "generated": True,
              "caught": [], "unscorable": 0, "total": 1, "unreached": [],
              "missed": [{"file": "a.py", "family": "arithmetic",
                          "change": "guard disabled, line 1"}]}
    write(result, [], str(tmp_path))
    assert not list(tmp_path.glob("*" + sq.QUESTIONS_SUFFIX))


def test_no_questions_when_nothing_was_missed(tmp_path):
    from qikly.mutation_score import write

    result = {"task": "pricing.py", "baseline": True, "generated": False,
              "caught": [{"file": "a.py", "family": "arithmetic",
                          "change": "guard disabled, line 1"}],
              "missed": [], "unscorable": 0, "total": 1, "unreached": []}
    write(result, [], str(tmp_path))
    assert not list(tmp_path.glob("*" + sq.QUESTIONS_SUFFIX))


# ------------------------------------------------------------ end to end --

def test_score_then_scaffold_puts_the_questions_where_criteria_live(scored):
    project, done, asked = scored
    assert len(asked) == 1, done.stdout + done.stderr
    assert "questions your tests leave open" in done.stdout
    assert "`qikly --scaffold pricing.py`" in done.stdout
    report = [p for p in (project / "qikly-suite-score").glob("*.md")][0]
    assert "## Questions your tests leave open" in report.read_text(encoding="utf-8")

    made = _run(["--scaffold", "pricing.py"], str(project))
    assert made.returncode == 0, made.stdout + made.stderr
    assert "questions your --score run" in made.stdout
    task_file = project / "inputs_private" / "config" / "tasks" / "PRICING_VERIFY.yaml"
    text = task_file.read_text(encoding="utf-8")
    criteria = yaml.safe_load(text)["acceptance_criteria"]
    assert criteria and all(c.startswith("TODO:") for c in criteria)
    assert "rate > 100" in text.split("acceptance_criteria:")[1]

    checked = _run(["--validate", "pricing.py"], str(project))
    assert "none of its" in checked.stdout + checked.stderr


def test_fresh_scaffold_does_not_take_the_questions(scored):
    project, done, asked = scored
    made = _run(["--scaffold", "pricing.py", "--fresh"], str(project))
    assert made.returncode == 0, made.stdout + made.stderr
    task_file = project / "inputs_private" / "config" / "tasks" / "PRICING.yaml"
    assert "Your tests pass" not in task_file.read_text(encoding="utf-8")


# ------------------------------------------------ re-audit regressions -----

def test_a_clean_rescore_replaces_the_questions_it_used_to_ask(tmp_path):
    """Re-audit: improved tests left the older, now false, questions in force."""
    import time

    folder = tmp_path / "qikly-suite-score"
    folder.mkdir()
    module = tmp_path / "pricing.py"
    module.write_text(MODULE, encoding="utf-8")
    sq.save([_q(module, "old?")], str(folder / ("a" + sq.QUESTIONS_SUFFIX)),
            "pricing.py", [str(module)])
    time.sleep(0.05)
    sq.save([], str(folder / ("b" + sq.QUESTIONS_SUFFIX)), "pricing.py",
            [str(module)])
    assert sq.latest_for(str(module), str(folder))[0] == []


def test_a_question_about_a_line_that_changed_is_dropped(tmp_path):
    """Re-audit: after an edit, line 2 said something else entirely."""
    folder = tmp_path / "qikly-suite-score"
    folder.mkdir()
    module = tmp_path / "pricing.py"
    module.write_text(MODULE, encoding="utf-8")
    sq.save([_q(module, "still?"), _q(module, "gone?", line=4, code="return x")],
            str(folder / ("a" + sq.QUESTIONS_SUFFIX)), "pricing.py", [str(module)])
    assert [q["question"] for q in sq.latest_for(str(module), str(folder))[0]] == ["still?"]


@pytest.mark.parametrize("content", [
    "[]", '{"questions": [{"path": "pricing.py", "line": 2, "question": null}]}',
    '{"questions": "x", "scored": 5}', "null",
])
def test_a_malformed_saved_score_is_skipped_not_fatal(tmp_path, content):
    """Re-audit: `[]` or a null question crashed --scaffold."""
    folder = tmp_path / "qikly-suite-score"
    folder.mkdir()
    (folder / ("a" + sq.QUESTIONS_SUFFIX)).write_text(content, encoding="utf-8")
    from qikly.scaffold import with_questions

    found, _ = sq.latest_for(str(tmp_path / "pricing.py"), str(folder))
    text = _scaffold_text(tmp_path)
    assert with_questions(text, found + [{"question": None}])[0] == text


def test_a_control_character_in_the_code_keeps_the_questions(tmp_path):
    """Re-audit: one ESC in a string literal silently voided every question."""
    from qikly.scaffold import with_questions

    q = _q(tmp_path / "pricing.py", sq.ask("guard disabled"),
           code='if s == "\x1b[0m":')
    text, used = with_questions(_scaffold_text(tmp_path), [q])
    assert used
    yaml.safe_load(text)


def test_neither_agent_reads_a_question_even_when_it_is_moved(tmp_path, monkeypatch):
    """
    Re-audit: the test generator reads the whole task file, comments included,
    so a question quoting the code reached it; and a question moved above
    `acceptance_criteria:` reached the coding agent. Lines qikly writes for a
    question are marked, and dropped from the text either agent receives.
    """
    from qikly.agent_api import agent_interface as ai
    from qikly.scaffold import with_questions

    q = _q(tmp_path / "pricing.py", sq.ask("> became >=", MODULE, 2))
    text, used = with_questions(_scaffold_text(tmp_path), [q])
    assert used
    moved = text.replace("requirements:",
                         "  #? moved by hand: if rate < 0 or rate > 100:\nrequirements:")
    task_file = tmp_path / "PRICING_VERIFY.yaml"
    task_file.write_text(moved, encoding="utf-8")
    monkeypatch.setattr(ai, "task_config_path", lambda _t: str(task_file))

    for view in (ai._task_with_criteria("PRICING_VERIFY", None),
                 ai.without_acceptance_criteria(moved)):
        assert "rate < 0 or rate > 100" not in view
        assert "Your tests pass" not in view
        assert sq.MARK not in view


def test_a_task_file_with_accents_reads_on_windows(tmp_path, monkeypatch):
    """Re-audit: the task was read as cp1252 and an accent stopped the run."""
    from qikly.agent_api import agent_interface as ai

    task_file = tmp_path / "T.yaml"
    task_file.write_text('task_id: "T"\nrequirements:\n  - "caf\u00e9 \u0401"\n',
                         encoding="utf-8")
    monkeypatch.setattr(ai, "task_config_path", lambda _t: str(task_file))
    assert "caf\u00e9 \u0401" in ai._read_task("T")


def test_validate_says_how_many_answers_are_left(tmp_path):
    project = tmp_path
    (project / "pricing.py").write_text(MODULE, encoding="utf-8")
    (project / "test_pricing.py").write_text(WEAK_SUITE, encoding="utf-8")
    _run(["--score-code", "pricing.py", "--score-tests", "test_pricing.py",
          "--score-seed", "1"], str(project))
    _run(["--scaffold", "pricing.py"], str(project))
    task = project / "inputs_private" / "config" / "tasks" / "PRICING_VERIFY.yaml"
    text = task.read_text(encoding="utf-8")
    first = text.index('  - "TODO:', text.index("acceptance_criteria:"))
    end = text.index("\n", first)
    task.write_text(text[:first] + '  - "apply_discount(100, 0) returns 100.0"'
                    + text[end:], encoding="utf-8")
    checked = _run(["--validate", "--tasks", "PRICING_VERIFY"], str(project))
    out = checked.stdout + checked.stderr
    assert "acceptance criteria are answered; a run skips the" in out, out
