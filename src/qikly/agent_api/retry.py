"""
Retry a model call when the transport fails, not when the answer is bad.

There are two kinds of failure around a model call and they need opposite
treatment. A bad answer, a diff that will not apply, a test file that does not
parse, is information: the loop feeds it back and asks again, and that
machinery already exists. A transport failure carries no information at all. A
rate limit, a gateway error, a dropped connection says nothing about the task
and everything about the minute you happened to ask in.

Until now the second kind propagated straight up and burned an attempt from
the stage budget, or ended the run. A single 429 partway through a sweep cost
six completed pairs on one occasion, none of which had anything wrong with
them.

What is NOT retried matters as much as what is. A depleted balance, a missing
key, a spend cap: retrying those wastes the caller's time to arrive at the same
answer more slowly, and the message already says exactly what to do.
"""
import random
import re
import time

# Substrings that mean "ask again in a moment". Matched against the exception
# text because the four provider SDKs raise four unrelated exception types for
# the same underlying condition, and importing all four to catch them would
# make an optional dependency mandatory.
TRANSIENT = (
    "429", "rate limit", "rate_limit", "too many requests",
    "500", "502", "503", "504", "internal error", "bad gateway",
    "service unavailable", "gateway timeout", "overloaded",
    "timeout", "timed out", "connection reset", "connection aborted",
    "temporarily unavailable", "try again",
)

# Substrings that mean "asking again will not help". Checked first, because
# several of these arrive wearing a 429.
PERMANENT = (
    "spending cap", "spend cap", "prepayment credits", "credits are depleted",
    "billing", "insufficient_quota",
    "invalid api key", "api key not valid", "unauthorized", "permission denied",
    "not found", "does not exist",
)

# Quota messages are the hard case: the same wording covers a per-minute rate
# limit that clears by itself and a monthly allowance that does not. Getting it
# wrong is expensive in both directions -- retrying a depleted balance wastes
# the whole budget on 429s, and giving up on a per-minute limit ends a run that
# would have succeeded thirty seconds later.
#
# So the PER-unit ones are read as transient and everything else about a quota
# is left to the tokens above. "quota exceeded for quota metric" used to sit in
# PERMANENT, which meant a per-minute rate limit killed the run outright.
RECOVERABLE_QUOTA = (
    "per minute", "per-minute", "perminute", "per second", "per day",
    "requests per", "retry after", "retrydelay",
)


def classify(error):
    """
    "permanent", "transient", or "unknown" for one exception.

    Unknown is not retried. An unrecognised failure is more likely to be a bug
    in the prompt or the code than a hiccup, and retrying a bug three times
    just makes it take three times as long to surface.
    """
    text = f"{type(error).__name__}: {error}".lower()
    if "quota" in text and any(t in text for t in RECOVERABLE_QUOTA):
        return "transient"
    for token in PERMANENT:
        if token in text:
            return "permanent"
    for token in TRANSIENT:
        if token in text:
            return "transient"
    return "unknown"


def retry_after_seconds(error):
    """
    An explicit wait the provider asked for, if it named one.

    Honouring it is both politer and faster than guessing: a provider that
    says 30 seconds means it, and backing off for 4 only to be refused again
    wastes an attempt.
    """
    m = re.search(r"retry[- _]?after[\"'\s:=]+(\d+(?:\.\d+)?)", str(error), re.I)
    if not m:
        m = re.search(r"retryDelay[\"'\s:=]+(\d+(?:\.\d+)?)s", str(error), re.I)
    if m:
        try:
            return min(float(m.group(1)), 120.0)
        except ValueError:
            return None
    return None


def backoff_seconds(attempt, error=None, base=2.0, cap=60.0, rng=None):
    """
    Exponential backoff with jitter, or whatever the provider asked for.

    Jitter matters when several tasks run concurrently, which is the normal
    case here: without it they all wait the same interval and retry in the
    same instant, reproducing the burst that caused the limit.
    """
    asked = retry_after_seconds(error) if error is not None else None
    if asked is not None:
        return asked
    rng = rng or random
    return min(base * (2 ** attempt), cap) * (0.5 + rng.random())


def with_retry(fn, attempts=4, sleep=time.sleep, rng=None, log=print):
    """
    Call fn(), retrying only transport failures.

    Returns fn()'s value, or re-raises the last error once the attempts are
    spent or the failure is one that retrying cannot fix.
    """
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            kind = classify(e)
            if kind != "transient" or attempt == attempts - 1:
                if kind == "permanent":
                    log(f"Provider refused for a reason retrying will not fix: {e}")
                raise
            wait = backoff_seconds(attempt, e, rng=rng)
            log(f"Transient provider error ({type(e).__name__}), retrying in "
                f"{wait:.1f}s [{attempt + 1}/{attempts - 1}]: {str(e)[:120]}")
            sleep(wait)
    raise last
