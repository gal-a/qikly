"""
First-run friction around --scaffold and --validate.

Measured on a fresh module on 2026-09-14: scaffold wrote two task files and
asked the user to delete one, told them to run a task whose input file did not
exist, and --validate then passed a file still full of TODO placeholders with
no warning at all.
"""
import os

import yaml

from qikly import cli, scaffold, validate

MODULE = ("def extract(input_path):\n    pass\n\n"
          "def run_billing(input_paths, output_path):\n    pass\n")


def _module(tmp_path, monkeypatch):
    (tmp_path / "billing.py").write_text(MODULE, encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))


def _task(tmp_path, name):
    path = tmp_path / "inputs_private" / "config" / "tasks" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------ one task file ----

def test_scaffold_writes_one_task_that_tests_the_existing_code(tmp_path, monkeypatch, capsys):
    _module(tmp_path, monkeypatch)
    assert cli._do_scaffold("billing.py", None) == 0
    assert os.listdir(tmp_path / "inputs_private" / "config" / "tasks") == ["BILLING_VERIFY.yaml"]
    assert _task(tmp_path, "BILLING_VERIFY.yaml")["seed"]["implementation"]
    assert "--fresh" in capsys.readouterr().out, "the other job has to be discoverable"


def test_fresh_writes_only_the_new_implementation_task(tmp_path, monkeypatch):
    _module(tmp_path, monkeypatch)
    assert cli._do_scaffold("billing.py", None, fresh=True) == 0
    assert os.listdir(tmp_path / "inputs_private" / "config" / "tasks") == ["BILLING.yaml"]
    assert "seed" not in _task(tmp_path, "BILLING.yaml")


def test_the_fresh_flag_parses():
    import sys

    argv = sys.argv
    try:
        sys.argv = ["qikly", "--scaffold", "billing.py", "--fresh"]
        args = cli._parse_args()
    finally:
        sys.argv = argv
    assert args.fresh is True


# ------------------------------------------------------------- next steps ----

def test_the_next_steps_name_the_missing_input_and_validate_before_running(
        tmp_path, monkeypatch, capsys):
    _module(tmp_path, monkeypatch)
    cli._do_scaffold("billing.py", None)
    out = capsys.readouterr().out.replace("\\", "/")
    assert "inputs_private/data/BILLING/input_01.csv" in out
    assert out.index("qikly --validate") < out.index("qikly --tasks BILLING_VERIFY")
    assert "Then: qikly --tasks" not in out


def test_the_input_step_is_skipped_when_the_data_is_already_there(
        tmp_path, monkeypatch, capsys):
    _module(tmp_path, monkeypatch)
    data = tmp_path / "inputs_private" / "data" / "BILLING"
    data.mkdir(parents=True)
    (data / "input_01.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    cli._do_scaffold("billing.py", None)
    assert "add a real sample of your input data" not in capsys.readouterr().out


# --------------------------------------------------------- --validate TODO ----

def test_validate_warns_about_leftover_todo_placeholders(tmp_path):
    task = tmp_path / "T.yaml"
    task.write_text(
        'task_id: "T"\n'
        'requirements:\n  - "TODO: describe what this module must do"\n'
        'interface:\n  module: "m"\n'
        'acceptance_criteria:\n  - "0 is rejected and 1 is accepted"\n',
        encoding="utf-8")
    errors, warnings = validate.check_task(str(task))
    assert not errors
    assert any("TODO" in w and "requirements" in w for w in warnings), warnings


def test_a_finished_task_draws_no_todo_warning(tmp_path):
    task = tmp_path / "T.yaml"
    task.write_text(
        'task_id: "T"\n'
        'requirements:\n  - "Read the file and validate each row"\n'
        'interface:\n  module: "m"\n'
        'acceptance_criteria:\n  - "0 is rejected and 1 is accepted"\n',
        encoding="utf-8")
    _errors, warnings = validate.check_task(str(task))
    assert not any("TODO" in w for w in warnings), warnings


# --------------------------------------------------------------- the words ----

def test_the_scaffold_template_uses_decisions_and_consequences():
    assert "The decisions" in scaffold.TASK_TEMPLATE
    assert "The consequences" in scaffold.TASK_TEMPLATE
    assert "checkable edge cases" not in scaffold.TASK_TEMPLATE


def test_the_landing_page_offers_the_quick_start_beside_the_install_block():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    install = page.index('<div class="install">')
    links = page.index('<div class="links">', install)
    assert "QUICK_START_ON_YOUR_OWN_DATA.md" in page[install:links]


# ---------------------------------------------------------------- over MCP ----

def test_the_mcp_scaffold_returns_the_task_that_tests_the_existing_code(tmp_path):
    """The command line and the editor must hand over the same default task."""
    from qikly import mcp_tools

    module = tmp_path / "billing.py"
    module.write_text(MODULE, encoding="utf-8")
    payload = mcp_tools.qikly_scaffold(str(module))
    assert payload["ok"] is True, payload.get("error")
    task = yaml.safe_load(payload["task_yaml"])
    assert task["seed"]["implementation"]
    assert "inputs_private/config/tasks/%s.yaml" % task["task_id"] in payload["note"]
