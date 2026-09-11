"""
The central claim, at the one boundary the other withholding tests cannot see.

`tests/test_withholding.py` guards the **prompt** path: no criterion text
reaches the coding agent's FIX or PATCH prompt. That is the right place for it
and it is not enough here.

An MCP host is usually running its own coding agent. Whatever a tool returns is
handed straight to that agent as context. So if `qikly_run` or `qikly_status`
puts `acceptance_criteria` in its response, the criteria reach a model that is
about to write code, the property this project exists to protect is gone, and
**not one existing test would notice**, because they all watch a different path.

These tests assert on the **serialised** response, the JSON that actually goes
over the wire, not on a dict before serialisation. A dict that happens to hold
the criteria under a key nobody prints is still a leak the moment anything
serialises it, and something always does.

Written before the server existed, which is the only order that proves the
guard was not fitted around the behaviour after the fact.
"""
import json

import pytest

from qikly import mcp_tools

SENTINEL_A = "ZZMCPCRITERIONALPHA"
SENTINEL_B = "ZZMCPCRITERIONBRAVO"

TASK_YAML = f"""task_id: "MCP_SENTINEL"

requirements: |
  Read rows from the input CSVs and write results to the output path.
  This line is not a criterion and may travel freely.

interface:
  module: "outputs.agent_src.code.MCP_SENTINEL.calc"
  system_entrypoint: "run(input_paths, output_path) -> None"

acceptance_criteria:
  - "{SENTINEL_A} must be rejected with a reason."
  - "{SENTINEL_B} must be rounded to two decimal places."

inputs:
  - "input_01.csv"
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project holding one task whose criteria are findable sentinels."""
    monkeypatch.chdir(tmp_path)
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "MCP_SENTINEL.yaml").write_text(TASK_YAML, encoding="utf-8")
    (tmp_path / "inputs_private" / "data" / "MCP_SENTINEL").mkdir(parents=True)
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(tmp_path))
    return tmp_path


def _wire(payload):
    """Exactly what a host receives: the serialised form, not the object."""
    return json.dumps(payload, default=str)


def _assert_no_criteria(text, where):
    for sentinel in (SENTINEL_A, SENTINEL_B):
        assert sentinel not in text, (
            f"{where} leaked a criterion to the host's agent: {sentinel}")
    assert "acceptance_criteria" not in text, (
        f"{where} carries the acceptance_criteria key itself")


# ------------------------------------------------------------- the tools ----

def test_run_returns_an_id_and_no_criteria(project, monkeypatch):
    """
    The one that matters most. `qikly_run` names a task, and the temptation is
    to echo the task back so the host can see what it started.
    """
    monkeypatch.setattr(mcp_tools.runs, "start",
                        lambda task_id, **kw: "MCP_SENTINEL_20260910_120000")
    out = mcp_tools.qikly_run("MCP_SENTINEL")
    assert out["run_id"] == "MCP_SENTINEL_20260910_120000"
    _assert_no_criteria(_wire(out), "qikly_run")


def test_status_reports_progress_and_no_criteria(project, monkeypatch):
    monkeypatch.setattr(mcp_tools.runs, "status", lambda run_id: {
        "run_id": run_id, "task_id": "MCP_SENTINEL", "state": "running",
        "progress": {"stage": "integration", "action": "test_run"},
    })
    out = mcp_tools.qikly_status("MCP_SENTINEL_20260910_120000")
    assert out["state"] == "running"
    _assert_no_criteria(_wire(out), "qikly_status")


def test_a_failing_run_reports_the_failure_without_the_rule_it_broke(project, monkeypatch):
    """
    The subtle one. A failed run is exactly when a helpful tool wants to say
    *why*, and "why" is the criterion. The host's agent may see the error text;
    it may never see the rule.
    """
    monkeypatch.setattr(mcp_tools.runs, "status", lambda run_id: {
        "run_id": run_id, "task_id": "MCP_SENTINEL", "state": "failed",
        "failed_tests": ["test_rejects_bad_rows"],
        "failure_text": "AssertionError: expected a reason for the rejected row",
        "progress": {"stage": "unit"},
    })
    out = mcp_tools.qikly_status("MCP_SENTINEL_20260910_120000")
    wire = _wire(out)
    assert "AssertionError" in wire, "the error text is what the agent is allowed"
    _assert_no_criteria(wire, "qikly_status on a failure")


def test_check_criteria_is_advisory_and_still_does_not_echo_them(project):
    """
    This tool is *about* the criteria, which makes it the easiest place to
    justify returning them. A verdict is not the same as the text.
    """
    out = mcp_tools.qikly_check_criteria("MCP_SENTINEL")
    _assert_no_criteria(_wire(out), "qikly_check_criteria")


def test_scaffold_never_invents_criteria(project, tmp_path):
    """
    `--scaffold` refuses to derive criteria from an implementation, because
    criteria taken from code can only describe what the code already does. The
    tool must not quietly become the place that does it.
    """
    module = tmp_path / "sample.py"
    module.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    out = mcp_tools.qikly_scaffold(str(module))
    text = _wire(out)
    assert "TODO" in text, "criteria must be left for a human"
    assert "add" in text, "the real signature should be there"


# ------------------------------------------------- the guard, generalised ----

def test_no_tool_response_may_carry_the_criteria_key(project, monkeypatch):
    """
    Every tool, one assertion, so a fifth tool added later is covered by
    something rather than by nobody remembering this file exists.
    """
    monkeypatch.setattr(mcp_tools.runs, "start", lambda t, **k: "MCP_SENTINEL_20260910_120000")
    monkeypatch.setattr(mcp_tools.runs, "status", lambda r: {"run_id": r, "state": "passed"})
    calls = {
        "qikly_run": lambda: mcp_tools.qikly_run("MCP_SENTINEL"),
        "qikly_status": lambda: mcp_tools.qikly_status("MCP_SENTINEL_20260910_120000"),
        "qikly_check_criteria": lambda: mcp_tools.qikly_check_criteria("MCP_SENTINEL"),
    }
    for name, call in calls.items():
        _assert_no_criteria(_wire(call()), name)


def test_every_declared_tool_is_covered_here():
    """
    The list of tools and the list of things this file checks must not drift.
    A tool added without a line here is a tool nobody proved is safe.
    """
    covered = {"qikly_run", "qikly_status", "qikly_check_criteria", "qikly_scaffold"}
    assert set(mcp_tools.TOOLS) == covered, (
        "a tool was added or removed without updating the withholding tests: "
        f"{set(mcp_tools.TOOLS) ^ covered}")


# ----------------------------------- criteria hiding inside a text blob ------
#
# The walk above strips forbidden *keys*. `qikly_scaffold` returns a whole task
# file as one string, which is a shape that walk cannot look inside: the same
# criteria it removes as a dict key travel through untouched as YAML.
#
# Nothing leaked when this was written, because scaffold emits TODO
# placeholders and refuses to derive criteria from an implementation. It is
# tested because `--from-doc` merges real criteria into exactly this YAML, so
# the two features are one plausible wiring change apart from a leak the
# key-based guard would never see.


def test_criteria_inside_a_yaml_string_do_not_reach_the_host():
    payload = {"ok": True, "task_yaml": (
        'task_id: "X"\n'
        'acceptance_criteria:\n'
        '  - "%s tax is 0.2 above 100000"\n'
        '  - "%s the boundary is inclusive"\n'
        '\n'
        'interface:\n'
        '  module: "x"\n' % (SENTINEL_A, SENTINEL_B))}
    blob = json.dumps(mcp_tools._redact(payload))
    assert SENTINEL_A not in blob, "a criterion crossed the boundary as YAML text"
    assert SENTINEL_B not in blob


def test_scrubbing_keeps_the_file_useful():
    """
    A scaffold whose criteria section came back empty would be useless, and the
    rest of the file is what the user asked for. Only the criteria go.
    """
    payload = {"task_yaml": (
        'task_id: "X"\n'
        'requirements:\n'
        '  - "read a CSV and write a report"\n'
        'acceptance_criteria:\n'
        '  - "%s tax is 0.2 above 100000"\n'
        'interface:\n'
        '  module: "x"\n' % SENTINEL_A)}
    out = mcp_tools._redact(payload)["task_yaml"]
    assert "read a CSV and write a report" in out
    assert 'module: "x"' in out
    assert "acceptance_criteria:" in out, "the section itself must survive"
    assert "withheld" in out, "the reader has to be told why it is empty"
    import yaml
    assert yaml.safe_load(out), "the scrubbed file must still parse as YAML"


def test_the_todo_placeholders_survive_scrubbing():
    """
    Telling the user what to write is the whole point of that section, so the
    placeholders are not criteria and must not be blanked.
    """
    out = mcp_tools.qikly_scaffold(__file__.replace("tests", "src/qikly").replace(
        "test_mcp_withholding.py", "from_doc.py"))
    if out.get("ok"):
        assert "TODO" in out["task_yaml"], "scaffold stopped being useful"


def test_the_explanatory_note_is_not_mangled_by_the_scrubber():
    """The word appears in prose that must read normally."""
    out = mcp_tools._redact(
        {"note": "requirements and acceptance_criteria are left as TODO on purpose"})
    assert out["note"] == "requirements and acceptance_criteria are left as TODO on purpose"
