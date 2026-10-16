"""
`qikly --start`, the findings of two reviews before 0.6.0: a Fable audit of
the code, and a fresh first-time user who had only the landing page. Each test
reproduces the reported case.
"""
import os
import re
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


def test_the_score_is_reused(tmp_path, monkeypatch):
    _project(tmp_path)
    calls = []
    real = start.score

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(start, "score", counting)
    code = str(tmp_path / "pricing.py")
    tests = str(tmp_path / "tests")
    first, _ = start._scored(Script([]).console, code, tests, str(tmp_path), {})
    again = start.load_session(str(tmp_path), code)
    second, _ = start._scored(Script([]).console, code, tests, str(tmp_path), again)
    assert len(calls) == 1 and second["total"] == first["total"]


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


def test_an_existing_task_this_command_did_not_write_is_left_alone(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    os.makedirs(os.path.dirname(paths.task))
    open(paths.task, "w").write("task_id: x\n")
    s = Script([])
    assert start._existing_task(s.console, paths) is False
    assert "left alone" in s.text and not any(str(x).startswith("Type a number") for x in s.seen)


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


def test_a_folder_of_one_module_is_that_module(tmp_path):
    # inflection's code is its __init__.py.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    assert start._one_module(str(pkg)) == str(pkg / "__init__.py")


def test_a_call_through_a_variable_is_the_answers_call():
    body = ('def test_p():\n    word = "mousetrap"\n'
            '    assert pluralize(word) == "mousetraps"\n')
    assert start._makes_call(body, ("pluralize", ["mousetrap"], {}))
    assert not start._makes_call(body, ("pluralize", ["cowboy"], {}))


def test_a_row_with_an_object_in_it_still_gives_its_plain_values():
    # isodate's rows hold date(...) beside the strings; reading the whole
    # table as one literal threw out every row.
    test = (
        "import pytest\n"
        "from datetime import date\n"
        "from isodate import parse_date\n"
        "CASES = [(4, '1985-04', date(1985, 4, 1)), (6, '+0019', None)]\n"
        "@pytest.mark.parametrize('yeardigits, datestring, expected', CASES)\n"
        "def test_parse(yeardigits, datestring, expected):\n"
        "    assert parse_date(datestring, yeardigits) == expected\n"
        "@pytest.mark.parametrize('s', [pytest.param('abc', id='x')])\n"
        "def test_param(s):\n"
        "    assert parse_date(s)\n"
    )
    # And by the package's name: the function lives in isodate.isodates.
    calls = so.literal_calls([test], "parse_date", "src.isodate.isodates")
    assert (["1985-04", 4], {}) in calls
    assert (["abc"], {}) in calls


# ------------------------------------------ the third audit, 2026-10-16 --

def _system_test(tmp_path, paths, body):
    folder = tmp_path / "outputs" / "tests" / paths.task_id / "system"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "test_system.py").write_text(body, encoding="utf-8")


def test_a_name_defined_under_an_if_is_not_missing(tmp_path):
    # Counting only top-level statements took this apply_discount as missing
    # and hid the one failure that was a real disagreement.
    source = ("import sys\nif sys.version_info >= (3,):\n"
              "    def apply_discount(price, rate):\n        return 90\n")
    _project(tmp_path, source=source)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    _system_test(tmp_path, paths,
                 'def test_s():\n    """z\n    # Criteria: 1\n    """\n'
                 '    from pricing import apply_discount\n'
                 '    assert apply_discount(100, 5) == 95\n')
    state = {"extra": [], "answers": {"a": {"status": "answered", "criterion": "c1"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_s"]
    disagreed, _, _, _, unchecked = start.disagreements(paths, state, lines)
    assert disagreed == ["c1"] and unchecked == {}


def test_a_module_getattr_means_nothing_is_called_missing(tmp_path):
    source = "def __getattr__(name):\n    return 1\n"
    _project(tmp_path, source=source)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    assert start._missing_imports("from pricing import anything\n", paths, source) == []


def test_agreement_is_never_claimed_for_an_answer_no_test_checked(tmp_path):
    _project(tmp_path)
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    _system_test(tmp_path, paths,
                 'def test_s():\n    """z\n    # Criteria: 1\n    """\n'
                 '    from pricing import apply_discount, NoSuchError\n'
                 '    assert apply_discount(1, 2)\n')
    state = {"extra": [], "answers": {
        "a": {"status": "answered", "criterion": "apply_discount(1, 2) returns 0.98"},
        "b": {"status": "answered", "criterion": "apply_discount(5, 0) returns 5"}}}
    lines = [f"[{paths.task_id}] [stage 1/3] [iteration 1] 0/1 passed | FAILED: test_s",
             f"[{paths.task_id}] [stage 1/3] [iteration 2] 1/1 passed"]
    s = Script([])
    start.report_result(s.console, paths, state, lines, True)
    assert "agrees with all" not in s.text and "agrees with your answer" not in s.text
    assert "No test that ran on your code checked any of your answers" in s.text
    assert "Not checked by any test" in s.text and "imports NoSuchError" in s.text


def test_two_different_guards_in_one_function_stay_two_questions(tmp_path):
    source = ("def apply_discount(price, rate):\n"
              "    if price < 0:\n        raise ValueError('price')\n"
              "    if rate > 1:\n        raise ValueError('rate')\n"
              "    return price * (1 - rate)\n")
    (tmp_path / "m.py").write_text(source, encoding="utf-8")
    path = str(tmp_path / "m.py")
    q = "Your tests pass with this check switched off. Which input?"
    questions = [{"path": path, "function": "apply_discount", "line": n, "question": q}
                 for n in (2, 4)]
    assert len(start.group(questions)) == 2


def test_rows_in_an_answers_file_keep_the_answers_own_calls(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert start.main("pricing.py", str(tmp_path),
                      console=Script([], interactive=False).console) == start.NEEDS_ANSWERS
    answers = tmp_path / "inputs_private" / "questions" / "PRICING_open_questions.txt"
    text = answers.read_text(encoding="utf-8")
    text = re.sub(r"^requirements:.*$", "requirements: applies a discount", text, flags=re.M)
    text = re.sub(r"^Q1:.*$", "Q1: apply_discount(7, 50) returns 3.5 exactly", text, flags=re.M)
    answers.write_text(text, encoding="utf-8")
    start.main("pricing.py", str(tmp_path), console=Script([], interactive=False).console,
               answers=str(answers))
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    assert ["7", "50"] in start.load_state(paths)["rows"]


def test_a_value_bound_more_than_one_way_is_not_used():
    test = ("from m import slugify\n"
            "def test_aug():\n    txt = 'a'\n    txt += ' b'\n    slugify(txt)\n"
            "def test_loop():\n    for txt in ['a', 'b']:\n        slugify(txt)\n"
            "def test_tuple():\n    txt, n = 'a', 1\n    slugify(txt)\n"
            "def test_late():\n    slugify(txt)\n    txt = 'late'\n"
            "def test_plain():\n    txt = 'plain'\n    slugify(txt)\n")
    assert so.literal_calls([test], "slugify", "m") == [(["plain"], {})]


def test_indirect_parametrize_is_not_read_as_the_call():
    test = ("import pytest\nfrom m import slugify\n"
            "@pytest.mark.parametrize('txt', ['raw'], indirect=True)\n"
            "def test_i(txt):\n    slugify(txt)\n")
    assert so.literal_calls([test], "slugify", "m") == []


def test_a_stdlib_dotted_import_is_not_an_import_of_the_project(tmp_path):
    (tmp_path / "src" / "geo").mkdir(parents=True)
    (tmp_path / "src" / "geo" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "geo" / "path.py").write_text("def f(x):\n    return x\n",
                                                     encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_io.py").write_text("import os.path\n\ndef test_a():\n"
                                                  "    assert os.path\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    found = start.importing_tests(str(tmp_path / "src" / "geo" / "path.py"), str(tmp_path))
    assert not found


def test_a_sample_is_never_bigger_than_the_whole(monkeypatch):
    # 40 seconds a run and 10 faults offered "a sample of 12 instead".
    import time
    clock = iter([0.0, 40.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: None)
    s = Script([], interactive=False)
    assert start._fit_to_time(s.console, "tests", ".", 10) == 10
    assert "sample of" not in s.text and "all 10 are planted" in s.text


def test_main_py_is_not_a_module_to_test(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (pkg / "__main__.py").write_text("print('hi')\n", encoding="utf-8")
    assert start._one_module(str(pkg)) == str(pkg / "__init__.py")


def test_a_fault_that_hangs_is_stopped_and_counted_caught(tmp_path, monkeypatch):
    # cachetools' scoring stopped for good on a fault that looped forever.
    import qikly.mutation_score as ms
    monkeypatch.setattr(ms, "FAULT_TIMEOUT_FLOOR", 3.0)
    (tmp_path / "counter.py").write_text(
        "def count(n):\n    i = 0\n    while i != n:\n        i += 1\n    return i\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_counter.py").write_text(
        "from counter import count\n\ndef test_count():\n    assert count(3) == 3\n")
    result = ms.score(ms.from_paths(str(tmp_path / "counter.py"), str(tmp_path / "tests")),
                      mutants=50, seed=1)
    assert result["timed_out"] >= 1
    assert "counted as caught" in ms.render(result, [])


# ------------------------------------- the cap and answers through public calls --


def test_a_helper_reached_only_through_a_public_function_gets_options(tmp_path):
    # On real libraries most missed faults sat in private helpers that tests
    # reach only through public functions, and no question offered an answer.
    from qikly.mutation import count_sites, make_mutant
    source = ("def _check(rate):\n"
              "    if not isinstance(rate, int):\n"
              "        raise TypeError('rate must be a whole number')\n"
              "    return rate\n\n\n"
              "def apply(price, rate):\n"
              "    return price - _check(rate)\n")
    (tmp_path / "shop.py").write_text(source, encoding="utf-8")
    tests = "from shop import apply\n\ndef test_apply():\n    assert apply(100, 5) == 95\n"
    mutant = next(m for m, d in (make_mutant(source, i, "validation")
                                 for i in range(count_sites(source, "validation")))
                  if d.startswith("guard disabled"))
    q = {"path": str(tmp_path / "shop.py"), "line": 2, "function": "_check",
         "kind": "guard disabled", "question": "Your tests pass with this check "
         "switched off. Which input, if any, should it catch?"}
    prompt, options = so.menu(q, source, [tests], str(tmp_path), mutant)
    assert prompt and prompt.startswith("What should apply(") and "runs through _check" in prompt
    labels = [o["label"] for o in options]
    assert any(l.startswith("raise TypeError") and "as your code does now" in l for l in labels)
    assert labels[-1] == "type my own answer"


def test_every_parametrize_row_is_a_call_and_a_default_is_tried_left_out():
    test = ("import pytest\nfrom m import parse\n"
            "ROWS = [(4, '1985'), (6, '+001985')]\n"
            "@pytest.mark.parametrize('digits, text', ROWS)\n"
            "def test_p(digits, text):\n    assert parse(text, digits)\n")
    calls = so.literal_calls([test], "parse", "m")
    assert (["1985", 4], {}) in calls and (["+001985", 6], {}) in calls
    source = "def parse(text, digits=4):\n    return text\n"
    candidates = so._candidates(source, [test], "parse", "m", 60)
    assert (["1985"], {}) in candidates


def test_a_module_its_package_imports_back_can_be_probed(tmp_path):
    # isodate's __init__ imports from isodates, which imports isodate.isoerror:
    # loaded on its own, the module met itself half-built and every probe of
    # it failed, so no question about it ever offered an answer.
    pkg = tmp_path / "src" / "iso"
    pkg.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='iso'\n")
    (pkg / "__init__.py").write_text("from iso.dates import parse\n")
    (pkg / "errors.py").write_text("class ParseError(ValueError):\n    pass\n")
    (pkg / "dates.py").write_text("from iso.errors import ParseError\n\n"
                                  "def parse(text):\n    if not text:\n"
                                  "        raise ParseError(text)\n    return text[::-1]\n")
    assert start_probe.run_calls(str(pkg / "dates.py"), str(tmp_path),
                                 [("parse", ["ab"], {}), ("parse", [""], {})]) == \
        [{"returns": "'ba'"}, {"raises": "ParseError"}]


def test_a_class_built_by_the_tests_reaches_a_fault_in_its_methods(tmp_path):
    # semantic_version's tests build Version('1.0.0'); every question about
    # its parsing was text-only before classes could be called.
    from qikly.mutation import count_sites, make_mutant
    source = ("class Version:\n"
              "    def __init__(self, text):\n"
              "        self.parts = self._parse(text)\n\n"
              "    def _parse(self, text):\n"
              "        if not text[0].isdigit():\n"
              "            raise ValueError(text)\n"
              "        return tuple(int(p) for p in text.split('.'))\n\n"
              "    def __repr__(self):\n"
              "        return 'Version(%r)' % ('.'.join(map(str, self.parts)),)\n")
    (tmp_path / "semver.py").write_text(source, encoding="utf-8")
    tests = "from semver import Version\n\ndef test_v():\n    assert Version('1.2')\n"
    mutant = next(m for m, d in (make_mutant(source, i, "validation")
                                 for i in range(count_sites(source, "validation")))
                  if d.startswith("guard disabled"))
    q = {"path": str(tmp_path / "semver.py"), "line": 6, "function": "_parse",
         "kind": "guard disabled", "question": "Your tests pass with this check "
         "switched off. Which input, if any, should it catch?"}
    prompt, options = so.menu(q, source, [tests], str(tmp_path), mutant)
    assert prompt and prompt.startswith("What should Version(")
    assert any(o["label"].startswith("raise ValueError") for o in options)


# ------------------------------------------- the fourth audit, 2026-10-16 --

def _guard_mutant(source):
    from qikly.mutation import count_sites, make_mutant
    return next(m for m, d in (make_mutant(source, i, "validation")
                               for i in range(count_sites(source, "validation")))
                if d.startswith("guard disabled"))


def test_a_random_public_call_is_never_offered_as_a_difference(tmp_path):
    # A uuid differs on every run; offered, it saved a criterion that never holds.
    source = ("import uuid\n\n"
              "def _check(rate):\n"
              "    if not isinstance(rate, int):\n"
              "        raise TypeError('rate')\n"
              "    return rate\n\n\n"
              "def make_id(prefix):\n"
              "    return prefix + '-' + uuid.uuid4().hex\n")
    (tmp_path / "shop.py").write_text(source, encoding="utf-8")
    tests = "from shop import make_id\n\ndef test_id():\n    assert make_id('a')\n"
    q = {"path": str(tmp_path / "shop.py"), "line": 4, "function": "_check",
         "kind": "guard disabled", "question": "Which input should it catch?"}
    prompt, _ = so.menu(q, source, [tests], str(tmp_path), _guard_mutant(source))
    assert prompt is None


def test_the_probe_sees_the_exception_classes_its_siblings_raise(tmp_path):
    # Run a second time from its file, dates.py caught its own ParseError, not
    # the one other.py raises, and the probe reported a raise the code never makes.
    pkg = tmp_path / "src" / "iso"
    pkg.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='iso'\n")
    (pkg / "__init__.py").write_text("from iso.dates import parse, ParseError\n")
    (pkg / "other.py").write_text("from iso.dates import ParseError\n\ndef strict(text):\n"
                                  "    if not text:\n        raise ParseError('empty')\n"
                                  "    return text\n")
    (pkg / "dates.py").write_text("class ParseError(ValueError):\n    pass\n\n"
                                  "from iso import other\n\ndef parse(text):\n    try:\n"
                                  "        return other.strict(text)\n    except ParseError:\n"
                                  "        return 'fallback'\n")
    assert start_probe.run_calls(str(pkg / "dates.py"), str(tmp_path),
                                 [("parse", [""], {})]) == [{"returns": "'fallback'"}]


def test_a_slow_package_init_does_not_slow_a_module_that_loads_alone(tmp_path):
    import time
    pkg = tmp_path / "src" / "slowpkg"
    pkg.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='slowpkg'\n")
    (pkg / "__init__.py").write_text("import time\ntime.sleep(3)\n")
    (pkg / "calc.py").write_text("def double(x):\n    return x * 2\n")
    began = time.time()
    assert start_probe.run_calls(str(pkg / "calc.py"), str(tmp_path),
                                 [("double", [2], {})]) == [{"returns": "4"}]
    assert time.time() - began < 3


def test_a_raise_against_an_object_without_a_repr_is_a_difference(tmp_path):
    source = ("class Spec:\n"
              "    def __init__(self, text):\n"
              "        if not text[0].isdigit():\n"
              "            raise ValueError(text)\n"
              "        self.text = text\n")
    (tmp_path / "spec.py").write_text(source, encoding="utf-8")
    tests = "from spec import Spec\n\ndef test_s():\n    assert Spec('1.2')\n"
    q = {"path": str(tmp_path / "spec.py"), "line": 3, "function": "__init__",
         "kind": "guard disabled", "question": "Which input should it catch?"}
    prompt, options = so.menu(q, source, [tests], str(tmp_path), _guard_mutant(source))
    labels = [o["label"] for o in options]
    assert prompt and any("a Spec object" in l for l in labels)
    assert not any("0x" in l for l in labels)


def test_building_a_menu_never_writes_a_new_file_beside_the_users_data(tmp_path):
    out = (tmp_path / "data" / "out.txt").as_posix()
    (tmp_path / "data").mkdir()
    source = ("def _check(rate):\n"
              "    if not isinstance(rate, int):\n"
              "        raise TypeError('rate')\n"
              "    return rate\n\n\n"
              "def save(path, text='x'):\n"
              "    with open(path, 'w') as f:\n"
              "        f.write(text)\n"
              "    return len(text)\n")
    (tmp_path / "shop.py").write_text(source, encoding="utf-8")
    tests = f"from shop import save\n\ndef test_save():\n    assert save({out!r}) == 1\n"
    q = {"path": str(tmp_path / "shop.py"), "line": 2, "function": "_check",
         "kind": "guard disabled", "question": "Which input should it catch?"}
    so.menu(q, source, [tests], str(tmp_path), _guard_mutant(source))
    assert list((tmp_path / "data").iterdir()) == []


def test_a_blank_answer_in_the_file_is_asked_again_in_a_terminal(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert start.main("pricing.py", str(tmp_path),
                      console=Script([], interactive=False).console) == start.NEEDS_ANSWERS
    answers = tmp_path / "inputs_private" / "questions" / "PRICING_open_questions.txt"
    text = re.sub(r"^requirements:.*$", "requirements: applies a discount",
                  answers.read_text(encoding="utf-8"), flags=re.M)
    answers.write_text(text, encoding="utf-8")
    start.main("pricing.py", str(tmp_path), console=Script([], interactive=False).console,
               answers=str(answers))
    paths = start.Paths(str(tmp_path), str(tmp_path / "pricing.py"))
    state = start.load_state(paths)
    assert state["answers"] and all(r.get("deferred") for r in state["answers"].values())


# -------------------------------------------- the fifth audit, 2026-10-16 --

def test_a_menu_never_writes_through_a_helper_or_the_lines_own_function(tmp_path):
    report = tmp_path / "report.txt"
    report.write_text("the user's real report\n", encoding="utf-8")
    source = ("def _dump(path, text):\n"
              "    with open(path, 'w') as f:\n"
              "        f.write(text)\n\n\n"
              "def save(path, text):\n"
              "    if not text:\n"
              "        raise ValueError('empty')\n"
              "    _dump(path, text)\n"
              "    return len(text)\n")
    (tmp_path / "shop.py").write_text(source, encoding="utf-8")
    tests = (f"from shop import save\n\ndef test_save():\n"
             f"    assert save({report.as_posix()!r}, 'abc') == 3\n")
    for line, function in ((7, "save"), (2, "_dump")):
        q = {"path": str(tmp_path / "shop.py"), "line": line, "function": function,
             "kind": "guard disabled", "question": "Which input should it catch?"}
        so.menu(q, source, [tests], str(tmp_path), _guard_mutant(source))
    assert report.read_text(encoding="utf-8") == "the user's real report\n"


def test_two_reprs_of_one_function_are_not_a_difference(tmp_path):
    source = ("def _fast(x):\n    return x\n\n\ndef _slow(x):\n    return x\n\n\n"
              "def parser_for(size):\n    if size < 0:\n        raise ValueError(size)\n"
              "    return _fast\n")
    (tmp_path / "disp.py").write_text(source, encoding="utf-8")
    now, changed = start_probe.run_calls(str(tmp_path / "disp.py"), str(tmp_path),
                                         [("parser_for", [5], {})], mutant=source)
    assert now == changed and "0x..." in now[0]["returns"]


def test_an_object_now_against_a_raise_after_is_a_difference(tmp_path):
    source = ("class Spec:\n"
              "    def __init__(self, text):\n"
              "        self.text = text\n")
    changed = source.replace("        self.text = text\n",
                             "        raise ValueError(text)\n")
    (tmp_path / "spec.py").write_text(source, encoding="utf-8")
    now, after = start_probe.run_calls(str(tmp_path / "spec.py"), str(tmp_path),
                                       [("Spec", ["1.2"], {})], mutant=changed)
    assert "returns" in now[0] and after[0] == {"raises": "ValueError"}


def test_a_default_and_a_constant_are_reached_through_public_calls(tmp_path):
    from qikly.mutation import count_sites, make_mutant
    source = ("FREE = 50\n\n\n"
              "def _pad(text, width=4):\n    return text.rjust(width, '0')\n\n\n"
              "def fmt(n):\n    return _pad(str(n))\n\n\n"
              "def shipping(total):\n    return 0 if total >= FREE else 5\n")
    (tmp_path / "shop.py").write_text(source, encoding="utf-8")
    tests = ("from shop import fmt, shipping\n\ndef test_f():\n    assert fmt(985)\n\n"
             "def test_s():\n    assert shipping(60) == 0\n")
    for change, line, function in (("int 4 -> 5", 4, "_pad"),):
        mutant = next(m for m, d in (make_mutant(source, i, "arithmetic")
                                     for i in range(count_sites(source, "arithmetic")))
                      if d.startswith(change))
        q = {"path": str(tmp_path / "shop.py"), "line": line, "function": function,
             "kind": change, "question": "What should it be?"}
        prompt, _ = so.menu(q, source, [tests], str(tmp_path), mutant)
        assert prompt, change


def test_tags_are_read_per_file_and_only_for_answers(tmp_path):
    a = tmp_path / "test_one.py"
    a.write_text('def test_sum():\n    """Criteria: 1"""\n\n'
                 'def test_far():\n    """Criteria: 7"""\n\n'
                 'def test_tail():\n    assert 1\n    # Criteria: 1\n', encoding="utf-8")
    b = tmp_path / "test_two.py"
    b.write_text("def test_sum():\n    assert 1\n", encoding="utf-8")
    from qikly import take_tests
    tagged = take_tests._tagged_tests([str(a), str(b)], 2)
    assert ("test_one", "test_sum") in tagged and ("test_one", "test_tail") in tagged
    assert ("test_two", "test_sum") not in tagged and ("test_one", "test_far") not in tagged


def test_a_class_test_is_read_inside_its_own_class():
    test_file = ("class TestA:\n    def test_x(self):\n        assert parse('1')\n\n"
                 "class TestB:\n    def test_x(self):\n        assert parse('2')\n")
    assert start._makes_call("", ("parse", ["2"], {}), None, test_file, "TestB::test_x")
    assert not start._makes_call("", ("parse", ["1"], {}), None, test_file, "TestB::test_x")


