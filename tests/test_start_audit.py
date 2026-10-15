"""
`qikly --start`, the findings of two reviews before 0.6.0: a Fable audit of
the code, and a fresh first-time user who had only the landing page. Each test
reproduces the reported case.
"""
import os
import subprocess
import sys

import pytest
import yaml

from qikly import cli, start, start_probe
from qikly import start_options as so

PRICING = ('def apply_discount(price, rate):\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n')
TESTS = ('from pricing import apply_discount\n\n\n'
         'def test_discount():\n    assert apply_discount(100, 10) == 90\n')


class Script(object):
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


def _project(tmp_path, source=PRICING, tests=TESTS, name="pricing.py"):
    (tmp_path / name).write_text(source, encoding="utf-8")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / ("test_" + name)).write_text(tests, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------ the first-time user --

def test_deleting_answers_needs_its_own_confirmation(tmp_path):
    """A piped "2" meant for the next question wiped every answer."""
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    q = {"file": "pricing.py", "path": paths.module, "line": 2,
         "function": "apply_discount", "question": "q?", "kind": "guard disabled"}
    start.save_state(paths, {"requirements": "applies a discount", "extra": [],
                             "answers": {start._key(q): {"status": "skip", "question": "q?",
                                                         "where": "w"}}})
    s = Script(["3", "1"])
    with pytest.raises(start.Stop):
        start.module_flow(s.console, paths, [q], [TESTS], str(tmp_path))
    assert "This cannot be undone." in s.text
    assert start.load_state(paths)["answers"], "answers kept after 'no, keep'"


def test_the_test_choice_and_the_score_are_reused(tmp_path, monkeypatch):
    _project(tmp_path)
    calls = []
    real = start.score

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(start, "score", counting)
    code = str(tmp_path / "pricing.py")
    tests = str(tmp_path / "tests")
    session = {}
    first, _ = start._scored(Script([]).console, code, tests, str(tmp_path), session)
    again = start.load_session(str(tmp_path), code)
    second, _ = start._scored(Script([]).console, code, tests, str(tmp_path), again)
    assert len(calls) == 1 and second["total"] == first["total"]
    s = Script(["1"])
    assert start._choose_tests(s.console, code, str(tmp_path), again) == \
        os.path.abspath(tests)
    assert "the same tests as last time" in s.text


def test_a_boundary_on_a_named_constant_with_a_defaulted_argument_is_concrete(tmp_path):
    source = ('THRESHOLD = 50.0\n\n\n'
              'def cost(total, weight, express=False):\n'
              '    if total > THRESHOLD and not express:\n'
              '        return 0.0\n'
              '    return 5.0\n')
    (tmp_path / "ship.py").write_text(source, encoding="utf-8")
    q = {"file": "ship.py", "path": str(tmp_path / "ship.py"), "line": 5,
         "function": "cost", "question": "q?", "edge": "THRESHOLD",
         "kind": "> became >="}
    prompt, options = so.menu(q, source, ["cost(20, 2)\n"], str(tmp_path))
    assert prompt and "THRESHOLD (50.0)" in prompt and "cost(50.0, 2)" in prompt
    assert any("as total 50.01 does now" in o["label"] for o in options)


def test_a_line_outside_any_function_is_labelled_as_such():
    assert start.where({"function": None, "path": "/x/shipping.py", "line": 6}) == \
        "shipping.py, top level, line 6"


def test_a_call_shaped_criterion_is_not_flagged_against_the_interface(tmp_path):
    from qikly import validate
    task = tmp_path / "T.yaml"
    task.write_text(
        'task_id: "T"\nrequirements:\n  - "says how long delivery takes"\n'
        'interface:\n  module: "m"\n  integration_functions:\n'
        '    - "delivery_days(country_code, express=False)"\n'
        '  system_entrypoint: "delivery_days(country_code, express=False)"\n'
        'acceptance_criteria:\n'
        '  - "delivery_days(country_code, express=False) returns 10"\n',
        encoding="utf-8")
    import yaml as y
    raw = task.read_text(encoding="utf-8")
    found = validate._restated_outside_requirements(raw, y.safe_load(raw))
    assert not any("delivery_days(country_code" in line for line, _, _ in found)


# ------------------------------------------------------------- the audit --

def test_two_modules_with_one_file_name_get_two_tasks(tmp_path):
    for sub in ("a", "b"):
        (tmp_path / "lib" / sub).mkdir(parents=True)
        (tmp_path / "lib" / sub / "util.py").write_text("def f(x):\n    return x\n")
    modules = [str(tmp_path / "lib" / s / "util.py") for s in ("a", "b")]
    names = start.task_bases(modules, str(tmp_path / "lib"))
    assert sorted(names.values()) == ["A_UTIL", "B_UTIL"]


def test_answers_for_one_module_never_land_on_another(tmp_path):
    path = tmp_path / "answers.txt"
    path.write_text("module: shop/labels.py\nrequirements: labels\nQ1: x y z\n")
    assert start.parse_answers(str(path))[3] == "shop/labels.py"


def test_a_backslash_in_the_requirements_survives(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    state = {"requirements": r"reads C:\data\prices, matching \d+", "extra": [],
             "answers": {"a": {"status": "answered", "question": "q",
                               "criterion": "apply_discount(1, 2) returns 0.98",
                               "where": "w"}}}
    task = yaml.safe_load(start.task_text(paths, state))
    assert task["requirements"] == [r"reads C:\data\prices, matching \d+"]


def test_the_probe_runs_in_an_empty_folder_not_the_project(tmp_path):
    (tmp_path / "store.py").write_text(
        "def save(name):\n    open(name + '.txt', 'w').write('x')\n    return 1\n")
    assert start_probe.run_calls(str(tmp_path / "store.py"), str(tmp_path),
                                 [("save", ["report"], {})]) == [{"returns": "1"}]
    assert not (tmp_path / "report.txt").exists()


def test_values_travel_as_python_literals(tmp_path):
    (tmp_path / "m.py").write_text(
        "def head(b, n):\n    return b[:n]\n\n"
        "def weigh(pair, scale):\n    return {pair: scale}\n")
    out = start_probe.run_calls(str(tmp_path / "m.py"), str(tmp_path),
                                [("head", [b"abcd", 2], {}),
                                 ("weigh", [(1, 2), 9], {})])
    assert out == [{"returns": "b'ab'"}, {"returns": "{(1, 2): 9}"}]


def test_a_relative_import_inside_a_package_works(tmp_path):
    pkg = tmp_path / "shop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "helpers.py").write_text("def tidy(s):\n    return s.strip()\n")
    (pkg / "labels.py").write_text(
        "from .helpers import tidy\n\ndef label(c):\n    return tidy(c).upper()\n")
    assert start_probe.run_calls(str(pkg / "labels.py"), str(tmp_path),
                                 [("label", [" vip "], {})]) == [{"returns": "'VIP'"}]


@pytest.mark.parametrize("kind", ["<= became <", "int 100 -> 101"])
def test_a_comparison_without_a_recorded_edge_is_never_run_at_the_edge(
        tmp_path, monkeypatch, kind):
    """`if not 0 <= rate <= 100` offered "return 100.0, as your code does now"."""
    source = ('def apply_discount(price, rate):\n'
              '    if not 0 <= rate <= 100:\n'
              '        raise ValueError("bad")\n'
              '    return price\n')
    monkeypatch.setattr(start_probe, "run_calls",
                        lambda *a, **k: pytest.fail("the code was run"))
    q = {"file": "p.py", "path": str(tmp_path / "p.py"), "line": 2,
         "function": "apply_discount", "question": "q?", "edge": None, "kind": kind}
    prompt, options = so.menu(q, source, ["apply_discount(100, 10)\n"],
                              str(tmp_path), mutant=source)
    assert prompt is None and options[-1]["label"] == "type my own answer"


def test_a_crashed_validate_is_an_error_not_ready(tmp_path, monkeypatch):
    class Done(object):
        returncode, stdout, stderr = 1, "", "Traceback ...\nRuntimeError: cannot be stripped"
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: Done())
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    errors, _ = start.validate(Script([]).console, paths)
    assert errors and "cannot be stripped" in errors[0]


def test_a_one_word_criterion_is_refused():
    s = Script(["1", "1", "apply_discount(100, 0) returns 100.0"])
    assert start.own_answer(s.console, "f(1) returns 2") == \
        "apply_discount(100, 0) returns 100.0"
    assert "A criterion needs a few words" in s.text


def test_a_value_prompt_takes_a_bare_number():
    s = Script(["2"])
    assert start.free_text(s.console, "Type what it should return", "1.0",
                           value=True) == "2"


def test_a_rename_writes_a_task_that_names_itself(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    paths.name("PRICING_V2")
    state = {"requirements": "applies a discount", "extra": [],
             "answers": {"a": {"status": "answered", "question": "q", "where": "w",
                               "criterion": "apply_discount(1, 2) returns 0.98"}}}
    task = yaml.safe_load(start.task_text(paths, state))
    assert task["task_id"] == "PRICING_V2_VERIFY"
    assert task["inputs"] == ["inputs_private/data/PRICING_V2/input_01.csv"]
    assert paths.task.endswith("PRICING_V2_VERIFY.yaml")


def test_failing_parametrized_and_class_tests_are_matched(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "integration"
    folder.mkdir(parents=True)
    (folder / "test_integration.py").write_text(
        'import pytest\n\n@pytest.mark.parametrize("r", [100])\n'
        'def test_a(r) -> None:\n    """x\n    # Criteria: 1\n    """\n\n'
        'class TestB:\n    def test_b(self):\n        """y\n        # Criteria: 2\n        """\n')
    state = {"extra": [], "answers": {
        "a": {"status": "answered", "criterion": "c1"},
        "b": {"status": "answered", "criterion": "c2"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/2 passed | FAILED: "
             f"test_a[100], TestB::test_b"]
    disagreed, _, _ = start.disagreements(paths, state, lines)
    assert disagreed == ["c1", "c2"]


def test_stage_two_counts_only_when_stage_one_changed_nothing(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "system"
    folder.mkdir(parents=True)
    (folder / "test_system.py").write_text(
        'def test_s():\n    """z\n    # Criteria: 1\n    """\n')
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    patched = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 1/2 passed | FAILED: test_x",
               f"[{paths.task_id}] [stage 2/3] [iteration 1] 0/1 passed | FAILED: test_s"]
    assert start.disagreements(paths, state, patched)[0] == []
    clean = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 2/2 passed",
             patched[1]]
    assert start.disagreements(paths, state, clean)[0] == ["c1"]


def test_a_module_with_no_public_functions_is_skipped_before_any_question(tmp_path):
    (tmp_path / "hidden.py").write_text("def _limit():\n    return 1\n")
    paths = start.Paths(str(tmp_path), str(tmp_path / "hidden.py"))
    assert start._cannot_task(paths)
    assert not os.path.exists(paths.task)


def test_functions_without_arguments_need_no_sample_file(tmp_path):
    (tmp_path / "settings_mod.py").write_text("def defaults():\n    return 1\n")
    paths = start.Paths(str(tmp_path), str(tmp_path / "settings_mod.py"))
    state = {"answers": {}, "extra": []}
    s = Script([])
    start.ask_data(s.console, paths, state, "def defaults():\n    return 1\n", [])
    assert "take no arguments" in s.text and state["rows"] == [["none"]]


def test_an_existing_task_is_not_asked_about_without_a_terminal(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    os.makedirs(os.path.dirname(paths.task))
    open(paths.task, "w").write("task_id: x\n")
    s = Script([], interactive=False)
    assert start._existing_task(s.console, paths, can_ask=False) is False
    assert not any(str(x).startswith("Type a number") for x in s.seen)


def test_printed_commands_paste_into_git_bash(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    start.write_open_questions(paths, {"answers": {"a": {
        "status": "skip", "question": "q", "where": "w", "number": 1, "key": "abc123"}}})
    text = open(paths.open, encoding="utf-8").read()
    assert "inputs_private/questions/PRICING_open_questions.txt" in text
    assert "# id abc123" in text


def test_an_option_that_asks_for_a_value_can_take_one_from_a_file(tmp_path, monkeypatch):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    q = {"file": "pricing.py", "path": paths.module, "line": 2, "question": "q?",
         "function": "apply_discount"}
    option = {"kind": so.BEHAVIOUR, "call": "apply_discount(100, 0)",
              "args": [100, 0], "kwargs": {}, "function": "apply_discount",
              "pins": {"returns": None, "like": "99.0"}, "label": "x"}
    monkeypatch.setattr(so, "menu", lambda *a, **k: ("p", [option]))
    answers = tmp_path / "a.txt"
    answers.write_text(f"requirements: applies a discount\n# id {start._key(q)}\nQ1: 1: 100.0\n")
    state, _ = start._from_answers(Script([], interactive=False).console, paths, [q],
                                   [TESTS], str(tmp_path), str(answers))
    assert state["answers"][start._key(q)]["criterion"] == \
        "apply_discount(100, 0) returns 100.0"


@pytest.mark.parametrize("bad", ["\x7f", "\x85", "\u2028", "\u2029", "\x00"])
def test_characters_yaml_rejects_are_removed(bad):
    s = Script([f"a{bad}b"])
    assert s.console.ask("x") == "ab"


def test_start_refuses_flags_it_would_ignore(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["qikly", "--start", "pricing.py",
                                      "--task-id", "X", "--fresh"])
    assert cli.main() == 2
    err = capsys.readouterr().err
    assert "--task-id" in err and "--fresh" in err


def test_the_rule_example_comes_from_the_module():
    q = [{"function": "apply_discount"}]
    assert start._rule_example(q, [TESTS]) == "apply_discount(100, 10) returns ..."
