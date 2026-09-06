"""
Three commands that cost nothing, and the estimate shown before one that does.

Each answers a question someone asks before they will run this tool at all:
what will it cost, is my task file even right, and can I see the withholding
rather than being told about it. All three work offline.
"""
import json
import os

import pytest

from qikly import explain, forecast, validate


# ============================================================= forecast =====

def test_the_estimate_says_which_kind_of_estimate_it_is(tmp_path, monkeypatch):
    """
    A number from your own runs and a number from shipped defaults are not
    equally good, and a reader deserves to know which one they were handed.
    """
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    projection = forecast.estimate(["T"], "gemini-3.5-flash-lite")
    assert projection["basis"] == "shipped defaults"


def test_history_is_preferred_over_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    for i in range(4):
        (tmp_path / f"T_2026010{i}_000000.json").write_text(json.dumps({
            "task": "T", "calls": 7, "input_tokens": 1000, "output_tokens": 200,
        }), encoding="utf-8")
    projection = forecast.estimate(["T"], "gemini-3.5-flash-lite")
    assert projection["basis"] == "your own runs"
    assert projection["calls"] == 7


def test_the_median_is_used_so_one_stall_cannot_dominate(tmp_path, monkeypatch):
    """
    A run that exhausts its budget is the long tail of this distribution, and a
    mean would let a single one of them price every future run.
    """
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    for i, calls in enumerate([5, 5, 5, 500]):
        (tmp_path / f"T_2026010{i}_000000.json").write_text(json.dumps({
            "task": "T", "calls": calls, "input_tokens": 100, "output_tokens": 10,
        }), encoding="utf-8")
    assert forecast.estimate(["T"], "gemini-3.5-flash-lite")["calls"] == 5


def test_it_reads_the_field_names_the_writer_actually_writes(tmp_path, monkeypatch):
    """
    The failure this guards against is silent: reading keys that do not exist
    falls back to the defaults forever while looking like it learned from your
    history. The writer's own names are asserted here rather than assumed.
    """
    from qikly.agent_api.usage import Usage

    keys = set(Usage().as_dict())
    assert {"calls", "input_tokens", "output_tokens"} <= keys, (
        f"forecast.py reads calls/input_tokens/output_tokens; usage writes {sorted(keys)}")


def test_repetitions_multiply_the_estimate(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    one = forecast.estimate(["T"], "gemini-3.5-flash-lite", repeat=1)
    ten = forecast.estimate(["T"], "gemini-3.5-flash-lite", repeat=10)
    assert ten["calls"] == one["calls"] * 10


def test_an_unpriced_model_gives_calls_without_inventing_a_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    projection = forecast.estimate(["T"], "some-model-nobody-priced")
    assert projection["cost_usd"] is None
    assert projection["calls"] > 0
    assert "no cost estimate" in forecast.render(projection)


def test_the_estimate_is_never_presented_as_a_price(tmp_path, monkeypatch):
    """
    A convergence run is a loop with a variable trip count. A projection
    printed as a price would be a lie with a decimal point on it.
    """
    monkeypatch.setattr(forecast, "USAGE_DIR", str(tmp_path))
    text = forecast.render(forecast.estimate(["T"], "gemini-3.5-flash-lite"))
    assert "projection, not a quote" in text
    assert "about" in text


# ============================================================== explain =====

def test_it_reads_the_real_withholding_function():
    """
    A demonstration that built its own two strings would prove what this file
    believes rather than what a run does, and would keep passing after someone
    changed the prompt builder underneath it.
    """
    import inspect

    source = inspect.getsource(explain.build)
    assert "_task_without_acceptance_criteria" in source
    assert "_read_task" in source


def test_a_real_task_shows_the_criteria_removed():
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    facts = explain.build("MERGE_SALES")
    assert facts["criteria_count"] > 0
    assert facts["withheld_ok"], f"criteria leaked: {facts['leaked']}"
    assert facts["coding_agent_chars"] < facts["test_generation_chars"]


def test_the_rendered_output_names_the_verdict():
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    text = explain.render(explain.build("MERGE_SALES"))
    assert "VERDICT" in text
    assert "REMOVED" in text
    assert "no model call" in text


def test_a_leak_would_be_reported_as_a_failure(monkeypatch):
    """
    The check has to be able to fail, or it is decoration. This forces the
    leak the real code prevents and confirms the verdict flips.
    """
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    monkeypatch.setattr(
        "qikly.agent_api.agent_interface._task_without_acceptance_criteria",
        lambda task_id: "acceptance_criteria leaked straight through")
    monkeypatch.setattr(
        "qikly.agent_api.agent_interface._read_task",
        lambda task_id: 'task_id: "T"\nacceptance_criteria:\n  - "leaked straight through"\n')
    facts = explain.build("T")
    assert facts["withheld_ok"] is False
    assert facts["leaked"] == ["leaked straight through"]
    assert "FAILED" in explain.render(facts)


# ============================================================= validate =====

def _task(tmp_path, body, name="T.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_clean_task_produces_nothing(tmp_path):
    path = _task(tmp_path, 'task_id: "T"\nrequirements: "do it"\n'
                           'interface: {module: "m"}\n'
                           'acceptance_criteria:\n  - "0 is rejected"\n')
    assert validate.check_task(path) == ([], [])


def test_broken_yaml_is_one_clear_error_rather_than_a_traceback(tmp_path):
    errors, _ = validate.check_task(_task(tmp_path, "task_id: [unclosed\n"))
    assert len(errors) == 1
    assert "not valid YAML" in errors[0]


def test_criteria_as_a_single_string_is_an_error(tmp_path):
    """
    The quiet one. A string where a list belongs makes the entire bar one
    criterion built from every rule run together, which then generates one
    enormous test, and nothing else complains.
    """
    errors, _ = validate.check_task(_task(
        tmp_path, 'task_id: "T"\nrequirements: "r"\ninterface: {module: "m"}\n'
                  'acceptance_criteria: "everything must be correct"\n'))
    assert any("single string" in e for e in errors)


def test_a_task_id_that_disagrees_with_the_filename_is_an_error(tmp_path):
    """--tasks names one thing and the run reports another."""
    errors, _ = validate.check_task(_task(
        tmp_path, 'task_id: "OTHER"\nrequirements: "r"\ninterface: {module: "m"}\n'))
    assert any("but the file is" in e for e in errors)


def test_a_missing_fixture_is_caught_before_the_suites_are_paid_for(tmp_path):
    errors, _ = validate.check_task(_task(
        tmp_path, 'task_id: "T"\nrequirements: "r"\ninterface: {module: "m"}\n'
                  'inputs:\n  - "no/such/file.csv"\n'))
    assert any("input file not found" in e for e in errors)


def test_a_vague_criterion_is_a_warning_not_an_error(tmp_path):
    """
    Advisory on purpose. "reject large amounts" runs fine and measures less
    than its author thinks, which is a different problem from a broken file.
    """
    errors, warnings = validate.check_task(_task(
        tmp_path, 'task_id: "T"\nrequirements: "r"\ninterface: {module: "m"}\n'
                  'acceptance_criteria:\n  - "amounts must be reasonable"\n'))
    assert errors == []
    assert any("without naming a value" in w for w in warnings)


def test_a_criterion_naming_a_boundary_is_not_warned_about(tmp_path):
    _, warnings = validate.check_task(_task(
        tmp_path, 'task_id: "T"\nrequirements: "r"\ninterface: {module: "m"}\n'
                  'acceptance_criteria:\n  - "100 is accepted and 101 is rejected"\n'))
    assert warnings == []


def test_the_shipped_tasks_all_validate():
    """The examples have to survive the check they ship with."""
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    results = validate.check_all()
    failing = {t: e for t, (e, _) in results.items() if e}
    assert not failing, f"shipped tasks fail validation: {failing}"


# ================================================== the pre-commit hook =====

def test_the_hook_runs_the_free_check_and_not_a_paid_one():
    """
    A hook runs on every commit whether or not you were thinking about it. One
    that bills per commit is one people uninstall on the second day, so the
    entry has to be the offline command.
    """
    import yaml

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".pre-commit-hooks.yaml"), encoding="utf-8") as fh:
        hooks = yaml.safe_load(fh)

    assert len(hooks) == 1
    entry = hooks[0]["entry"]
    assert "--validate" in entry
    for paid in ("--check-criteria", "--generate-criteria", "--tasks", "--demo"):
        assert paid not in entry, f"the hook would spend money: {entry}"


def test_the_demo_shows_the_withholding_before_it_runs():
    """
    Someone watching a demo has one question underneath all the others: what
    makes this different from an agent writing its own tests? Answering it
    first, from the real builders and with no model call, means everything
    after is read in the right frame.

    Before the run, not after, and wrapped so that a demo can never fail
    because an explanation could not be built.
    """
    import inspect

    from qikly import cli

    source = inspect.getsource(cli._demo_body)
    assert "from qikly.explain import" in source
    assert source.index("qikly.explain") < source.index("subprocess.Popen"), (
        "the explanation has to come before the run, not after it")
    assert "except Exception" in source


def test_the_demo_explains_the_task_it_is_about_to_run():
    """CALC_TAX by default, and whatever --tasks names otherwise."""
    from qikly import cli, explain
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    facts = explain.build(cli.DEMO_TASK)
    assert facts["criteria_count"] > 0, (
        f"{cli.DEMO_TASK} is the demo task and has no criteria to withhold")
    assert facts["withheld_ok"]


def test_the_line_count_explains_itself():
    """
    Found by a reader doing arithmetic on the output: 11 criteria are declared
    and 12 lines are removed, and nothing on the page said where the extra one
    came from. It is the `acceptance_criteria:` key the list hangs off.

    A number a reader has to reconcile is a number they distrust, which is the
    wrong reaction to the one screen that exists to demonstrate the claim.
    """
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    facts = explain.build("CALC_TAX")
    text = explain.render(facts)
    assert "`acceptance_criteria:` key" in text
    assert f"all {facts['criteria_count']} criteria under it" in text


def test_the_explain_output_fits_a_terminal():
    """
    It opens the demo, so it is the first thing anyone sees. A line that wraps
    at 80 columns turns a clean block into a ragged one.
    """
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    for task_id in ("CALC_TAX", "MERGE_SALES"):
        for line in explain.render(explain.build(task_id)).splitlines():
            # The criteria and REMOVED lines carry the user's own text and are
            # already truncated; everything qikly writes itself must fit.
            if line.strip().startswith(("REMOVED", "1.", "2.", "3.")):
                continue
            assert len(line) <= 80, f"{len(line)} chars: {line[:90]!r}"


def test_a_bundled_task_validates_on_a_fresh_install(tmp_path, monkeypatch):
    """
    The bug a smoke run in a clean directory found and the unit tests could
    not. A task's `inputs:` carry the private prefix, and a bundled task's
    fixtures live inside the package until a run copies them out, so checking
    the literal path reported all ten shipped tasks as broken: twenty errors,
    every one false, from the command recommended as a pre-commit hook.

    Someone's first `qikly --validate` would have said their install was
    broken.
    """
    monkeypatch.chdir(tmp_path)
    results = validate.check_all()
    failing = {t: e for t, (e, _) in results.items() if e}
    assert not failing, f"clean project reports errors it should not: {failing}"


def test_a_genuinely_missing_fixture_is_still_an_error(tmp_path):
    path = tmp_path / "T.yaml"
    path.write_text('task_id: "T"\nrequirements: "r"\ninterface: {module: "m"}\ninputs:\n  - "inputs_private/data/T/nope.csv"\n',
                    encoding="utf-8")
    errors, _ = validate.check_task(str(path))
    assert any("input file not found" in e for e in errors), (
        "the fix must not swallow a real missing fixture")
