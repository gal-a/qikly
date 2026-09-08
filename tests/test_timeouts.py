"""
Every model call has a deadline, and the process says it is alive.

A ten-repetition sweep once hung after its first repetition and sat silent for
two hours: four live processes, no log line, no retry, no error. Every provider
SDK here defaults to waiting forever, so a stalled connection blocked the call,
and because it never raised, nothing downstream could react. `with_retry` saw
no exception and the attempt budget never advanced.

The fix is two parts. A timeout turns the hang into an ordinary transient
error that the retry layer already handles. A heartbeat makes "not answering"
visible rather than something you infer from the clock.
"""
import os

import pytest

from qikly.agent_api.providers import timeouts


def test_there_is_a_deadline_by_default(monkeypatch):
    monkeypatch.delenv(timeouts.ENV_VAR, raising=False)
    assert timeouts.request_timeout() == timeouts.DEFAULT_REQUEST_TIMEOUT


def test_the_default_is_far_longer_than_any_real_call(monkeypatch):
    """
    Cutting off a slow-but-working call wastes the tokens already spent on it.
    Cutting off a dead one costs nothing. So the deadline is deliberately
    generous: minutes, not seconds.
    """
    monkeypatch.delenv(timeouts.ENV_VAR, raising=False)
    assert timeouts.request_timeout() >= 120


def test_the_deadline_can_be_overridden(monkeypatch):
    monkeypatch.setenv(timeouts.ENV_VAR, "45")
    assert timeouts.request_timeout() == 45.0


def test_zero_restores_waiting_forever(monkeypatch):
    """An explicit escape hatch, for anyone who wants the old behaviour."""
    monkeypatch.setenv(timeouts.ENV_VAR, "0")
    assert timeouts.request_timeout() is None
    assert timeouts.timeout_milliseconds() is None


def test_a_typo_falls_back_rather_than_ending_the_run(monkeypatch):
    """
    This is read on the path to every model call. A malformed environment
    variable must not be what kills a run that would otherwise work.
    """
    monkeypatch.setenv(timeouts.ENV_VAR, "five minutes")
    assert timeouts.request_timeout() == timeouts.DEFAULT_REQUEST_TIMEOUT


def test_gemini_gets_milliseconds(monkeypatch):
    """google-genai takes milliseconds where the others take seconds."""
    monkeypatch.setenv(timeouts.ENV_VAR, "30")
    assert timeouts.timeout_milliseconds() == 30000


@pytest.mark.parametrize("name", ["gemini.py", "openai.py", "anthropic.py"])
def test_every_provider_passes_a_timeout(name):
    """
    One provider without a deadline is enough to reproduce the hang, and it
    would only show up on whichever provider a user happened to choose.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "qikly", "agent_api", "providers", name)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    assert "timeouts import" in source, f"{name} does not read the deadline"
    assert "timeout=" in source, f"{name} builds its client without a timeout"


def test_a_timed_out_call_is_retried_not_abandoned():
    """
    The whole point of the deadline: it has to become an error the retry layer
    will back off and reattempt, not a permanent refusal.
    """
    from qikly.agent_api.retry import classify

    for message in ("httpx.ReadTimeout: timed out",
                    "Request timed out after 300s",
                    "ConnectTimeout"):
        assert classify(message) == "transient", message


# ------------------------------------------------------------- heartbeat ----

def test_the_heartbeat_reports_while_a_run_is_alive(capsys):
    import time

    from qikly import cli

    stop = cli._heartbeat("T", every=0.05)
    time.sleep(0.2)
    stop.set()
    time.sleep(0.1)
    assert "still running" in capsys.readouterr().out


def test_the_heartbeat_stops_when_told(capsys):
    import time

    from qikly import cli

    stop = cli._heartbeat("T", every=0.05)
    stop.set()
    capsys.readouterr()
    time.sleep(0.25)
    assert "still running" not in capsys.readouterr().out


def test_the_heartbeat_is_silent_for_a_normal_run(capsys):
    """
    A converging run takes under two minutes against a five-minute interval,
    so this normally prints nothing at all. It is a signal that something is
    wrong, not a progress bar.
    """
    import time

    from qikly import cli

    assert cli.HEARTBEAT_SECONDS >= 300
    stop = cli._heartbeat("T")
    time.sleep(0.2)
    stop.set()
    assert capsys.readouterr().out == ""


def test_the_heartbeat_thread_cannot_hold_the_process_open():
    """A non-daemon ticker would keep a finished run from exiting."""
    import threading

    from qikly import cli

    stop = cli._heartbeat("T", every=60)
    ticker = [t for t in threading.enumerate() if t.name.startswith("heartbeat-")]
    try:
        assert ticker and all(t.daemon for t in ticker)
    finally:
        stop.set()
