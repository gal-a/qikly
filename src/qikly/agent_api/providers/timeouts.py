"""
How long one model call may take before it is treated as a failure.

Every provider SDK here defaults to waiting forever. A stalled connection
therefore blocks the call, and because it never returns an error, nothing
downstream can react: `with_retry` sees no exception, the orchestrator's
attempt budget never advances, and the run neither finishes nor fails.

That is not hypothetical. A ten-repetition sweep hung after its first
repetition and sat silent for two hours: four live processes, no log line, no
retry, no error. The only remedy was killing it, and nine repetitions of paid
work were lost to a default nobody set.

A timeout converts that into an ordinary transient error, which the retry
layer already knows how to back off and reattempt.

## Why 300 seconds

A cold call on a large prompt runs a few seconds; the slowest legitimate calls
observed here are well under a minute. Five minutes is far outside that and
still far inside a person's patience. It is deliberately not tight: cutting off
a slow-but-working call wastes the tokens already spent on it, whereas cutting
off a dead one costs nothing.

`QIKLY_REQUEST_TIMEOUT` overrides it, in seconds. 0 restores the old
wait-forever behaviour for anyone who needs it.
"""
import os

DEFAULT_REQUEST_TIMEOUT = 300.0
ENV_VAR = "QIKLY_REQUEST_TIMEOUT"


def request_timeout():
    """
    Seconds one model call may take, or None for no limit.

    A malformed value falls back to the default rather than raising: this is
    read on the path to every model call, and a typo in an environment
    variable should not be what ends a run.
    """
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        return DEFAULT_REQUEST_TIMEOUT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_REQUEST_TIMEOUT
    return None if value <= 0 else value


def timeout_milliseconds():
    """The same value in milliseconds, which is what google-genai expects."""
    seconds = request_timeout()
    return None if seconds is None else int(seconds * 1000)
