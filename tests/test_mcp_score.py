"""
`qikly_score` and `qikly_score_result`: step 1 as an MCP tool.

Scoring takes seconds to over an hour, so it follows the `qikly_run` design:
start in the background, poll for the result. These tests cover the argument
checks, the reading of a finished score back from its log, and one real score
of a tiny module, because a parser that only ever saw hand-written logs is a
parser nobody has shown works on what the command prints.
"""
import io
import json
import os
import sys
import time

import pytest

from qikly import mcp_server, mcp_tools, runs

MODULE = '''def apply_discount(price, rate):
    if rate < 0 or rate > 100:
        raise ValueError("rate out of range")
    return round(price * (1 - rate / 100), 2)
'''

TEST = '''import pytest
from pricing import apply_discount


def test_basic():
    assert apply_discount(100, 10) == 90


def test_bad_rate():
    with pytest.raises(ValueError):
        apply_discount(100, 200)
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A folder with one module and its tests, and no qikly project files."""
    (tmp_path / "pricing.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text(TEST, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(tmp_path))
    return tmp_path


def _log(project, score_id, text, pid=None, started_at=None):
    """A score record and its log, as start_score would have left them."""
    folder = project / "outputs" / "score_runs"
    folder.mkdir(parents=True, exist_ok=True)
    logs = project / "outputs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (folder / ("%s.json" % score_id)).write_text(json.dumps({
        "score_id": score_id, "kind": "score", "code": "pricing.py", "pid": pid,
        "started_at": started_at or "2026-11-26T10:00:00+00:00"}), encoding="utf-8")
    (logs / ("%s.log" % score_id)).write_text(text, encoding="utf-8")


# ------------------------------------------------------------ arguments -----

def test_a_missing_path_names_where_it_looked(project):
    out = mcp_tools.qikly_score("nope.py")
    assert out["ok"] is False
    assert "no such path" in out["error"]
    assert str(project) in out["error"]


def test_a_non_python_file_is_refused(project):
    (project / "notes.txt").write_text("hi", encoding="utf-8")
    out = mcp_tools.qikly_score("notes.txt")
    assert out["ok"] is False
    assert "not a Python file" in out["error"]


@pytest.mark.parametrize("bad", [0, -3, 1001, 2.5, True, "12", [5]])
def test_mutants_must_be_a_whole_number_in_range(project, bad):
    out = mcp_tools.qikly_score("pricing.py", mutants=bad)
    assert out["ok"] is False
    assert "mutants" in out["error"]


def test_a_missing_tests_path_is_refused(project):
    out = mcp_tools.qikly_score("pricing.py", tests_path="tests/none.py")
    assert out["ok"] is False
    assert "tests path" in out["error"]


def test_nothing_is_started_when_an_argument_is_bad(project, monkeypatch):
    started = []
    monkeypatch.setattr(runs, "start_score", lambda *a, **k: started.append(a))
    mcp_tools.qikly_score("pricing.py", mutants=0)
    mcp_tools.qikly_score("nope.py")
    assert started == []


def test_a_valid_call_starts_one_score_and_says_how_to_poll(project, monkeypatch):
    seen = {}

    def fake(code, tests, mutants=None, **kwargs):
        seen.update(code=code, tests=tests, mutants=mutants)
        return "score-pricing.py_20260910_120000"

    monkeypatch.setattr(runs, "start_score", fake)
    out = mcp_tools.qikly_score("pricing.py", mutants=5)
    assert out == {"ok": True, "score_id": "score-pricing.py_20260910_120000",
                   "state": "running",
                   "next": "call qikly_score_result with this score_id"}
    assert os.path.isabs(seen["code"]) and seen["code"].endswith("pricing.py")
    assert seen["tests"] is None and seen["mutants"] == 5


def test_the_tool_arguments_arrive_through_the_dispatcher(project, monkeypatch):
    monkeypatch.setattr(runs, "start_score", lambda *a, **k: "score-x_20260910_120000")
    out = json.loads(mcp_server.call_tool("qikly_score", {"code_path": "pricing.py"}))
    assert out["ok"] is True
    out = json.loads(mcp_server.call_tool("qikly_score", {}))
    assert out["ok"] is False


# ----------------------------------------------------- reading the result ---

FINISHED = """qikly 0.6.5  2026-11-26 23:01:00  run in /somewhere
Scoring against tests/test_pricing.py, the test files that import it. To name others, add --score-tests <file or folder>.
[pricing.py] 5 of 10 planted faults missed (50%), 5 caught.
[pricing.py] what it missed, one line each: {report}
[pricing.py] 3 questions your tests leave open, in the same report.
"""

REPORT = """# Suite score for pricing.py

## What it missed

Each line is a change to your code that the suite still passed.

1. `pricing.py`: < became <=, line 2 (arithmetic)
2. `pricing.py`: > became >=, line 2 (arithmetic)

## Questions your tests leave open

1. Your tests pass whether this is `rate < 0` or `rate <= 0`.

## What it caught
"""


def test_a_finished_score_is_read_from_its_log_and_report(project):
    report = project / "qikly-suite-score" / "pricing.py_20260910_120000.md"
    report.parent.mkdir()
    report.write_text(REPORT, encoding="utf-8")
    _log(project, "score-pricing.py_20260910_120000",
         FINISHED.replace("{report}", str(report)))

    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["ok"] is True
    assert out["state"] == "finished"
    assert (out["planted"], out["missed"], out["caught"]) == (10, 5, 5)
    assert out["missed_percent"] == 50
    assert out["headline"].startswith("5 of 10 planted faults missed (50%)")
    assert out["open_questions"] == 3
    assert out["report_path"] == str(report)
    assert out["missed_faults"] == [
        "`pricing.py`: < became <=, line 2 (arithmetic)",
        "`pricing.py`: > became >=, line 2 (arithmetic)"]


def test_the_missed_lines_stop_at_the_next_section(project):
    report = project / "r.md"
    report.write_text(REPORT, encoding="utf-8")
    assert len(runs._missed_faults(str(report))) == 2


def test_a_score_still_running_says_so(project):
    _log(project, "score-pricing.py_20260910_120000", "qikly 0.6.5  banner only\n",
         pid=os.getpid(), started_at=_now())
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["state"] == "running"


def test_a_suite_that_fails_on_the_original_is_not_scored_and_says_why(project):
    _log(project, "score-pricing.py_20260910_120000",
         "qikly 0.6.5  banner\n"
         "[pricing.py] your suite does not pass your untouched code, so planting "
         "a fault would prove nothing. Report at /x/r.md\n", pid=None)
    runs_record = project / "outputs" / "score_runs" / "score-pricing.py_20260910_120000.json"
    record = json.loads(runs_record.read_text(encoding="utf-8"))
    record["pid"] = 999999991                      # a pid nothing holds
    runs_record.write_text(json.dumps(record), encoding="utf-8")
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["state"] == "not_scored"
    assert "does not pass your untouched code" in out["detail"]
    assert "banner" not in out["detail"]


def test_a_process_that_vanished_without_output_is_stalled(project):
    _log(project, "score-pricing.py_20260910_120000", "", pid=999999991)
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["state"] == "stalled"


def test_a_score_older_than_the_cap_is_not_believed_alive(project):
    _log(project, "score-pricing.py_20260910_120000", "", pid=os.getpid(),
         started_at="2020-01-01T00:00:00+00:00")
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["state"] == "stalled"


def test_unknown_ids_are_reported_not_raised(project):
    for bad in ("nonsense", "CALC_TAX_20260910_120000",
                "score-never_20260910_120000"):
        out = mcp_tools.qikly_score_result(bad)
        assert out["ok"] is False and out["state"] == "unknown", bad
    assert mcp_tools.qikly_score_result("")["ok"] is False


def test_a_score_id_does_not_show_up_as_a_run(project):
    """A score is not a run: it must not read as a crashed one."""
    _log(project, "score-pricing.py_20260910_120000", "")
    assert runs.status("score-pricing.py_20260910_120000")["state"] == "unknown"
    assert runs.list_runs() == []


def _now():
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


# -------------------------------------------------- one real score, no mocks --

def test_a_real_score_of_a_tiny_module_comes_back_finished(project):
    """
    The command is started for real, detached, and polled the way a host would.
    The parser is only worth anything if it reads what the command prints.
    """
    out = mcp_tools.qikly_score("pricing.py")
    assert out["ok"] is True, out
    score_id = out["score_id"]
    assert score_id.startswith("score-pricing.py_")

    deadline = time.time() + 240
    result = {}
    while time.time() < deadline:
        result = mcp_tools.qikly_score_result(score_id)
        if result["state"] != "running":
            break
        time.sleep(1)

    assert result["state"] == "finished", result
    assert result["planted"] > 0
    assert result["missed"] + result["caught"] == result["planted"]
    assert result["missed"] >= 1, "this suite misses the boundaries on purpose"
    assert os.path.isfile(result["report_path"])
    assert result["missed_faults"], "the missed lines should come back by value"
    # Nothing of the caller's was changed.
    assert (project / "pricing.py").read_text(encoding="utf-8") == MODULE


# ------------------------------------- the generated tests stay hidden ------
#
# The first version let a caller name `outputs/tests/<TASK>/` as the tests. Its
# failing assertion quoted the criterion it was written from, and the response
# carried that text to the host's agent. Found by an independent review, and
# reproduced before it was fixed: this is that scenario.

SENTINEL = "ZZSCORECRITERION"
HIDDEN = (
    "from pricing import apply_discount\n"
    "def test_hidden():\n"
    "    assert apply_discount(100, 100) == 0, '%s a full discount is free'\n"
    % SENTINEL)


@pytest.fixture
def hidden(project):
    folder = project / "outputs" / "tests" / "T"
    folder.mkdir(parents=True)
    (folder / "test_hidden.py").write_text(HIDDEN, encoding="utf-8")
    return folder


@pytest.mark.parametrize("code, tests", [
    ("pricing.py", "outputs/tests/T/test_hidden.py"),
    ("pricing.py", "outputs/tests/T"),
    ("pricing.py", "outputs"),
    ("pricing.py", "tests/../outputs/tests/T/test_hidden.py"),
    ("outputs/tests/T/test_hidden.py", None),
    ("outputs", None),
    (".", "tests"),
])
def test_nothing_under_or_holding_outputs_is_scored(project, hidden, monkeypatch,
                                                    code, tests):
    started = []
    monkeypatch.setattr(runs, "start_score", lambda *a, **k: started.append(a))
    out = mcp_tools.qikly_score(code, tests_path=tests)
    assert out["ok"] is False
    assert "outputs/" in out["error"]
    assert started == [], "a refused call must not start anything"
    assert SENTINEL not in json.dumps(out)


def test_a_link_into_outputs_does_not_get_round_the_check(project, hidden):
    link = project / "innocent"
    try:
        os.symlink(str(hidden), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make a symbolic link here")
    out = mcp_tools.qikly_score("pricing.py", tests_path="innocent")
    assert out["ok"] is False


def test_pytests_own_failure_text_is_not_returned(project):
    """Whatever the suite quoted, the log's pytest lines stay out of `detail`."""
    _log(project, "score-pricing.py_20260910_120000",
         "qikly 0.6.5  banner\n"
         "[pricing.py] your suite does not pass your untouched code, so planting "
         "a fault would prove nothing.\n"
         "[pricing.py] what pytest said:\n"
         "[pricing.py]     E       AssertionError: %s a full discount is free\n"
         "[pricing.py]     E       assert 0.5 == 0\n"
         "[pricing.py]     FAILED outputs/tests/T/test_hidden.py::test_hidden - %s\n"
         "[pricing.py] This is a problem in your project's environment.\n"
         % (SENTINEL, SENTINEL), pid=999999991)
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert out["state"] == "not_scored"
    wire = json.dumps(out)
    assert SENTINEL not in wire
    assert "AssertionError" not in wire
    assert "does not pass your untouched code" in out["detail"]
    assert "problem in your project's environment" in out["detail"]


def test_the_hidden_suite_cannot_be_reached_end_to_end(project, hidden):
    """Nothing is started, so no log exists to read the criterion back from."""
    out = mcp_tools.qikly_score("pricing.py", tests_path="outputs/tests/T")
    assert out["ok"] is False
    assert not (project / "outputs" / "score_runs").exists()


# ------------------------------------------------------------ process -------

def test_the_child_does_not_inherit_the_interactive_switch(project, monkeypatch):
    """With it set, a slow suite asks a question nobody can answer and stops."""
    seen = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        seen.update(env=kwargs["env"], cmd=cmd)
        return FakeProc()

    monkeypatch.setenv("QIKLY_INTERACTIVE", "1")
    monkeypatch.setattr(runs.subprocess, "Popen", fake_popen)
    score_id = runs.start_score(str(project / "pricing.py"), mutants=4)
    assert "QIKLY_INTERACTIVE" not in seen["env"]
    assert seen["env"]["PYTHONUNBUFFERED"] == "1"
    assert seen["cmd"][-2:] == ["--score-mutants", "4"]
    assert score_id.startswith("score-pricing.py_")


def test_a_headline_alone_is_not_yet_a_finished_score(project):
    """
    The headline is printed before the report line. While the process is still
    writing, answering from half the output would give a final state with no
    report and no questions.
    """
    headline_only = "[pricing.py] 5 of 10 planted faults missed (50%), 5 caught.\n"
    _log(project, "score-pricing.py_20260910_120000", headline_only,
         pid=os.getpid(), started_at=_now())
    assert mcp_tools.qikly_score_result(
        "score-pricing.py_20260910_120000")["state"] == "running"

    # Once the process is gone there is nothing more to wait for.
    _log(project, "score-pricing.py_20260910_120001", headline_only, pid=999999991)
    done = mcp_tools.qikly_score_result("score-pricing.py_20260910_120001")
    assert done["state"] == "finished"
    assert "report_path" not in done


# ------------------------------- found by the second independent review ------
#
# Each of these was reproduced against the first fix before it was repaired.

BS = chr(92)


def test_a_long_path_prefix_does_not_get_round_the_check(project, hidden):
    if os.name != "nt":
        pytest.skip("the long-path prefix is a Windows form")
    spelled = BS * 2 + "?" + BS + str(hidden)
    out = mcp_tools.qikly_score("pricing.py", tests_path=spelled)
    assert out["ok"] is False
    assert SENTINEL not in json.dumps(out)


def test_a_link_inside_a_tests_folder_is_refused(project, hidden):
    holder = project / "mytests"
    holder.mkdir()
    try:
        os.symlink(str(hidden), str(holder / "gen"), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make a symbolic link here")
    assert mcp_tools.qikly_score("pricing.py", tests_path="mytests")["ok"] is False


def test_a_hard_link_to_a_generated_test_is_refused(project, hidden):
    holder = project / "mytests"
    holder.mkdir()
    try:
        os.link(str(hidden / "test_hidden.py"), str(holder / "test_copy.py"))
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make a hard link here")
    assert mcp_tools.qikly_score("pricing.py", tests_path="mytests")["ok"] is False


def test_tests_found_automatically_are_checked_too(project, hidden, monkeypatch):
    """Leaving tests_path out must not skip the check on what the CLI would find."""
    import qikly.start
    monkeypatch.setattr(qikly.start, "auto_tests",
                        lambda code, cwd=None: str(hidden / "test_hidden.py"))
    started = []
    monkeypatch.setattr(runs, "start_score", lambda *a, **k: started.append(a))
    out = mcp_tools.qikly_score("pricing.py")
    assert out["ok"] is False and started == []


def test_a_label_with_a_bracket_does_not_defeat_the_pytest_filter(project):
    label = "a]b"
    _log(project, "score-%s_20260910_120000" % label.replace("]", "-"),
         "[%s] your suite does not pass your untouched code.\n"
         "[%s] what pytest said:\n"
         "[%s]     E       AssertionError: %s a full discount is free\n"
         "[%s]     FAILED t.py::t - %s\n"
         "[%s] This is a problem in your project's environment.\n"
         % ((label,) * 3 + (SENTINEL,) + (label,) + (SENTINEL,) + (label,)),
         pid=999999991)
    out = mcp_tools.qikly_score_result("score-a-b_20260910_120000")
    assert SENTINEL not in json.dumps(out)
    assert "problem in your project's environment" in out["detail"]


def test_a_report_path_outside_the_report_folder_is_not_read(project, tmp_path):
    secret = tmp_path / "other.md"
    secret.write_text("## What it missed\n\n1. SECRETLINE\n", encoding="utf-8")
    _log(project, "score-pricing.py_20260910_120000",
         "[pricing.py] 5 of 10 planted faults missed (50%), 5 caught.\n"
         "[pricing.py] what it missed, one line each: {secret}\n".replace(
             "{secret}", str(secret)),
         pid=999999991)
    out = mcp_tools.qikly_score_result("score-pricing.py_20260910_120000")
    assert "SECRETLINE" not in json.dumps(out)


def test_the_child_is_told_not_to_quote_pytest(project, monkeypatch):
    seen = {}

    class FakeProc:
        pid = 4243

    monkeypatch.setattr(runs.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(env=kw["env"]) or FakeProc())
    runs.start_score(str(project / "pricing.py"))
    assert seen["env"]["QIKLY_NO_PYTEST_QUOTE"] == "1"


def test_optional_arguments_accept_an_explicit_null():
    pytest.importorskip("mcp")          # an optional extra, not on every CI job
    import asyncio
    from qikly.mcp_server import build_server
    server = build_server()
    schema = {t.name: t.input_schema for t in asyncio.run(server.list_tools())}
    for prop in ("tests_path", "mutants"):
        spec = schema["qikly_score"]["properties"][prop]
        assert "null" in json.dumps(spec), spec
