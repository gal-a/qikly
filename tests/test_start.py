"""
The helpers `--score` and `--scaffold` share for code a person already has:
the prompts a slow suite's sample size is chosen with, the tests found for a
module, the rows read from those tests, and the values qikly finds by running
the code beside a question.

The values never read the answer off the code: a boundary is never run at the
value in question, and their order carries no signal.
"""
import sys

import pytest

from qikly import start
from qikly import start_options as so

PRICING = ('def apply_discount(price, rate):\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n\n\n'
           'def label(code):\n'
           '    if code.strip().lower() == "vip":\n'
           '        return "gold"\n'
           '    return "standard"\n')
TESTS = ('from pricing import apply_discount, label\n\n\n'
         'def test_discount():\n    assert apply_discount(100, 10) == 90\n\n\n'
         'def test_label():\n    assert label("vip") == "gold"\n')


class Script(object):
    """A console fed from a list. Running out is end of input."""

    def __init__(self, answers, interactive=True):
        self.answers, self.seen = list(answers), []
        self.console = start.Console(ask=self.ask, say=self.seen.append,
                                     interactive=interactive)

    def ask(self, prompt):
        self.seen.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    @property
    def text(self):
        return "\n".join(str(s) for s in self.seen)


# ------------------------------------------------------------ wrong input --

@pytest.mark.parametrize("typed,expected", [("2", 2), (" 2 ", 2), ("2.", 2), ("2)", 2)])
def test_a_menu_takes_a_number_however_it_is_typed(typed, expected):
    s = Script([typed])
    assert start.choose(s.console, ["a", "b", "c"]) == expected


def test_a_menu_says_why_and_asks_again_and_has_no_default():
    s = Script(["", "9", "yes", "0", "3"])
    assert start.choose(s.console, ["a", "b", "c"]) == 3
    assert "Nothing was chosen. Please type a number from 1 to 3." in s.text
    assert "There is no option 9." in s.text
    assert '"yes" is not one of the numbers.' in s.text
    assert "There is no option 0." in s.text
    assert s.text.count("Type a number from 1 to 3, then press Enter:") == 5


def test_a_long_wrong_answer_is_shortened_visibly():
    s = Script(["apply_discount(100, -5) raises ValueError", "1"])
    start.choose(s.console, ["a", "b"])
    assert '..." is not one of the numbers' in s.text


@pytest.mark.parametrize("typed", ["q", "quit", "exit", "stop"])
def test_quitting_or_running_out_of_input_stops_cleanly(typed):
    with pytest.raises(start.Stop):
        start.choose(Script([typed]).console, ["a"])
    with pytest.raises(start.Stop):
        start.choose(Script([]).console, ["a"])


def test_free_text_refuses_empty():
    s = Script(["", "gemini"])
    assert start.free_text(s.console, "Type it") == "gemini"
    assert "Nothing was typed." in s.text


# ------------------------------------------------- the answer is theirs --

def _question(tmp_path, **extra):
    module = tmp_path / "pricing.py"
    module.write_text(PRICING, encoding="utf-8")
    q = {"file": "pricing.py", "path": str(module), "line": 2,
         "function": "apply_discount", "question": "What at exactly 100?",
         "edge": "100", "kind": "> became >="}
    q.update(extra)
    return q


def test_a_boundary_is_never_run_at_the_value_in_question(tmp_path, monkeypatch):
    seen = []

    def fake(path, root, calls, mutant=None):
        seen.extend(calls)
        return [{"returns": "1.0"}, {"raises": "ValueError"}]

    monkeypatch.setattr(so.start_probe, "run_calls", fake)
    q = _question(tmp_path)
    prompt, options = so.menu(q, PRICING, [TESTS], str(tmp_path))
    rates = [args[1] for _, args, _ in seen]
    assert 100 not in rates and sorted(rates) == [99, 101]
    assert "apply_discount(100, 100)" in prompt
    labels = [o["label"] for o in options]
    assert any("as rate 101 does now" in l for l in labels)
    assert any("as rate 99 does now" in l for l in labels)
    assert labels[-1] == "type my own answer"


def test_the_order_of_the_two_behaviours_comes_from_the_question_not_the_code(
        tmp_path, monkeypatch):
    monkeypatch.setattr(so.start_probe, "run_calls",
                        lambda *a, **k: [{"returns": "1.0"}, {"raises": "ValueError"}])
    orders = set()
    for text in ("one", "two", "three", "four", "five", "six"):
        _, options = so.menu(_question(tmp_path, question=text), PRICING, [TESTS],
                             str(tmp_path))
        orders.add(options[0]["label"].startswith("raise"))
        again = so.menu(_question(tmp_path, question=text), PRICING, [TESTS],
                        str(tmp_path))[1]
        assert [o["label"] for o in again] == [o["label"] for o in options]
    assert orders == {True, False}, "option 1 must not always be one reading"


@pytest.mark.parametrize("kind", ["guard disabled", "raise swallowed"])
def test_where_the_input_cannot_be_known_only_skip_and_own_are_offered(tmp_path, kind):
    prompt, options = so.menu(_question(tmp_path, edge=None, kind=kind), PRICING,
                              [TESTS], str(tmp_path))
    assert prompt is None
    assert [o["label"] for o in options] == ["skip this question for now",
                                             "type my own answer"]


def test_a_difference_is_offered_with_the_current_one_labelled(tmp_path):
    from qikly.mutation import make_mutant
    from qikly import mutation_score as ms
    q = _question(tmp_path, edge=None, line=8, function="label",
                  kind=".lower() dropped", question="Without .lower()?")
    family, index, _ = next(s for s in ms.sites(PRICING) if ".lower()" in s[2])
    mutant = make_mutant(PRICING, index, family)[0]
    prompt, options = so.menu(q, PRICING, [TESTS], str(tmp_path), mutant)
    assert prompt.startswith("What should label(")
    labels = [o["label"] for o in options[:2]]
    assert sum("as your code does now" in l for l in labels) == 1


# ------------------------------------------------------- what is written --


def test_rows_are_built_from_typed_answers_and_test_calls():
    state = {"answers": {"a": {"status": "answered",
                               "criterion": "apply_discount(100, 0) returns 100.0"}},
             "extra": ["label(' vip ') returns 'gold'"]}
    rows = start.build_rows(state, ["price", "rate", "code"], PRICING, [TESTS])
    assert ["100", "0", "vip"] in rows
    assert ["100", "10", " vip "] in rows


# ------------------------------------------------------- the whole flow --


def test_a_folder_beside_its_tests_finds_them_without_a_project_marker(tmp_path):
    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "__init__.py").write_text("", encoding="utf-8")
    (shop / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_shop.py").write_text(
        "from shop.pricing import apply_discount\n\ndef test_a():\n"
        "    assert apply_discount(100, 10) == 90\n", encoding="utf-8")
    assert start.auto_tests(str(shop), str(tmp_path)) == str(tmp_path / "tests" / "test_shop.py")


# -------------------------------------------------------------- the flags --


def test_the_interactive_variable_forces_prompts_for_a_terminal_python_cannot_see(monkeypatch):
    """Git Bash's window is not a console to Python, but input() works there."""
    monkeypatch.setenv("QIKLY_INTERACTIVE", "1")
    assert start.is_terminal() is True
    monkeypatch.setenv("QIKLY_INTERACTIVE", "")
    monkeypatch.setattr(sys, "stdin", None)
    assert start.is_terminal() is False


# ------------------------------------- the answers file, the sixth audit --


