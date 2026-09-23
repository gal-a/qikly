import os
import time

from qikly.agent_api.providers.router import (effective_model, route_model,
                                              thinks_before_answering)
from qikly.agent_api.retry import with_retry

# A call slower than this is worth a line of its own.
#
# The run prints per iteration, not per call, so on a reasoning model the
# console can sit silent for minutes and read as a hang. It did: a demo task
# that takes under a minute on a flash model took about sixteen on the
# Anthropic default, with nothing printed throughout, and the person watching
# reasonably concluded it had stopped.
#
# 45 seconds is well past any call on a fast model and well short of a
# reasoning model's normal pace, so this stays quiet unless something really is
# taking a while.
SLOW_CALL_SECONDS = 45.0

# The advice belongs on the first slow call only. Every call after that is slow
# for the same reason, and repeating the paragraph seven times is how a message
# stops being read. One process per task, so this is per task, which is right:
# each task's output is read on its own.
_advice_given = False


def _note_if_slow(mode, elapsed):
    """One line after a slow call, and the reason once."""
    global _advice_given

    if elapsed < SLOW_CALL_SECONDS:
        return
    print("  [%s] that call took %.0fs" % (mode, elapsed))

    if _advice_given:
        return
    _advice_given = True

    provider = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    model = effective_model(provider)
    if thinks_before_answering(provider, model):
        faster = ("claude-haiku-4-5" if provider == "anthropic"
                  else "a flash model, such as gemini-3.5-flash-lite")
        print("  %s reasons before it answers, and a run makes one call per"
              % model)
        print("  stage per iteration, so expect this for every call of this")
        print("  run. For fast runs set LLM_MODEL=%s." % faster)
    else:
        print("  That is slower than this model usually answers in. It is")
        print("  abandoned at QIKLY_REQUEST_TIMEOUT seconds (300 by default)")
        print("  and retried, so a call that is merely slow rather than stuck")
        print("  is thrown away and paid for twice. Raise it if this repeats.")


def call_llm(mode, prompt, seed=None):
    """
    Unified entry point for all LLM calls. Every mode is sent to the single
    provider configured via LLM_PROVIDER (see agent_api/providers/router.py).
    mode: "fix", "patch", "test_integration", "test_system", or "test_unit"
    prompt: fully constructed prompt string
    seed: optional int for best-effort reproducible output
    """
    # Transport failures are retried here; bad answers are not. A rate limit
    # or a gateway error says nothing about the task, and letting it through
    # spends an attempt from the stage budget on a problem the model never
    # saw. A refusal that retrying cannot fix, a depleted balance or a bad
    # key, is raised immediately with its own message intact.
    started = time.monotonic()
    answer = with_retry(lambda: route_model(mode, prompt, seed=seed))
    # After the answer, not in a finally: a call that failed has an error of
    # its own to print, and how long it took before failing is not the thing
    # to say about it.
    _note_if_slow(mode, time.monotonic() - started)
    return answer
