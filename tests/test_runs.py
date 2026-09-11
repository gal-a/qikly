"""
Starting a run without waiting for it, and asking about it afterwards.

This is the mechanism underneath the planned MCP server, and it is tested on
its own because it is the only genuinely new thing there: a tool call cannot
block for the minutes or hours a run takes, so `qikly_run` has to return an id
and `qikly_status` has to answer from what the run leaves on disk.

Two decisions are pinned here because both are easy to undo by accident:

  the run id is not new    it is <task_id>_<run_timestamp>, the string every
                           artefact path is already built from, so there is no
                           mapping between two identifiers to keep in sync
  state is derived         never stored, because the process that would have
                           to update a stored state is the one that crashed
"""
import io
import json
import os
from datetime import datetime, timedelta

import pytest

from qikly import runs


@pytest.fixture
def project(tmp_path, monkeypatch):
    """
    A real project directory, not just an empty one.

    `project_root()` walks up from the working directory looking for
    `inputs_private`, and **failing that walks up from the package's own
    location** and finds the source checkout. A temp directory without the
    marker therefore resolves to this repository, and these tests silently
    read and write its outputs. Creating the marker is what makes tmp_path an
    actual project rather than a directory that happens to be empty.
    """
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "inputs_private", exist_ok=True)
    for d in (runs.runs_dir(), runs.log_dir(), runs.summary_dir()):
        os.makedirs(d, exist_ok=True)
    assert runs.runs_dir().startswith(str(tmp_path)), runs.runs_dir()
    return tmp_path


def _write(path, payload):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle)


def _read(path):
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _record(run_id, pid, started_at=None):
    """
    started_at defaults to now, not to a fixed string.

    A fixed one silently ages past SILENCE_BEFORE_DOUBT and turns every
    "running" assertion into a "stalled" one, which is how this fixture broke
    when that rule was added. Tests that care about age pass it explicitly.
    """
    task, stamp = runs.split_run_id(run_id)
    _write(os.path.join(runs.runs_dir(), run_id + ".json"),
           {"run_id": run_id, "task_id": task, "run_timestamp": stamp,
            "pid": pid,
            "started_at": started_at or datetime.now().astimezone().isoformat(
                timespec="seconds")})


def _log(run_id, rows):
    task, stamp = runs.split_run_id(run_id)
    path = os.path.join(runs.log_dir(), "transactions_%s_%s.jsonl" % (task, stamp))
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _summary(run_id, passed):
    task, stamp = runs.split_run_id(run_id)
    _write(os.path.join(runs.summary_dir(), "%s_%s.json" % (task, stamp)),
           {"task_id": task, "run_timestamp": stamp, "passed_overall": passed,
            "total_fix_attempts": 3, "duration_seconds": 22,
            "provenance": {"provider": "gemini", "model": "gemini-3.5-flash-lite"}})


# ------------------------------------------------------------- the run id ----

def test_the_run_id_is_the_string_every_artefact_already_uses():
    run_id = runs.make_run_id("CALC_TAX", "20260910_120000")
    assert run_id == "CALC_TAX_20260910_120000"
    assert runs.split_run_id(run_id) == ("CALC_TAX", "20260910_120000")


@pytest.mark.parametrize("bad", [
    "", "CALC_TAX", "CALC_TAX_2026", "CALC_TAX_20260910", "20260910_120000",
    "../../etc/passwd", "CALC_TAX_20260910_12000",
])
def test_a_string_that_is_not_a_run_id_is_refused(bad):
    assert runs.split_run_id(bad) == (None, None)


def test_status_of_a_malformed_id_says_so_rather_than_raising():
    out = runs.status("../../etc/passwd")
    assert out["state"] == "unknown"
    assert "run id" in out["detail"]


# --------------------------------------------------------------- states ------

def test_a_run_with_a_live_process_and_no_summary_is_running(project, monkeypatch):
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242)
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    assert runs.status(run_id)["state"] == "running"


def test_a_run_whose_process_is_gone_without_a_summary_is_stalled(project, monkeypatch):
    """
    A crash and a failure are different things and must not be reported the
    same way: a failure has a summary, a crash has nothing.
    """
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242)
    monkeypatch.setattr(runs, "_alive", lambda pid: False)
    out = runs.status(run_id)
    assert out["state"] == "stalled"
    assert "no summary" in out["detail"]


@pytest.mark.parametrize("passed,expected", [(True, "passed"), (False, "failed")])
def test_a_summary_decides_the_outcome(project, monkeypatch, passed, expected):
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242)
    _summary(run_id, passed)
    # Even with the process still alive, a written summary is the answer.
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    out = runs.status(run_id)
    assert out["state"] == expected
    assert out["total_fix_attempts"] == 3
    assert out["provenance"]["model"] == "gemini-3.5-flash-lite"
    assert out["artifacts"]["run_summary"].endswith(".json")


def test_a_run_nobody_started_is_unknown(project):
    out = runs.status("CALC_TAX_20260910_120000")
    assert out["state"] == "unknown"


# -------------------------------------------------------------- progress -----

def test_progress_comes_from_the_log_the_run_writes(project, monkeypatch):
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=1)
    _log(run_id, [
        {"ts": "2026-09-10T12:00:01", "stage": "integration", "action": "tests_generated"},
        {"ts": "2026-09-10T12:00:09", "stage": "integration", "action": "test_run",
         "iteration": 2, "status": "failed"},
    ])
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    p = runs.status(run_id)["progress"]
    assert p["events"] == 2
    assert p["stage"] == "integration"
    assert p["action"] == "test_run"
    assert p["iteration"] == 2
    assert p["all_tests_passed"] is False


def test_a_half_written_line_does_not_break_progress(project, monkeypatch):
    """
    The log is appended to by a live process, so a read can land mid-line.
    Reporting nothing would be wrong; raising would be worse.
    """
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=1)
    task, stamp = runs.split_run_id(run_id)
    path = os.path.join(runs.log_dir(), "transactions_%s_%s.jsonl" % (task, stamp))
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"action": "tests_generated", "stage": "unit"}) + "\n")
        handle.write('{"action": "test_ru')          # torn write
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    p = runs.status(run_id)["progress"]
    assert p["events"] == 1
    assert p["stage"] == "unit"


def test_the_passing_marker_is_noticed(project, monkeypatch):
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=1)
    _log(run_id, [{"action": "all_tests_passed", "ts": "2026-09-10T12:00:40"}])
    monkeypatch.setattr(runs, "_alive", lambda pid: False)
    assert runs.status(run_id)["progress"]["all_tests_passed"] is True


def test_no_log_yet_is_empty_progress_not_an_error(project, monkeypatch):
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=1)
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    assert runs.status(run_id)["progress"] == {}


# ------------------------------------------------------------ listing --------

def test_runs_are_listed_newest_first(project, monkeypatch):
    for stamp in ("20260910_090000", "20260910_120000", "20260909_235959"):
        _record("CALC_TAX_%s" % stamp, pid=1)
    monkeypatch.setattr(runs, "_alive", lambda pid: False)
    got = [r["run_timestamp"] for r in runs.list_runs()]
    assert got == ["20260910_120000", "20260910_090000", "20260909_235959"]


def test_listing_an_absent_directory_is_empty_rather_than_an_error(tmp_path, monkeypatch):
    """A project that has never run anything, not a missing project."""
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "inputs_private", exist_ok=True)
    assert not os.path.isdir(runs.runs_dir())
    assert runs.list_runs() == []


# ------------------------------------------------- the injected timestamp ----

def test_the_orchestrator_accepts_a_timestamp_the_parent_chose(monkeypatch):
    """
    This is what makes a detached run addressable: the parent knows where the
    run will write before the run has written anything.
    """
    from qikly.orchestrator import orchestrator as o
    monkeypatch.setenv(o.RUN_TIMESTAMP_ENV, "20260910_120000")
    assert o._injected_run_timestamp() == "20260910_120000"


@pytest.mark.parametrize("bad", ["", "bad", "../../etc", "2026091_120000",
                                 "20260910_120000/../x"])
def test_a_timestamp_that_could_escape_the_output_tree_is_refused(monkeypatch, bad):
    """
    It becomes part of several file paths, so a separator in it would write
    outside the run's own directories.
    """
    from qikly.orchestrator import orchestrator as o
    monkeypatch.setenv(o.RUN_TIMESTAMP_ENV, bad)
    assert o._injected_run_timestamp() is None


# ----------------------------------------------------- how it is launched ----

def test_the_child_is_launched_without_a_console_window(monkeypatch, tmp_path):
    """
    The first version used DETACHED_PROCESS, which only stops the child
    inheriting this console and leaves it, and the per-stage subprocesses it
    spawns, free to acquire one. A console window opened on the user's desktop
    on the first real use. The two flags are mutually exclusive, so this cannot
    be fixed by adding CREATE_NO_WINDOW alongside it.

    CREATE_NEW_PROCESS_GROUP is the other half: without it a Ctrl+C or a
    closing console in the parent's group reaches the run and kills it, which
    defeats the point of starting it in the background.
    """
    import subprocess as sp

    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "inputs_private", exist_ok=True)
    captured = {}

    class _Proc:
        pid = 1234

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(runs.subprocess, "Popen", fake_popen)
    runs.start("CALC_TAX")

    if os.name == "nt":
        flags = captured["creationflags"]
        assert flags & sp.CREATE_NO_WINDOW, "a console window would open"
        assert flags & sp.CREATE_NEW_PROCESS_GROUP, "closing the terminal would kill it"
        assert not flags & getattr(sp, "DETACHED_PROCESS", 0), (
            "DETACHED_PROCESS makes CREATE_NO_WINDOW be ignored")
    else:
        assert captured.get("start_new_session") is True


def test_the_child_gets_the_timestamp_the_parent_chose(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "inputs_private", exist_ok=True)
    captured = {}

    class _Proc:
        pid = 1234

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs); captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(runs.subprocess, "Popen", fake_popen)
    run_id = runs.start("CALC_TAX")

    _, stamp = runs.split_run_id(run_id)
    assert captured["env"]["QIKLY_RUN_TIMESTAMP"] == stamp
    assert captured["env"]["QIKLY_NO_VERSION_CHECK"] == "1"
    assert "--tasks" in captured["cmd"] and "CALC_TAX" in captured["cmd"]
    # And it runs in the project, not wherever the caller happened to be.
    assert str(tmp_path) in str(captured["cwd"])


# ------------------------------------------- a pid that is somebody else's ---

def test_a_live_pid_that_has_written_nothing_for_ages_is_not_believed(project, monkeypatch):
    """
    `_alive` is the only signal separating running from stalled, and a pid gets
    reused. Windows recycles low pids quickly, so a crashed run whose pid was
    taken by something unrelated would report "running" forever and the crash
    this state exists to name would be hidden.
    """
    run_id = "CALC_TAX_20260910_120000"
    old = (datetime.now().astimezone()
           - timedelta(seconds=runs.SILENCE_BEFORE_DOUBT + 60)).isoformat(timespec="seconds")
    _record(run_id, pid=4242, started_at=old)
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    out = runs.status(run_id)
    assert out["state"] == "stalled"
    assert "somebody else" in out["detail"]


def test_a_run_that_is_quiet_but_recent_is_still_running(project, monkeypatch):
    """A model call can legitimately leave the log silent for minutes."""
    run_id = "CALC_TAX_20260910_120000"
    recent = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat(timespec="seconds")
    _record(run_id, pid=4242, started_at=recent)
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    assert runs.status(run_id)["state"] == "running"


def test_recent_log_activity_keeps_a_long_run_alive(project, monkeypatch):
    """Age is measured from the last transaction, not from the start."""
    run_id = "CALC_TAX_20260910_120000"
    long_ago = (datetime.now().astimezone()
                - timedelta(seconds=runs.SILENCE_BEFORE_DOUBT * 3)).isoformat(timespec="seconds")
    _record(run_id, pid=4242, started_at=long_ago)
    _log(run_id, [{"action": "test_run", "stage": "unit",
                   "ts": datetime.now().isoformat(timespec="seconds")}])
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    assert runs.status(run_id)["state"] == "running"


def test_an_unreadable_timestamp_never_turns_a_run_into_a_crash(project, monkeypatch):
    """A clock or format problem must not manufacture failures."""
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242, started_at="not a timestamp")
    monkeypatch.setattr(runs, "_alive", lambda pid: True)
    assert runs.status(run_id)["state"] == "running"


# --------------------------------------------------- hostile task ids --------

@pytest.mark.parametrize("bad", [
    "../../evil", "a/b", "a\b", "..", ".", "", None, 42, "with space",
])
def test_a_task_id_that_could_escape_the_output_tree_is_refused(bad):
    """
    It arrives straight from an MCP tool call and becomes part of several file
    paths. os.path.join normalises "outputs/runs/../../evil.json" two levels
    up, so this was a write outside the project waiting for a hostile or
    careless caller.
    """
    with pytest.raises(runs.BadTaskId):
        runs.make_run_id(bad, "20260910_120000")


@pytest.mark.parametrize("good", ["CALC_TAX", "calc-tax", "calc.tax", "a1_B2"])
def test_ordinary_task_ids_still_work(good):
    assert runs.make_run_id(good, "20260910_120000").startswith(good + "_")


def test_start_refuses_a_hostile_task_id_before_launching_anything(project, monkeypatch):
    launched = []
    monkeypatch.setattr(runs.subprocess, "Popen",
                        lambda *a, **k: launched.append(a) or None)
    with pytest.raises(runs.BadTaskId):
        runs.start("../../evil")
    assert not launched, "a process was started for a rejected task id"


# ------------------------------------------------------ id collisions --------

def test_two_starts_in_the_same_second_get_different_ids(project, monkeypatch):
    """
    The id is task plus a one-second timestamp. Two starts inside one second
    produced the same id: the second record overwrote the first, both children
    were handed the same QIKLY_RUN_TIMESTAMP so they appended to one
    transaction log, and they raced to overwrite one summary. A host retrying a
    slow tool call is enough to cause it.
    """
    frozen = datetime(2026, 9, 10, 12, 0, 0)
    monkeypatch.setattr(runs, "datetime", _FrozenDatetime(frozen))
    ids = [runs._claim_run_id("SAME")[0] for _ in range(3)]
    assert len(set(ids)) == 3, ids
    for run_id in ids:
        task, stamp = runs.split_run_id(run_id)
        assert task == "SAME" and stamp, run_id


def test_a_claim_is_a_real_reservation_on_disk(project, monkeypatch):
    """Two callers must not both believe they hold the same id."""
    run_id, _, path = runs._claim_run_id("SAME")
    assert os.path.exists(path), "the claim did not reserve anything"
    assert runs._claim_run_id("SAME")[0] != run_id


class _FrozenDatetime:
    """Stands in for the datetime module so `now()` does not advance."""

    def __init__(self, moment):
        self._moment = moment

    def now(self, tz=None):
        return self._moment


# ------------------------------------------- what progress is allowed to say --

def test_progress_copies_an_allowlist_and_not_the_whole_row(project):
    """
    A transaction row carries `failure` (whole pytest output), `fix` (the
    model's reasoning) and `test_path` (a criteria-derived test file). Only
    stage, action, iteration and ts are copied out.

    Widening this to `out.update(last)` would be a natural-looking tidy-up and
    would put failure text and test paths into every MCP status response. The
    audit asked whether the MCP boundary leaks through artifacts; the honest
    answer is that it does not *because of this allowlist*, so the allowlist
    gets a test rather than a comment.
    """
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242)
    _log(run_id, [{
        "stage": "unit", "action": "test_run", "iteration": 2,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "failure": "ZZLEAKFAILURE assert 0.19 == 0.2",
        "fix": "ZZLEAKFIX the boundary must be inclusive at 100000",
        "test_path": "outputs/tests/CALC_TAX/unit/test_unit.py",
        "criteria_in_batch": 7,
    }])
    monkey = runs.status(run_id)["progress"]
    assert monkey["stage"] == "unit" and monkey["iteration"] == 2
    blob = json.dumps(monkey)
    for forbidden in ("ZZLEAKFAILURE", "ZZLEAKFIX", "test_path", "criteria_in_batch"):
        assert forbidden not in blob, "%s reached the status response" % forbidden


def test_a_finished_runs_response_carries_no_free_text(project):
    """
    Same boundary on the other branch. The summary is counts; if somebody adds
    a free-text field to it, this says so before it reaches a host agent.
    """
    run_id = "CALC_TAX_20260910_120000"
    _record(run_id, pid=4242)
    _write(os.path.join(runs.summary_dir(), "CALC_TAX_20260910_120000.json"),
           {"passed_overall": True, "total_fix_attempts": 3,
            "why": "ZZLEAKWHY because the criterion said 100000 was inclusive"})
    out = runs.status(run_id)
    assert out["state"] == "passed"
    assert "ZZLEAKWHY" not in json.dumps(out, default=str)


# ------------------------------------------ asking the OS about a process ----

def test_a_broken_process_lookup_does_not_invent_a_crash(project, monkeypatch):
    """
    `_alive` shells out to tasklist on Windows. If that is missing, restricted
    by policy, or slow, the call raised and the exception escaped status()
    entirely. Reporting "dead" instead would be worse than the crash: a healthy
    run would be declared stalled on the strength of a broken lookup. Unknown
    means believed alive, and the silence rule is what settles it.
    """
    monkeypatch.setattr(runs.os, "name", "nt")

    def missing(*a, **k):
        raise FileNotFoundError("tasklist is not on PATH")

    monkeypatch.setattr(runs.subprocess, "run", missing)
    assert runs._alive(4242) is True


def test_a_slow_process_lookup_is_not_fatal_either(project, monkeypatch):
    monkeypatch.setattr(runs.os, "name", "nt")

    def slow(*a, **k):
        raise runs.subprocess.TimeoutExpired(cmd="tasklist", timeout=20)

    monkeypatch.setattr(runs.subprocess, "run", slow)
    assert runs._alive(4242) is True


def test_the_pid_is_matched_as_a_field_not_as_a_substring(project, monkeypatch):
    """
    The old check was `str(pid) in stdout`. Memory usage is printed in the same
    line, so pid 42 matched the "42,168 K" of an unrelated process and a dead
    run looked alive. CSV makes the pid a field that can be compared exactly.
    """
    monkeypatch.setattr(runs.os, "name", "nt")

    class Result:
        stdout = '"python.exe","9999","Console","1","42,168 K"\n'

    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: Result())
    assert runs._alive(42) is False, "matched the memory column, not the pid"
    assert runs._alive(9999) is True


def test_an_image_name_containing_a_comma_does_not_confuse_the_parser(project, monkeypatch):
    monkeypatch.setattr(runs.os, "name", "nt")

    class Result:
        stdout = '"my, app.exe","777","Console","1","1,024 K"\n'

    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: Result())
    assert runs._alive(777) is True


# ------------------------------------------ the moment before a pid exists ---

def test_a_run_that_has_a_record_but_no_pid_yet_is_not_a_crash(project):
    """
    start() writes its record before launching, so there is a moment where the
    record exists and the pid does not. That used to be an empty claim file,
    which status() read as no record at all and reported "stalled": a run doing
    nothing wrong, described as a crash. Narrow on a local disk, wider on a
    synced folder.
    """
    run_id = "CALC_TAX_20260910_120000"
    task, stamp = runs.split_run_id(run_id)
    _write(os.path.join(runs.runs_dir(), run_id + ".json"),
           {"run_id": run_id, "task_id": task, "run_timestamp": stamp,
            "pid": None,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds")})
    assert runs.status(run_id)["state"] == "running"


def test_a_launch_that_never_completed_still_ends_up_stalled(project):
    """
    The forgiving reading above must not be permanent. A record that never
    gained a pid, because the process failed to start and the cleanup did not
    run, is a crash once it has been silent long enough.
    """
    run_id = "CALC_TAX_20260910_120000"
    task, stamp = runs.split_run_id(run_id)
    old = (datetime.now().astimezone()
           - timedelta(seconds=runs.SILENCE_BEFORE_DOUBT + 60)).isoformat(timespec="seconds")
    _write(os.path.join(runs.runs_dir(), run_id + ".json"),
           {"run_id": run_id, "task_id": task, "run_timestamp": stamp,
            "pid": None, "started_at": old})
    assert runs.status(run_id)["state"] == "stalled"


def test_start_writes_the_record_before_it_launches_anything(project, monkeypatch):
    """
    The ordering is the fix, so it is the thing worth pinning. Popen looks at
    the record that exists at the moment it is called.
    """
    seen = {}

    class Fake:
        pid = 4242

    def spy(*a, **k):
        # The child is told which run it is through the environment, so the
        # record to look for can be named from the same value.
        stamp = k["env"]["QIKLY_RUN_TIMESTAMP"]
        seen["record"] = _read(
            os.path.join(runs.runs_dir(), "SPY_%s.json" % stamp))
        return Fake()

    monkeypatch.setattr(runs.subprocess, "Popen", spy)
    run_id = runs.start("SPY")
    assert seen["record"] is not None, "no record existed when the process started"
    assert seen["record"]["run_id"] == run_id
    assert seen["record"]["pid"] is None, "the pid cannot be known before Popen"
    # and afterwards it is filled in
    final = _read(os.path.join(runs.runs_dir(), run_id + ".json"))
    assert final["pid"] == 4242


def test_a_record_is_never_read_half_written(project):
    """
    status() runs while records are being written. A truncated file parses as
    no record, which reads as a crash, so the write goes through os.replace.
    """
    run_id = "CALC_TAX_20260910_120000"
    path = os.path.join(runs.runs_dir(), run_id + ".json")
    os.makedirs(runs.runs_dir(), exist_ok=True)
    runs._write_record(path, {"run_id": run_id, "pid": 1})
    runs._write_record(path, {"run_id": run_id, "pid": 2})
    assert _read(path)["pid"] == 2
    leftovers = [f for f in os.listdir(runs.runs_dir()) if f.endswith(".tmp")]
    assert not leftovers, "a temporary file was left behind: %s" % leftovers
