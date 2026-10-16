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
    s = Script([])
    assert start._choose_tests(s.console, code, str(tmp_path), again) == \
        os.path.abspath(tests)
    assert "as you chose last time" in s.text, "reused without asking"


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
    # Both sides return a value here, so one option shows both neighbours.
    assert any("total 49.99 returns 5.0 now" in o["label"]
               and "total 50.01 returns 0.0" in o["label"] for o in options)
    assert sum(o["kind"] == so.BEHAVIOUR for o in options) == 1


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
    disagreed, _, _, _, _ = start.disagreements(paths, state, lines)
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


# ------------------------------------------------- the eight-project matrix --

def test_calls_through_an_import_alias_are_found_for_the_right_module():
    """`from lib.a.util import scale as a_scale` hid every call from the menus."""
    tests = ("from lib.a.util import scale as a_scale\n"
             "from lib.b.util import scale as b_scale\n\n"
             "def test_a():\n    assert a_scale(2) == 4\n\n"
             "def test_b():\n    assert b_scale(7) == 21\n")
    assert so.literal_calls([tests], "scale", "lib.a.util") == [([2], {})]
    assert so.literal_calls([tests], "scale", "lib.b.util") == [([7], {})]


def test_a_src_layout_package_can_be_probed(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n")
    pkg = tmp_path / "src" / "acme"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "util.py").write_text("def clamp(v, lo, hi):\n    return max(lo, min(hi, v))\n")
    (pkg / "scoring.py").write_text("from .util import clamp\n\ndef grade(p):\n"
                                    "    return clamp(p, 0, 100)\n")
    assert start_probe.run_calls(str(pkg / "scoring.py"), str(tmp_path),
                                 [("grade", [150], {})]) == [{"returns": "100"}]


def test_a_module_in_a_package_seeds_the_whole_package(tmp_path):
    """A one-file seed lost `from .util import clamp`, so no test ran on the code."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n")
    pkg = tmp_path / "src" / "acme"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "util.py").write_text("def clamp(v, lo, hi):\n    return max(lo, min(hi, v))\n")
    (pkg / "scoring.py").write_text("from .util import clamp\n\ndef grade(p):\n"
                                    "    return clamp(p, 0, 100)\n")
    paths = start.Paths(str(tmp_path), str(pkg / "scoring.py"))
    state = {"requirements": "grades", "extra": [], "answers": {"a": {
        "status": "answered", "criterion": "grade(150) returns 100", "question": "q",
        "where": "w"}}}
    task = yaml.safe_load(start.task_text(paths, state))
    assert task["interface"]["module"] == "acme.scoring"
    assert task["seed"]["implementation"] == "src/acme"


def test_a_first_iteration_that_ran_nothing_is_not_agreement(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] no test ran: the module "
             f"could not be imported",
             f"[{paths.task_id}] [stage 1/3] [iteration 2] 1/1 passed"]
    assert start.disagreements(paths, state, lines)[0] == "unknown"
    s = Script([])
    start.report_result(s.console, paths, state, lines, True)
    assert "cannot say where your code and your answers disagree" in s.text
    assert "agrees" not in s.text


def test_a_boundary_between_two_categories_offers_both(tmp_path):
    source = 'def grade(p):\n    if p >= 90:\n        return "A"\n    return "B"\n'
    (tmp_path / "g.py").write_text(source)
    q = {"file": "g.py", "path": str(tmp_path / "g.py"), "line": 2, "function": "grade",
         "question": "q?", "edge": "90", "kind": ">= became >"}
    prompt, options = so.menu(q, source, ["grade(95)\n"], str(tmp_path))
    labels = [o["label"] for o in options]
    assert "return 'B', as p 89 does now" in labels
    assert "return 'A', as p 91 does now" in labels
    chosen = next(o for o in options if o["label"].startswith("return 'A'"))
    assert so.criterion(chosen) == "grade(90) returns 'A'"


def test_only_the_tasks_the_run_names_are_reported_as_failed():
    lines = ["...", "Task(s) failed: COUPONS_VERIFY"]
    assert start._failed_tasks(lines, ["CART_VERIFY", "COUPONS_VERIFY"], False) == \
        {"COUPONS_VERIFY"}
    assert start._failed_tasks(["boom"], ["A", "B"], False) == {"A", "B"}
    assert start._failed_tasks(lines, ["A"], True) == set()


def test_an_answer_is_listed_only_against_tests_that_make_its_call():
    """A free-shipping answer was listed against two express-delivery tests."""
    express = "def t():\n    cost = shipping_cost(50.0, 2, express=True)\n    assert cost\n"
    exact = "def t():\n    assert shipping_cost(50.0, 2) == 0.0\n"
    call = ("shipping_cost", [50.0, 2], {})
    assert not start._makes_call(express, call)
    assert start._makes_call(exact, call)


def test_a_default_passed_explicitly_is_the_same_call():
    source = "def shipping_cost(order_total, weight_kg, express=False):\n    return 0.0\n"
    body = "def t():\n    assert shipping_cost(50.0, weight_kg=2, express=False) == 0.0\n"
    assert start._makes_call(body, ("shipping_cost", [50.0, 2], {}), source)


def test_a_tag_without_a_hash_still_links_the_test(tmp_path):
    """'Criteria: 2' in a docstring was linked to nothing, and a real
    disagreement was reported as agreement."""
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "integration"
    folder.mkdir(parents=True)
    (folder / "test_integration.py").write_text(
        'def test_upper():\n    """rate 100 raises.\n\n    Criteria: 2\n    """\n'
        '    try:\n        apply_discount(100, 100)\n        assert False\n'
        '    except ValueError:\n        pass\n    # Criteria: 2\n')
    state = {"extra": [], "answers": {
        "a": {"status": "answered", "criterion": "apply_discount(100, 0) returns 100.0"},
        "b": {"status": "answered", "criterion": "apply_discount(100, 100) raises ValueError"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_upper"]
    assert start.disagreements(paths, state, lines)[0] == \
        ["apply_discount(100, 100) raises ValueError"]


def test_a_failure_with_no_tag_is_still_reported(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_odd"]
    s = Script([])
    start.report_result(s.console, paths, state, lines, True)
    assert "test_odd" in s.text and "agrees" not in s.text


def test_start_takes_its_tests_from_score_tests(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setattr(start, "main",
                        lambda path, cwd, answers=None, tests=None: seen.update(tests=tests) or 0)
    monkeypatch.setattr(sys, "argv", ["qikly", "--start", "pricing.py",
                                      "--score-tests", "tests/"])
    assert cli.main() == 0 and seen["tests"] == "tests/"


def test_code_with_no_tests_gets_questions_about_every_fault(tmp_path, monkeypatch):
    (tmp_path / "pricing.py").write_text(PRICING)
    monkeypatch.chdir(tmp_path)
    s = Script([])
    suite = start.no_tests_suite(s.console, str(tmp_path / "pricing.py"), str(tmp_path))
    assert start.is_placeholder(suite, str(tmp_path))
    assert "qikly-suite-score" in suite and not (tmp_path / "tests").exists()
    result, _ = start.score(s.console, str(tmp_path / "pricing.py"), suite,
                            str(tmp_path), False)
    assert result and result["total"] and not result["caught"]


# ---------------------------------------------- second audit, 2026-10-15 --

def _tagged_project(tmp_path, body):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "integration"
    folder.mkdir(parents=True)
    (folder / "test_integration.py").write_text(body)
    return paths


def test_a_failure_tagged_beyond_the_answers_is_still_reported(tmp_path):
    paths = _tagged_project(tmp_path, 'def test_x():\n    """# Criteria: 3"""\n')
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_x"]
    _, _, _, untagged, _ = start.disagreements(paths, state, lines)
    assert untagged == ["test_x"]


def test_a_failing_stage_without_names_is_never_agreement(tmp_path):
    paths = _tagged_project(tmp_path, 'def test_x():\n    pass\n')
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    for tail in ("1/2 passed | FAILED: ", "0 passed, 1 failed"):
        lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] {tail}"]
        s = Script([])
        start.report_result(s.console, paths, state, lines, True)
        assert "agrees" not in s.text and "did not name" in s.text, tail


def test_a_tag_above_the_next_test_belongs_to_that_test(tmp_path):
    body = ('def test_a():\n    assert True\n\n# Criteria: 1\ndef test_b():\n'
            '    """b"""\n    assert True\n')
    paths = _tagged_project(tmp_path, body)
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 1/2 passed | FAILED: test_a"]
    disagreed, _, _, untagged, _ = start.disagreements(paths, state, lines)
    assert disagreed == [] and untagged == ["test_a"]


def test_same_named_methods_in_two_classes_stay_apart(tmp_path):
    body = ('class TestHigh:\n    def test_edge(self):\n        """# Criteria: 1"""\n\n'
            'class TestLow:\n    def test_edge(self):\n        """# Criteria: 2"""\n')
    paths = _tagged_project(tmp_path, body)
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "high"},
                                      "b": {"status": "answered", "criterion": "low"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 1/2 passed | FAILED: TestHigh::test_edge"]
    assert start.disagreements(paths, state, lines)[0] == ["high"]


def test_a_package_named_like_the_standard_library_stays_a_file_seed(tmp_path):
    pkg = tmp_path / "code"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "pricing.py").write_text(PRICING)
    paths = start.Paths(str(tmp_path), str(pkg / "pricing.py"))
    state = {"requirements": "r", "extra": [], "answers": {"a": {
        "status": "answered", "criterion": "apply_discount(1, 2) returns 0.98",
        "question": "q", "where": "w"}}}
    task = yaml.safe_load(start.task_text(paths, state))
    assert task["seed"]["implementation"].endswith("pricing.py")


def test_the_placeholder_leaves_out_main_and_unimportable_modules(tmp_path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text("import sys\nsys.exit(2)\n")
    (pkg / "broken.py").write_text("import nonexistent_module_xyz\n")
    (pkg / "rules.py").write_text("def f(x):\n    return x\n")
    s = Script([])
    path = start.no_tests_suite(s.console, str(pkg), str(tmp_path))
    text = open(path).read()
    assert "app.rules" in text and "__main__" not in text and "broken" not in text
    assert "left out" in s.text


def test_decimal_neighbours_are_typed_not_pinned(tmp_path, monkeypatch):
    source = ("from decimal import Decimal\n\ndef fee(amount):\n"
              "    if amount >= 100:\n        return Decimal('9.9')\n"
              "    return Decimal('0')\n")
    (tmp_path / "f.py").write_text(source)
    q = {"file": "f.py", "path": str(tmp_path / "f.py"), "line": 4, "function": "fee",
         "question": "q?", "edge": "100", "kind": ">= became >"}
    _, options = so.menu(q, source, ["fee(50)\n"], str(tmp_path))
    behaviours = [o for o in options if o["kind"] == so.BEHAVIOUR]
    assert len(behaviours) == 1 and behaviours[0]["pins"]["returns"] is None


def test_take_tests_and_start_together_are_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["qikly", "--start", "p.py", "--take-tests", "X"])
    assert cli.main() == 2
    assert "separate steps" in capsys.readouterr().err


def test_score_code_finds_the_tests_when_none_are_named(tmp_path, monkeypatch, capsys):
    _project(tmp_path)
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    found = {}
    import qikly.mutation_score as ms
    monkeypatch.setattr(ms, "from_paths", lambda code, tests: found.update(tests=tests)
                        or (_ for _ in ()).throw(ValueError("stop here")))
    cli._do_score_suite(None, None, None, code="pricing.py", tests=None)
    out = capsys.readouterr()
    assert found["tests"].endswith(os.path.join("tests", "test_pricing.py"))
    assert "the test files that import it" in out.out


def test_score_code_says_how_to_name_tests_when_none_import_it(tmp_path, monkeypatch, capsys):
    (tmp_path / "pricing.py").write_text(PRICING)
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_score_suite(None, None, None, code="pricing.py", tests=None) == 2
    assert "--score-tests" in capsys.readouterr().err


# ------------------------------------------- real libraries, 2026-10-16 --

def test_a_package_whose_code_is_its_init_is_scored_and_named(tmp_path):
    """tabulate and inflection keep the whole library in __init__.py."""
    pkg = tmp_path / "inflection"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def pluralize(word):\n    return word + 's'\n")
    (tmp_path / "test_inflection.py").write_text(
        "import inflection\n\ndef test_p():\n    assert inflection.pluralize('a') == 'as'\n")
    import qikly.mutation_score as ms
    from qikly import score_questions
    assert str(pkg / "__init__.py") in start.modules_in(str(pkg))
    assert "inflection" in start.import_names(str(pkg))
    assert start.auto_tests(str(pkg), str(tmp_path)).endswith("test_inflection.py")
    target = ms.from_paths(str(pkg), str(tmp_path / "test_inflection.py"))
    assert any(p.endswith("__init__.py") for p, _ in target.files)
    assert score_questions.task_for(str(pkg / "__init__.py")) == "INFLECTION_VERIFY"
    assert start_probe.dotted_name(str(pkg / "__init__.py"), str(tmp_path)) == "inflection"


def test_a_module_gets_its_own_tests_before_the_whole_package(tmp_path):
    """validators' tests all import validators; card.py's are test_card.py."""
    pkg = tmp_path / "src" / "validators"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .card import card_number\n")
    (pkg / "card.py").write_text("def card_number(v):\n    return v.isdigit()\n")
    (pkg / "email.py").write_text("def email(v):\n    return '@' in v\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_card.py").write_text("from validators import card_number\n")
    (tests / "test_email.py").write_text("from validators import email\n")
    (tmp_path / "pyproject.toml").write_text("")
    picked = start.importing_tests(str(pkg / "card.py"), str(tmp_path))
    assert [os.path.basename(p) for p in picked] == ["test_card.py"]
    whole = start.importing_tests(str(pkg), str(tmp_path))
    assert len(whole) == 2


def test_an_input_passed_through_a_variable_is_found():
    tests = "def test_a():\n    txt = 'Hello World'\n    assert slugify(txt) == 'hello-world'\n"
    assert so.literal_calls([tests], "slugify") == [(["Hello World"], {})]
    twice = "def test_b():\n    t = 'a'\n    t = 'b'\n    slugify(t)\n"
    assert so.literal_calls([twice], "slugify") == []


def test_a_slow_suite_is_sampled_without_a_terminal(tmp_path, monkeypatch):
    import time as real_time
    clock = iter([0.0, 20.0])
    monkeypatch.setattr(real_time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: None)
    s = Script([], interactive=False)
    assert start._fit_to_time(s.console, "tests", str(tmp_path), 150) == 15
    assert "about 50 minutes" in s.text


def test_scoring_prints_a_heartbeat(tmp_path, monkeypatch, capsys):
    """A slow suite ran for over an hour on a real library with nothing on screen."""
    import qikly.mutation_score as ms
    monkeypatch.setattr(ms, "HEARTBEAT_SECONDS", 0)
    (tmp_path / "pricing.py").write_text(PRICING)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text(TESTS)
    ms.score(ms.from_paths(str(tmp_path / "pricing.py"), str(tmp_path / "tests")),
             mutants=4, seed=1)
    assert "still scoring:" in capsys.readouterr().out


def test_parametrize_rows_give_the_call_its_arguments():
    # Real suites pass inputs through parametrize, often from a module-level
    # table; before this, inflection and slugify offered no concrete calls.
    test = (
        "import pytest\n"
        "from shop import price\n"
        "ROWS: list = [(3, 30), (4, 40)]\n"
        "@pytest.mark.parametrize(('qty', 'total'), ROWS)\n"
        "def test_price(qty, total):\n"
        "    assert price(qty) == total\n"
        "@pytest.mark.parametrize('word', ['a b'])\n"
        "def test_inline(word):\n"
        "    assert price(word)\n"
    )
    calls = so.literal_calls([test], "price", "shop")
    assert ([3], {}) in calls
    assert (["a b"], {}) in calls


def test_the_same_question_on_many_lines_is_asked_once():
    # inflection's table of 37 regexes all missing an anchor asked one
    # question 37 times; public functions now come before private helpers.
    q = "Your tests pass when this pattern matches only part of a value?"
    questions = [{"path": "m.py", "function": None, "line": n, "question": q}
                 for n in (22, 23, 24)]
    questions.insert(0, {"path": "m.py", "function": "_helper", "line": 5,
                         "question": "Private?"})
    questions.append({"path": "m.py", "function": "titleize", "line": 90,
                      "question": "Public?"})
    grouped = start.group(questions)
    assert [g["question"] for g in grouped] == ["Public?", q, "Private?"]
    assert grouped[1]["also"] == [23, 24]
    assert start.where(grouped[1]) == "m.py, top level, line 22 (and 2 more lines like it: 23, 24)"


def test_a_test_importing_a_name_the_module_lacks_is_not_a_disagreement(tmp_path):
    # validators' card.py met the answer, but the test imported ValidationError
    # from card.py, which does not have it, and the report said "disagrees".
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "system"
    folder.mkdir(parents=True)
    (folder / "test_system.py").write_text(
        'def test_s():\n    """z\n    # Criteria: 1\n    """\n'
        '    from pricing import apply_discount, NoSuchError\n'
        '    assert apply_discount(1, 2)\n')
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_s"]
    disagreed, _, _, untagged, unchecked = start.disagreements(paths, state, lines)
    assert disagreed == [] and untagged == []
    assert unchecked == {"test_s": ["NoSuchError"]}


def test_a_folder_of_one_module_is_that_module_with_or_without_a_terminal(tmp_path):
    # inflection's code is its __init__.py: a terminal run tested the module
    # and a run without one the folder, each with its own questions.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    assert start._one_module(str(pkg)) == str(pkg / "__init__.py")
    s = Script(["1"])
    assert start.pick_code(s.console, "pkg", str(tmp_path)) == str(pkg / "__init__.py")


def test_a_call_through_a_variable_is_the_answers_call():
    body = ('def test_p():\n    word = "mousetrap"\n'
            '    assert pluralize(word) == "mousetraps"\n')
    assert start._makes_call(body, ("pluralize", ["mousetrap"], {}))
    assert not start._makes_call(body, ("pluralize", ["cowboy"], {}))
