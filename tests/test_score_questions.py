"""
The questions `--score-code` asks about the faults a suite missed.

The step new users stopped at was the blank task file after a score. These
guard the bridge across it: each missed fault becomes a question a person can
answer, the answers become acceptance criteria through `--criteria-from`
unchanged, and nothing on the way guesses an answer or calls a model.

## What would quietly break it

A question taken for a criterion. The file is read by `--criteria-from`, so a
question that leaked into the criteria section would become a "rule" nobody
wrote, which is the one thing this tool must never do with a bar.

A question that does not say where. `if rate < 0 or rate > 100:` holds two
comparisons, and "whether this is `>` or `>=`" about that line points at
neither, so the questions name the expression.

The documented next steps not working. They chain three existing commands,
and the chain broke on its first run: `--criteria-from` left half of
`--scaffold`'s wrapped placeholder behind and the task stopped being YAML.
"""
import os
import subprocess
import sys

import pytest
import yaml

from qikly import score_questions as sq
from qikly.criteria_import import parse_criteria

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
    environment["QIKLY_NO_INVITE"] = "1"
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
    asked = list((tmp_path / "qikly-suite-score").glob("*_questions.md"))
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


# ------------------------------------- the file is --criteria-from input --

def _file(questions=None):
    questions = questions or [
        {"file": "pricing.py", "path": None, "line": 2,
         "function": "apply_discount", "code": "if rate > 100:",
         "question": sq.ask("> became >=")},
        {"file": "pricing.py", "path": None, "line": 3,
         "function": "apply_discount", "code": "raise ValueError('x')",
         "question": sq.ask("raise swallowed")}]
    return sq.render("pricing.py", questions,
                     ["qikly --scaffold pricing.py"])


def test_an_unanswered_file_holds_no_criteria():
    """Nothing in the questions, the code or the instructions is a criterion."""
    assert parse_criteria(_file()) == []


def test_only_the_answers_become_criteria():
    text = _file()
    answers = ["a rate of exactly 100 is accepted",
               "a rate of 101 raises ValueError"]
    for answer in answers:
        text = text.replace("\n- \n", "\n- %s\n" % answer, 1)
    assert parse_criteria(text) == answers


def test_the_file_has_one_answer_line_per_question():
    text = _file()
    section = text.split("## Acceptance Criteria", 1)[1]
    assert section.count("\n- ") == 2


# --------------------------------------------------------- next steps -----

def test_one_file_gets_the_exact_task_id_scaffold_will_write(tmp_path):
    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    steps, note = sq.next_steps(
        [{"path": str(path)}],
        str(tmp_path / "qikly-suite-score" / "p_questions.md"), str(tmp_path))
    assert note is None
    assert steps[0] == "qikly --scaffold pricing.py"
    assert steps[1].endswith("--task-id PRICING_VERIFY")
    assert steps[2] == "qikly --validate --tasks PRICING_VERIFY"


def test_questions_over_several_files_give_no_command_to_paste(tmp_path):
    """A template pasted as it stands fails, so none is printed."""
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(MODULE, encoding="utf-8")
    steps, note = sq.next_steps(
        [{"path": str(tmp_path / "a.py")}, {"path": str(tmp_path / "b.py")}],
        str(tmp_path / "q_questions.md"), str(tmp_path))
    assert steps == []
    assert "2 files" in note


def test_a_module_of_classes_is_not_sent_to_a_scaffold_that_refuses_it(tmp_path):
    """Audit finding: the chain failed at its first step on `class Box`."""
    path = tmp_path / "box.py"
    path.write_text("class Box:\n    def put(self, v):\n        return v > 0\n",
                    encoding="utf-8")
    steps, note = sq.next_steps([{"path": str(path)}],
                                str(tmp_path / "q_questions.md"), str(tmp_path))
    assert steps == []
    assert "--init" in note


def test_a_second_round_does_not_scaffold_again(tmp_path):
    """Audit finding: --scaffold refuses a task that already exists."""
    path = tmp_path / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "PRICING_VERIFY.yaml").write_text("task_id: PRICING_VERIFY\n",
                                               encoding="utf-8")
    steps, note = sq.next_steps([{"path": str(path)}],
                                str(tmp_path / "q_questions.md"), str(tmp_path))
    assert not any("--scaffold" in s for s in steps)
    assert "already exists" in note


def test_a_path_with_a_space_is_quoted_and_uses_forward_slashes(tmp_path):
    """Audit finding: an unquoted path split into two arguments when pasted."""
    folder = tmp_path / "my proj"
    folder.mkdir()
    path = folder / "pricing.py"
    path.write_text(MODULE, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    steps, _ = sq.next_steps([{"path": str(path)}],
                             str(folder / "q_questions.md"), str(elsewhere))
    assert '"' in steps[0] and "\\" not in steps[0]


def test_task_for_matches_scaffold():
    from qikly.scaffold import VERIFY_SUFFIX

    assert sq.task_for("/x/my-pricing.py") == "MY_PRICING" + VERIFY_SUFFIX


# --------------------------------------------------- written only when ---

def test_no_questions_for_a_suite_qikly_wrote(tmp_path):
    """
    A qikly task already has criteria and `--criteria-from` refuses to add
    more, so a questions file there would end in a command that does nothing.
    """
    from qikly.mutation_score import write

    result = {"task": "CALC_TAX", "baseline": True, "generated": True,
              "caught": [], "unscorable": 0, "total": 1, "unreached": [],
              "missed": [{"file": "a.py", "family": "arithmetic",
                          "change": "guard disabled, line 1"}]}
    write(result, [], str(tmp_path))
    assert not list(tmp_path.glob("*_questions.md"))


def test_no_questions_when_nothing_was_missed(tmp_path):
    from qikly.mutation_score import write

    result = {"task": "pricing.py", "baseline": True, "generated": False,
              "caught": [{"file": "a.py", "family": "arithmetic",
                          "change": "guard disabled, line 1"}],
              "missed": [], "unscorable": 0, "total": 1, "unreached": []}
    write(result, [], str(tmp_path))
    assert not list(tmp_path.glob("*_questions.md"))


# ------------------------------------------------------------ end to end --

def test_score_code_writes_the_questions_and_prints_the_way_on(scored):
    project, done, asked = scored
    assert len(asked) == 1, done.stdout + done.stderr
    assert "questions your tests leave open" in done.stdout
    assert "qikly --scaffold pricing.py" in done.stdout
    assert "\\" not in [l for l in done.stdout.splitlines() if "--criteria-from" in l][0]
    assert "--task-id PRICING_VERIFY" in done.stdout
    report = [p for p in (project / "qikly-suite-score").glob("*.md")
              if p not in asked][0].read_text(encoding="utf-8")
    assert asked[0].name in report


def test_the_printed_steps_produce_a_valid_task_with_the_answers(scored):
    """
    The whole bridge, as a user would cross it, and the regression for the
    placeholder `--criteria-from` used to half remove.
    """
    project, done, asked = scored
    text = asked[0].read_text(encoding="utf-8")
    answers = ["a rate of exactly 100 is accepted and gives a price of 0",
               "a rate of 101 raises ValueError"]
    for answer in answers:
        text = text.replace("\n- \n", "\n- %s\n" % answer, 1)
    asked[0].write_text(text, encoding="utf-8")

    made = _run(["--scaffold", "pricing.py"], str(project))
    assert made.returncode == 0, made.stdout + made.stderr
    filled = _run(["--criteria-from", str(asked[0]), "--task-id",
                   "PRICING_VERIFY"], str(project))
    assert filled.returncode == 0, filled.stdout + filled.stderr

    task_file = project / "inputs_private" / "config" / "tasks" / "PRICING_VERIFY.yaml"
    task = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    assert task["acceptance_criteria"] == answers
    # Nothing of the scaffold's own placeholder survives into the bar.
    assert "101 is rejected" not in task_file.read_text(encoding="utf-8").split(
        "acceptance_criteria:")[-1]


# ------------------------------------------------- audit regressions -------

def test_code_shown_in_the_file_can_never_become_a_criterion(tmp_path):
    """
    Audit finding, the serious one. `--criteria-from` looks for Gherkin first,
    and a dataclass field `example: int = 3` shown as a fenced block read as a
    scenario: the task's criteria became `int = 3:` and the answers were lost.
    """
    path = tmp_path / "sim.py"
    path.write_text("from dataclasses import dataclass\n\n@dataclass\n"
                    "class Cfg:\n    example: int = 3\n    scenario: int = 4\n",
                    encoding="utf-8")
    questions = sq.build([
        {"file": "sim.py", "change": "int 3 -> 4, line 5", "path": str(path)},
        {"file": "sim.py", "change": "int 4 -> 5, line 6", "path": str(path)}])
    text = sq.render("sim.py", questions, ["qikly --scaffold sim.py"])
    assert parse_criteria(text) == []
    answered = text.replace("\n- \n", "\n- the default example count is 3\n", 1)
    assert parse_criteria(answered) == ["the default example count is 3"]


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
        {"file": "pricing.py", "change": "int 0 -> 1, line 2", "path": str(path)}])
    numbers = [q for q in questions if "number is" in q["question"]]
    assert len(numbers) == 1 and "0 or 1" in numbers[0]["question"]


def test_the_file_counts_misses_and_questions_separately():
    text = sq.render("p.py", [{"file": "p.py", "path": None, "line": 1,
                               "function": None, "code": None,
                               "question": "Q?"}], [], "note", misses=3)
    assert "passed 3 deliberate changes" in text and "1 question below" in text


def test_the_file_tells_a_person_not_to_answer_from_the_code():
    text = sq.render("p.py", [], [], "note", misses=0)
    assert "not from what the" in text
