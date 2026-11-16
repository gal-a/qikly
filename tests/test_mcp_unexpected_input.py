"""
What an agent passes to the MCP tools that they did not expect.

An agent fills these arguments in with no person reading them, so each odd
value gets an answer that names the fix, and nothing odd starts a run. The
schema's enum for `provider` is advice to the host, not a check: before this,
`qikly_run` started a run with provider "evil", 5 or a list.
"""
import json
import os

import pytest

from qikly import mcp_server, runs


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(tmp_path))
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T.yaml").write_text('task_id: "T"\nrequirements:\n  - "r"\n'
                                  'acceptance_criteria:\n  - "f(1) returns 1"\n')
    (tmp_path / "mod.py").write_text("def f(x):\n    return x\n")
    (tmp_path / "notes.txt").write_text("SECRET=hunter2\n")
    (tmp_path / "pkg").mkdir()
    started = []
    monkeypatch.setattr(runs, "start", lambda task_id, env=None: started.append(
        ((env or {}).get("LLM_PROVIDER"), (env or {}).get("LLM_MODEL"))) or "T_20261116_120000")
    return started


def _call(name, arguments):
    return json.loads(mcp_server.call_tool(name, arguments))


ODD = [None, "", " ", 0, True, [], {}, ["x"], {"a": 1}, "x" * 5000, "a\x00b",
       "../../etc/passwd", "C:\\Windows\\win.ini", "*", "%s", "NUL", "\u00e9t\u00e9"]


@pytest.mark.parametrize("name, key", [("qikly_run", "task_id"), ("qikly_status", "run_id"),
                                       ("qikly_validate", "task_id"),
                                       ("qikly_scaffold", "file_path")])
@pytest.mark.parametrize("value", ODD, ids=repr)
def test_an_odd_argument_gets_an_answer_and_starts_nothing(project, name, key, value):
    out = mcp_server.call_tool(name, {key: value})
    data = json.loads(out)
    assert data.get("ok") is False or name == "qikly_validate", data
    assert "Traceback" not in out and "hunter2" not in out
    assert project == []


@pytest.mark.parametrize("provider", ["evil", 5, ["gemini"], {"a": 1}, " "])
def test_an_unknown_provider_starts_no_run(project, provider):
    data = _call("qikly_run", {"task_id": "T", "provider": provider})
    assert data["ok"] is False and "provider must be one of" in data["error"], data
    assert project == []


@pytest.mark.parametrize("model", [7, {"a": 1}, "x\ny", "two words", " "])
def test_a_model_that_is_not_one_name_starts_no_run(project, model):
    data = _call("qikly_run", {"task_id": "T", "model": model})
    assert data["ok"] is False and "model must be one model name" in data["error"], data
    assert project == []


def test_a_provider_in_capitals_or_empty_is_read_as_meant(project):
    assert _call("qikly_run", {"task_id": "T", "provider": " Anthropic "})["ok"]
    assert _call("qikly_run", {"task_id": "T", "provider": "", "model": ""})["ok"]
    assert project == [("anthropic", None), (None, None)]


@pytest.mark.parametrize("arguments, says", [
    ({}, "task_id is required"),
    (None, "task_id is required"),
    ({"task_id": "T", "extra": 1}, "qikly_run does not take 'extra'. It takes: task_id, provider, model"),
    ("T", "takes its arguments as an object"),
    (["T"], "takes its arguments as an object"),
])
def test_arguments_of_the_wrong_shape_are_named(project, arguments, says):
    data = _call("qikly_run", arguments)
    assert data["ok"] is False and says in data["error"], data
    assert project == []


def test_a_folder_is_named_as_a_folder(project):
    data = _call("qikly_scaffold", {"file_path": "pkg"})
    assert "is a folder" in data["error"], data


def test_a_file_that_is_not_python_is_named_and_not_read_back(project):
    out = mcp_server.call_tool("qikly_scaffold", {"file_path": "notes.txt"})
    assert "is not a Python file" in out and "hunter2" not in out


def test_the_right_call_still_works(project):
    assert _call("qikly_scaffold", {"file_path": "mod.py"})["ok"]
    assert _call("qikly_run", {"task_id": "T", "provider": "gemini"})["run_id"]
