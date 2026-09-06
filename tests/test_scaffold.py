"""
Tests for project creation and for deriving a task from existing code.

These two commands close the gap between "installed" and "usable". A fresh
install had nowhere to put a task, and the use case the tool exists for,
verifying code somebody else wrote, required hand-writing an interface block
restating signatures already present in the file being pointed at.

The one thing that must never happen here is scaffold writing acceptance
criteria. Criteria derived from an implementation can only describe what that
implementation already does, and a bar that agrees with the code by
construction is exactly the failure the whole tool exists to prevent. It has
its own test.
"""
import os

import pytest
import yaml

from qikly import scaffold


SAMPLE = '''
"""A module someone else wrote."""
from decimal import Decimal


def extract(input_path):
    return []


def transform(rows, tax_rate: Decimal = Decimal("0.2")) -> dict:
    return {"accepted": [], "rejected": []}


def _private_helper():
    return 1


def run_billing(input_paths, output_path) -> None:
    pass
'''


@pytest.fixture
def module(tmp_path):
    p = tmp_path / "src" / "billing.py"
    p.parent.mkdir(parents=True)
    p.write_text(SAMPLE, encoding="utf-8")
    return p


# ------------------------------------------------------- reading the code ----

def test_public_top_level_functions_are_found_in_order(module):
    names = [f.name for f in scaffold.read_functions(module.read_text(encoding="utf-8"))]
    assert names == ["extract", "transform", "run_billing"]


def test_private_helpers_are_not_part_of_the_interface(module):
    names = [f.name for f in scaffold.read_functions(module.read_text(encoding="utf-8"))]
    assert "_private_helper" not in names, "the interface is what tests may call"


def test_signatures_keep_their_annotations(module):
    text, problem = scaffold.build_task(str(module), str(module.parent.parent))
    assert problem is None
    assert "transform(rows, tax_rate: Decimal) -> dict" in text


def test_the_entrypoint_prefers_a_run_prefixed_function(module):
    fns = scaffold.read_functions(module.read_text(encoding="utf-8"))
    assert scaffold.guess_entrypoint(fns).name == "run_billing"


def test_the_entrypoint_falls_back_to_the_widest_signature():
    src = "def alpha(a):\n    pass\n\ndef beta(a, b, c):\n    pass\n"
    fns = scaffold.read_functions(src)
    assert scaffold.guess_entrypoint(fns).name == "beta"


def test_the_module_path_is_dotted_and_relative_to_the_project(module):
    assert scaffold.module_path(str(module), str(module.parent.parent)) == "src.billing"


# ---------------------------------------------------------- the generated ----

def test_the_generated_task_is_valid_yaml_with_the_interface_filled_in(module):
    text, problem = scaffold.build_task(str(module), str(module.parent.parent))
    assert problem is None
    data = yaml.safe_load(text)
    assert data["task_id"] == "BILLING"
    assert data["interface"]["module"] == "src.billing"
    assert len(data["interface"]["integration_functions"]) == 3
    assert data["interface"]["system_entrypoint"].startswith("run_billing")


def test_criteria_are_never_derived_from_the_implementation(module):
    """
    The one thing this command must not do. A criterion read out of the code
    describes what the code already does, so the coding agent would be judged
    against its own behaviour and every run would pass for no reason.
    """
    text, _ = scaffold.build_task(str(module), str(module.parent.parent))
    data = yaml.safe_load(text)
    assert data["acceptance_criteria"] == ["TODO: one checkable statement, with its boundary value"]
    assert data["requirements"] == ["TODO: describe what this module must do"]
    assert "never sees" in text.lower() or "NEVER sees" in text


def test_the_task_id_can_be_overridden(module):
    text, _ = scaffold.build_task(str(module), str(module.parent.parent), task_id="MY_ID")
    assert yaml.safe_load(text)["task_id"] == "MY_ID"


def test_a_file_with_no_public_functions_is_refused_with_a_reason(tmp_path):
    p = tmp_path / "empty.py"
    p.write_text("X = 1\n\ndef _hidden():\n    pass\n", encoding="utf-8")
    text, problem = scaffold.build_task(str(p), str(tmp_path))
    assert text is None
    assert "no public top level functions" in problem


def test_a_file_that_does_not_parse_is_refused_with_a_reason(tmp_path):
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n    pass\n", encoding="utf-8")
    text, problem = scaffold.build_task(str(p), str(tmp_path))
    assert text is None
    assert "does not parse" in problem


# ------------------------------------------------------------------- init ----

def test_init_creates_a_runnable_layout(tmp_path):
    made, skipped = scaffold.init_project(str(tmp_path))
    assert skipped == []
    for rel in ("inputs_private/config/tasks/MY_FIRST_TASK.yaml",
                "inputs_private/data/MY_FIRST_TASK/input_01.csv",
                "inputs_private/config/settings.yaml"):
        assert (tmp_path / rel).exists(), rel


def test_the_starter_task_is_valid_and_carries_both_halves(tmp_path):
    scaffold.init_project(str(tmp_path))
    data = yaml.safe_load(
        (tmp_path / "inputs_private/config/tasks/MY_FIRST_TASK.yaml").read_text(encoding="utf-8"))
    assert data["requirements"] and data["acceptance_criteria"]
    assert data["interface"]["module"]


def test_the_starter_criteria_name_boundary_values(tmp_path):
    """
    The starter file is the first thing a new user copies, so its criteria
    have to demonstrate the habit the whole project depends on: a boundary
    stated explicitly, not "must be positive".
    """
    scaffold.init_project(str(tmp_path))
    text = (tmp_path / "inputs_private/config/tasks/MY_FIRST_TASK.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert any("0 is rejected" in c and "1 is accepted" in c
               for c in data["acceptance_criteria"])


def test_init_never_overwrites_existing_work(tmp_path):
    scaffold.init_project(str(tmp_path))
    task = tmp_path / "inputs_private/config/tasks/MY_FIRST_TASK.yaml"
    task.write_text("mine\n", encoding="utf-8")
    made, skipped = scaffold.init_project(str(tmp_path))
    assert task.read_text(encoding="utf-8") == "mine\n"
    assert any("MY_FIRST_TASK.yaml" in p for p in skipped)
    assert not any("MY_FIRST_TASK.yaml" in p for p in made)


# ---------------------------------------------------------- the CLI wiring ---

def test_init_writes_where_the_user_is_standing(tmp_path, monkeypatch, capsys):
    """
    cli.py chdirs to the project root at import, so the first version of this
    created its files inside the qikly checkout instead of the user's project.
    The invocation directory has to be captured before that chdir.
    """
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_init() == 0
    assert (tmp_path / "inputs_private/config/tasks/MY_FIRST_TASK.yaml").exists()
    assert "Next:" in capsys.readouterr().out


def test_scaffold_writes_the_task_where_the_user_is_standing(tmp_path, monkeypatch, capsys):
    from qikly import cli

    src = tmp_path / "mod.py"
    src.write_text("def run_it(a, b):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("mod.py", None) == 0
    assert (tmp_path / "inputs_private/config/tasks/MOD.yaml").exists()
    assert "acceptance_criteria" in capsys.readouterr().out


def test_scaffold_refuses_to_clobber_an_existing_task(tmp_path, monkeypatch, capsys):
    from qikly import cli

    src = tmp_path / "mod.py"
    src.write_text("def run_it(a):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    cli._do_scaffold("mod.py", None)
    existing = tmp_path / "inputs_private/config/tasks/MOD.yaml"
    existing.write_text("hand written\n", encoding="utf-8")
    assert cli._do_scaffold("mod.py", None) == 2
    assert existing.read_text(encoding="utf-8") == "hand written\n"


def test_scaffold_reports_a_missing_file_rather_than_raising(tmp_path, monkeypatch, capsys):
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("nope.py", None) == 2
    assert "no such file" in capsys.readouterr().out


def test_check_criteria_exits_non_zero_when_it_finds_a_contradiction(monkeypatch, capsys):
    """
    A non-zero exit lets a pipeline gate on it, which is the only reason to
    run a check before a run rather than after.
    """
    from qikly import cli
    from qikly.orchestrator.tuning import check_criteria as cc

    monkeypatch.setattr(cc, "check",
                        lambda t, seed=None: [{"criterion": "c",
                                               "conflicts_with": "r", "why": "w"}])
    assert cli._do_check_criteria("CALC_TAX") == 1
    assert "contradiction" in capsys.readouterr().out


def test_check_criteria_exits_zero_on_a_clean_spec(monkeypatch, capsys):
    from qikly import cli
    from qikly.orchestrator.tuning import check_criteria as cc

    monkeypatch.setattr(cc, "check", lambda t, seed=None: [])
    assert cli._do_check_criteria("CALC_TAX") == 0
