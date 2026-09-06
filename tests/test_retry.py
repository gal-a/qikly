"""
Tests for retrying transport failures around a model call.

The distinction being tested is the whole point: a bad answer is information
and the loop already handles it, while a rate limit says nothing about the
task and should not cost an attempt from the stage budget. A single 429 once
ended a sweep and lost six completed pairs, none of which had anything wrong
with them.

The other half matters just as much. Several refusals arrive wearing a 429 and
retrying them is pure delay: a depleted balance will still be depleted in four
seconds, and the message already says what to do.
"""
import pytest

from qikly.agent_api import retry as r


# ------------------------------------------------------------ classifying ----

@pytest.mark.parametrize("message", [
    "429 RESOURCE_EXHAUSTED: rate limit exceeded",
    "503 Service Unavailable",
    "The model is overloaded. Please try again",
    "Connection reset by peer",
    "Read timed out",
    "502 Bad Gateway",
])
def test_transport_failures_are_transient(message):
    assert r.classify(RuntimeError(message)) == "transient"


@pytest.mark.parametrize("message", [
    "429 RESOURCE_EXHAUSTED: Your project has exceeded its monthly spending cap.",
    "429 RESOURCE_EXHAUSTED: Your prepayment credits are depleted.",
    "401 Unauthorized: invalid api key",
    "403 permission denied",
])
def test_refusals_that_retrying_cannot_fix_are_permanent(message):
    """
    Every one of these arrives as an error a naive matcher would call
    transient, and three of the four carry a 429. Waiting four seconds and
    asking again reaches the same answer more slowly.
    """
    assert r.classify(RuntimeError(message)) == "permanent"


def test_an_unrecognised_failure_is_not_retried():
    """
    Unknown is more likely a bug in the prompt or the code than a hiccup, and
    retrying a bug three times only makes it take three times as long to show
    up.
    """
    assert r.classify(ValueError("unexpected token in response schema")) == "unknown"


# -------------------------------------------------------------- backoff -----

def test_a_provider_requested_delay_is_honoured():
    """Backing off for 4 seconds when told 30 wastes the attempt."""
    assert r.retry_after_seconds(RuntimeError("rate limited, retry-after: 30")) == 30.0
    assert r.retry_after_seconds(RuntimeError('"retryDelay": "17s"')) == 17.0


def test_a_requested_delay_is_capped():
    assert r.retry_after_seconds(RuntimeError("retry-after: 9999")) == 120.0


def test_no_requested_delay_reads_as_none():
    assert r.retry_after_seconds(RuntimeError("503 unavailable")) is None


def test_backoff_grows_and_stays_bounded():
    class _Fixed:
        def random(self):
            return 0.5
    waits = [r.backoff_seconds(i, rng=_Fixed()) for i in range(8)]
    assert waits[0] < waits[1] < waits[2]
    assert max(waits) <= 60.0


def test_backoff_is_jittered():
    """
    Tasks run concurrently. Without jitter they all wait the same interval and
    retry in the same instant, recreating the burst that caused the limit.
    """
    class _A:
        def random(self): return 0.0
    class _B:
        def random(self): return 1.0
    assert r.backoff_seconds(2, rng=_A()) != r.backoff_seconds(2, rng=_B())


# --------------------------------------------------------------- retrying ---

def test_a_transient_failure_is_retried_and_can_succeed():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("503 Service Unavailable")
        return "ok"

    assert r.with_retry(flaky, sleep=lambda s: None, log=lambda *a: None) == "ok"
    assert len(calls) == 3


def test_a_permanent_failure_is_raised_at_once():
    calls = []

    def broke():
        calls.append(1)
        raise RuntimeError("429: Your prepayment credits are depleted.")

    with pytest.raises(RuntimeError, match="depleted"):
        r.with_retry(broke, sleep=lambda s: None, log=lambda *a: None)
    assert len(calls) == 1, "no point asking again"


def test_attempts_are_bounded_and_the_last_error_is_raised():
    calls = []

    def always():
        calls.append(1)
        raise RuntimeError("429 rate limit")

    with pytest.raises(RuntimeError, match="rate limit"):
        r.with_retry(always, attempts=3, sleep=lambda s: None, log=lambda *a: None)
    assert len(calls) == 3


def test_a_successful_call_is_not_slowed_down():
    slept = []
    assert r.with_retry(lambda: "fine", sleep=slept.append, log=lambda *a: None) == "fine"
    assert slept == []


def test_the_model_call_goes_through_the_retry(monkeypatch):
    """Guards the wiring: losing it restores the old behaviour silently."""
    import inspect

    from qikly.agent_api import call_llm as mod
    assert "with_retry" in inspect.getsource(mod.call_llm)


# ------------------------------------------- quota: the ambiguous 429 case ---

def test_a_per_minute_quota_is_transient():
    """
    The same word covers two opposite situations. A per-minute rate limit
    clears by itself; a depleted balance does not. "quota exceeded for quota
    metric" sat in the permanent list, so a rate limit that would have cleared
    in thirty seconds ended the run outright.
    """
    from qikly.agent_api.retry import classify

    assert classify(
        "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
        "'generate_requests_per_model_per_minute'") == "transient"


def test_a_per_day_quota_is_also_worth_waiting_for():
    from qikly.agent_api.retry import classify

    assert classify("429 Quota exceeded for quota metric requests_per_day") == "transient"


def test_a_depleted_balance_is_still_permanent():
    """
    The other direction matters just as much: retrying an empty account spends
    the whole retry budget on 429s and reports a network problem.
    """
    from qikly.agent_api.retry import classify

    assert classify(
        "429 RESOURCE_EXHAUSTED: Your prepayment credits are depleted. "
        "Please go to AI Studio to manage your project and billing.") == "permanent"


def test_a_spend_cap_is_permanent_even_though_it_is_a_429():
    from qikly.agent_api.retry import classify

    assert classify("429 RESOURCE_EXHAUSTED: spending cap reached") == "permanent"


def test_a_quota_word_alone_does_not_make_it_retryable():
    """
    Only the per-unit forms are read as recoverable. A bare quota refusal with
    no rate in it falls through to the ordinary rules.
    """
    from qikly.agent_api.retry import classify

    assert classify("403 insufficient_quota for this project") == "permanent"
