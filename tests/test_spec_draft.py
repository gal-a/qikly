"""
The spec agent: the first draft of a task's answers, written from the
documentation without the code.

What these pin, in order of how much a failure would cost:

- no function body ever reaches the spec agent's prompt, and neither does the
  code a question quotes: a draft read off the code would agree with it by
  construction and find nothing;
- a criterion that claims to quote the documentation and does not is dropped;
- the draft lands in the task file with a note saying where each criterion
  came from, and the drafted criteria are still withheld from the coding agent;
- without a key, or with drafting switched off, --scaffold writes TODOs as it
  did before.
"""
import json
import os

import pytest

from qikly import cli, spec_draft

PRICING = ('def apply_discount(price, rate):\n'
           '    """Apply a percentage discount."""\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n'
           '\n'
           '\n'
           'def label(code):\n'
           '    if code.strip().lower() == "vip":\n'
           '        return "gold"\n'
           '    return "standard"\n')
TESTS = ('from pricing import apply_discount, label\n\n\n'
         'def test_discount():\n    assert apply_discount(100, 10) == 90.0\n\n\n'
         'def test_label():\n    assert label("vip") == "gold"\n')
README = ("# Pricing\n\nA rate of 0 leaves the price as it is. A rate of 100 or more "
          "is rejected with ValueError.\n")
TASK = os.path.join("inputs_private", "config", "tasks", "PRICING_VERIFY.yaml")
BODY_LINES = ["rate < 0 or rate > 100", "round(price * (1 - rate / 100), 2)",
              'raise ValueError("rate out of range")', 'code.strip().lower() == "vip"']


@pytest.fixture
def scored(tmp_path, monkeypatch):
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text(TESTS, encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    assert cli._do_score_suite(None, None, None, code="pricing.py", tests=None) == 0
    return tmp_path


def _drafting(monkeypatch, reply):
    """Drafting switched on, with the model call answered by `reply(prompt)`."""
    from qikly.agent_api.providers import router
    monkeypatch.delenv("QIKLY_NO_DRAFT", raising=False)
    monkeypatch.setattr(router, "validate_config", lambda: "fake")
    seen = []

    def call(mode, prompt, seed=None):
        assert mode == "spec_draft"
        seen.append(prompt)
        return reply(prompt)
    from qikly.agent_api import call_llm
    monkeypatch.setattr(call_llm, "call_llm", call)
    return seen


def _answers(prompt):
    count = sum(1 for line in prompt.split("THE QUESTIONS")[1].splitlines()
                if line[:1].isdigit())
    answers = [{"question": n, "criterion": f"apply_discount(100, {n}) returns 1.0",
                "source": "purpose", "quote": "", "check": True}
               for n in range(1, count + 1)]
    answers[0] = {"question": 1, "criterion": "apply_discount(100, 0) returns 100.0",
                  "source": "docs", "quote": "A rate of 0 leaves the price as it is.",
                  "check": False}
    return json.dumps({"requirements": "Pricing helpers; a rate is a percentage.",
                       "answers": answers})


def test_the_prompt_never_holds_the_code(scored, monkeypatch):
    seen = _drafting(monkeypatch, _answers)
    assert cli._do_scaffold("pricing.py", None) == 0
    (prompt,) = seen
    for line in BODY_LINES:
        assert line not in prompt, line
    # What it may read: the README, the signatures and docstrings.
    assert "A rate of 100 or more is rejected" in prompt
    assert "def apply_discount(price, rate):" in prompt
    assert "Apply a percentage discount." in prompt


def test_a_question_reaches_the_agent_without_the_code_it_quotes():
    q = {"function": "apply_discount",
         "question": "Your tests pass whether this is `rate > 100` or `rate >= 100`, so "
                     "nothing checks the boundary itself. What should happen at exactly `100`?"}
    assert spec_draft.neutral_question(q) == ("In apply_discount: What should happen at "
                                              "exactly 100?")
    q = {"function": "label", "question": "Your tests pass without `.strip()` here. Should "
                                          "two inputs that differ only by spaces be treated the same?"}
    assert "strip" not in spec_draft.neutral_question(q)


def test_the_draft_lands_with_where_each_criterion_came_from(scored, monkeypatch):
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert '- "Pricing helpers; a rate is a percentage."' in text
    assert "TODO: MODIFY THIS" not in text
    assert '#? Drafted from your documentation: "A rate of 0 leaves the price as it is."' in text
    assert '- "apply_discount(100, 0) returns 100.0"' in text
    assert "#? CHECK: drafted from the module's purpose" in text
    criteria_part = text[text.index("acceptance_criteria:"):]
    assert '- "TODO: ' not in criteria_part


def test_an_invented_quote_is_dropped(scored, monkeypatch):
    def reply(prompt):
        data = json.loads(_answers(prompt))
        data["answers"][0]["quote"] = "A rate of 0 is a free gift."
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert "free gift" not in text
    assert '- "apply_discount(100, 0) returns 100.0"' not in text
    assert '- "TODO: ' in text[text.index("acceptance_criteria:"):]


def test_drafted_criteria_never_reach_the_coding_agent(scored, monkeypatch):
    from qikly.agent_api.agent_interface import (_read_task, read_acceptance_criteria,
                                                 without_acceptance_criteria)
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    criteria = read_acceptance_criteria("PRICING_VERIFY")
    assert "apply_discount(100, 0) returns 100.0" in criteria
    handed_over = without_acceptance_criteria(_read_task("PRICING_VERIFY"))
    for criterion in criteria:
        assert criterion not in handed_over
    assert "#?" not in handed_over


def test_without_a_key_or_with_drafting_off_the_answers_are_todos(scored, monkeypatch, capsys):
    # The test suite runs with QIKLY_NO_DRAFT=1 and no key.
    cli._do_scaffold("pricing.py", None)
    criteria_part = (scored / TASK).read_text(encoding="utf-8").split("acceptance_criteria:")[1]
    assert '- "TODO: ' in criteria_part
    os.remove(scored / TASK)
    monkeypatch.delenv("QIKLY_NO_DRAFT", raising=False)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    assert "No API key is set" in capsys.readouterr().out


def test_a_failed_draft_leaves_the_todos(scored, monkeypatch, capsys):
    _drafting(monkeypatch, lambda prompt: "not json")
    assert cli._do_scaffold("pricing.py", None) == 0
    assert "could not be read" in capsys.readouterr().out
    assert '- "TODO: ' in (scored / TASK).read_text(encoding="utf-8")


def test_the_interface_shows_signatures_and_docstrings_only():
    text = spec_draft.interface_text(PRICING)
    assert "def apply_discount(price, rate):" in text
    assert "def label(code):" in text
    for line in BODY_LINES:
        assert line not in text


def test_take_tests_says_who_wrote_each_criterion(scored, monkeypatch):
    from qikly import take_tests
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    criteria = take_tests.criteria_with_origin(str(scored), "PRICING_VERIFY")
    assert criteria[0] == ("apply_discount(100, 0) returns 100.0", "docs")
    assert all(origin == "check" for _, origin in criteria[1:])


def test_the_draft_is_shown_on_screen_check_first(scored, monkeypatch, capsys):
    _drafting(monkeypatch, _answers)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    out = capsys.readouterr().out
    draft = out[out.index("The draft:"):]
    assert draft.index("CHECK  ") < draft.index("docs   apply_discount(100, 0) returns 100.0")
    assert "To run it as it is:  qikly --tasks pricing.py" in out
    assert "To change an answer, edit:" in out


def test_a_dropped_quote_is_counted_and_said(scored, monkeypatch, capsys):
    def reply(prompt):
        data = json.loads(_answers(prompt))
        data["answers"][0]["quote"] = "A rate of 0 is a free gift."
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    assert "1 left as TODO because the quote given for it is not in your documentation" \
        in capsys.readouterr().out


def test_stopping_the_draft_still_writes_the_file(scored, monkeypatch, capsys):
    def reply(prompt):
        raise KeyboardInterrupt
    _drafting(monkeypatch, reply)
    assert cli._do_scaffold("pricing.py", None) == 0
    assert "Drafting stopped" in capsys.readouterr().out
    assert '- "TODO: ' in (scored / TASK).read_text(encoding="utf-8")


def test_a_suite_failing_on_its_own_is_said_to_be_the_setup_not_qikly():
    from qikly import mutation_score as ms
    target = ms.Target("x", [], ["tests"], ".")
    lines = ms.setup_advice(["E   ModuleNotFoundError: No module named 'click'"], target)
    text = "\n".join(lines)
    assert "your project's setup, not qikly" in text
    assert "-m pip install click" in text
    assert "python -m pytest tests" in text
