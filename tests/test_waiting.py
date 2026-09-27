"""
The heartbeat that says a slow call is still a call.

The bug it prevents is not a crash. It is a person watching a silent terminal
for four minutes, concluding the run is wedged, and killing it. That report
arrives as "qikly hangs", which is unanswerable, so the fix has to be in the
output rather than in the documentation.
"""
import io
import time

import pytest

from qikly.agent_api import waiting
from qikly.agent_api.waiting import Heartbeat


def test_a_fast_call_says_nothing():
    """
    Silence is the common case and has to stay free.

    On the default small model most calls finish inside the first tick, so a
    normal run looks exactly as it did before this existed.
    """
    stream = io.StringIO()
    with Heartbeat("fix", stream=stream, first=5.0):
        time.sleep(0.05)
    assert stream.getvalue() == ""


def test_a_slow_call_reports_while_it_waits():
    stream = io.StringIO()
    with Heartbeat("patch", stream=stream, first=0.05, interval=0.05):
        time.sleep(0.35)
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) >= 2, "a long wait produced fewer than two lines"
    assert all("still waiting on the model" in line for line in lines)
    assert all(line.startswith("  [patch]") for line in lines)


def test_it_reports_elapsed_seconds_and_they_rise():
    stream = io.StringIO()
    with Heartbeat("fix", stream=stream, first=0.05, interval=0.2):
        time.sleep(0.6)
    seconds = [int(line.rsplit(",", 1)[1].strip().rstrip("s"))
               for line in stream.getvalue().splitlines() if line.strip()]
    assert seconds == sorted(seconds), "the clock went backwards"


def test_nothing_rewrites_the_terminal():
    """
    No spinner, no carriage returns, no escape codes.

    This output is read three ways and only one of them is a terminal: it also
    lands in outputs/logs/, in CI, and in the context of whatever agent is
    driving the CLI. A carriage return makes all three worse, and a log full
    of them is worse than a log with no progress at all.
    """
    stream = io.StringIO()
    with Heartbeat("fix", stream=stream, first=0.05, interval=0.05):
        time.sleep(0.2)
    text = stream.getvalue()
    assert "\r" not in text
    assert "\x1b" not in text, "an escape code reached the log"


def test_the_environment_variable_turns_it_off(monkeypatch):
    monkeypatch.setenv(waiting.OFF_ENV, "1")
    stream = io.StringIO()
    with Heartbeat("fix", stream=stream, first=0.05, interval=0.05):
        time.sleep(0.2)
    assert stream.getvalue() == ""


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off "])
def test_only_a_real_yes_turns_it_off(monkeypatch, value):
    """
    An unset variable and a variable set to "0" must not mean the same thing.

    Someone exporting QIKLY_NO_PROGRESS=0 has asked for progress, and reading
    any value as truthy would silently give them the opposite.
    """
    monkeypatch.setenv(waiting.OFF_ENV, value)
    expected = value.strip().lower() in ("1", "true", "yes", "on")
    assert waiting.enabled() is not expected


def test_a_broken_stream_never_takes_down_a_run():
    """
    A progress line is the least important thing in the process.

    If the stream is closed or replaced underneath it, the thread stops and
    says nothing. Raising from a thread nobody is watching would kill a run
    over a cosmetic feature, which is the worst possible trade.
    """
    class Broken(object):
        def write(self, _text):
            raise ValueError("stream closed")

        def flush(self):
            pass

    with Heartbeat("fix", stream=Broken(), first=0.05, interval=0.05):
        time.sleep(0.2)
    # Reaching here at all is the assertion: __exit__ ran and nothing raised.


def test_it_stops_as_soon_as_the_call_returns():
    stream = io.StringIO()
    beat = Heartbeat("fix", stream=stream, first=0.05, interval=0.05)
    with beat:
        time.sleep(0.12)
    before = stream.getvalue()
    time.sleep(0.25)
    assert stream.getvalue() == before, "it kept printing after the call ended"


def test_the_thread_is_a_daemon_so_ctrl_c_is_never_held_up():
    """
    Ctrl+C handling in this project has already been got wrong once.

    A non-daemon timer thread would keep the process alive after the worker
    was killed, which is exactly the symptom the tree-kill fix removed.
    """
    stream = io.StringIO()
    beat = Heartbeat("fix", stream=stream, first=5.0)
    with beat:
        assert beat._thread is not None
        assert beat._thread.daemon is True


def test_call_llm_wraps_its_call_in_one():
    """
    The wiring, checked in the source rather than by making a call.

    A test that ran a real call would cost money, and mocking the provider
    proves the mock was wrapped rather than the provider.
    """
    import ast
    import os

    from qikly.agent_api import call_llm

    tree = ast.parse(io.open(call_llm.__file__, encoding="utf-8").read())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "call_llm":
            for inner in ast.walk(node):
                if isinstance(inner, ast.With):
                    for item in inner.items:
                        call = item.context_expr
                        if (isinstance(call, ast.Call)
                                and getattr(call.func, "id", "") == "Heartbeat"):
                            found = True
    assert found, "call_llm no longer wraps its provider call in a Heartbeat"
    assert os.path.basename(call_llm.__file__) == "call_llm.py"


def test_it_names_its_task_when_one_is_set(monkeypatch):
    """
    Thirteen tasks running at once, and no way to tell whose line is whose.

    The sweep prefixes each task's stdout with its name; the heartbeat writes
    to stderr, which is not prefixed. A real sweep produced 39 lines reading
    "[test_integration] still waiting" with nothing to attribute them to.
    """
    monkeypatch.setenv("QIKLY_TASK_ID", "CALC_TAX")
    stream = io.StringIO()
    with Heartbeat("test_integration", stream=stream, first=0.05, interval=0.05):
        time.sleep(0.15)
    assert "[CALC_TAX test_integration]" in stream.getvalue()


def test_a_single_run_is_not_made_noisier_by_it(monkeypatch):
    """One task needs no attribution, so it does not get one."""
    monkeypatch.delenv("QIKLY_TASK_ID", raising=False)
    stream = io.StringIO()
    with Heartbeat("fix", stream=stream, first=0.05, interval=0.05):
        time.sleep(0.15)
    assert "[fix]" in stream.getvalue()


def test_the_per_task_process_sets_the_task_id():
    """
    Checked in the source, because the alternative is spawning processes.

    The heartbeat can only name a task if something sets it, and the only
    place that knows is the function each task's process starts in.
    """
    import ast

    from qikly import cli

    tree = ast.parse(io.open(cli.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_task_process":
            source = ast.dump(node)
            assert "QIKLY_TASK_ID" in source, (
                "the per-task process no longer records which task it is, so "
                "a sweep's heartbeat lines cannot be attributed")
            return
    raise AssertionError("_run_task_process is gone")
