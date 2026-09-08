import os

from qikly.agent_api.providers.timeouts import request_timeout
from qikly.agent_api.providers import keys
from qikly.agent_api.usage import record_usage


from anthropic import Anthropic, APIError

DEFAULT_MODEL = "claude-sonnet-5"
# Anthropic requires an explicit output budget, and 4096 was wrong for a
# reasoning model. claude-sonnet-5 thinks before it answers, thinking tokens
# come out of this same budget, and a first real run spent the entire 4096 on
# thinking and returned no answer at all: stop_reason max_tokens, zero text
# blocks, nothing generated.
#
# 16384 comfortably fits a chain of thought plus a pytest file or a unified
# diff. Raising a cap is free in itself, since you are billed for tokens
# produced rather than for the ceiling, though a thinking model does produce
# more of them: expect Anthropic runs to cost more than the equivalent on a
# non-reasoning model.
#
# QIKLY_MAX_OUTPUT_TOKENS overrides it, because a bigger task or a chattier
# model should not need a source edit.
DEFAULT_MAX_OUTPUT_TOKENS = 16384
ENV_MAX_OUTPUT_TOKENS = "QIKLY_MAX_OUTPUT_TOKENS"


def max_output_tokens():
    raw = os.environ.get(ENV_MAX_OUTPUT_TOKENS)
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_OUTPUT_TOKENS


def call_anthropic(prompt, seed=None):
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY environment variable is not set (required for LLM_PROVIDER=anthropic)")

    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    client = Anthropic(api_key=api_key, timeout=request_timeout())

    # No determinism lever at all on this provider, and `seed` is accepted
    # here only so every provider has the same signature.
    #
    # Anthropic's Messages API has never had a seed parameter. It also no
    # longer takes `temperature`: SDK 1.x removed it from Messages.create(),
    # and passing it raises TypeError before a request is ever sent. So an
    # Anthropic run is not reproducible even best-effort, which matters when
    # comparing a rate measured here against one measured on Gemini.
    #
    # This was found by running against the installed SDK. A hand-written fake
    # accepted **kwargs and reported everything working, which is the exact
    # limit of testing an integration against a stand-in you wrote yourself.
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_output_tokens(),
            messages=[{"role": "user", "content": prompt}],
        )
    except APIError as e:
        raise RuntimeError(
            f"Anthropic API rejected the request: {e}. {keys.auth_hint('anthropic')} "
            f"It must be an active key."
        ) from e
    # Counted here rather than in the router: the router only sees the
    # text, and the token counts live on the SDK response object.
    record_usage(model, response)
    return _text_from(response)


def _text_from(response):
    """
    The text out of a Messages response, whatever else is in it.

    `response.content[0].text` was wrong and looked right for as long as every
    reply happened to start with a text block. claude-sonnet-5 returns extended
    thinking, so the first block is a ThinkingBlock, which carries `.thinking`
    and no `.text`, and the run died with an AttributeError before a single
    test had been generated.

    Selecting by type rather than by position is what makes this stable: a
    reply may contain thinking, redacted thinking, tool use or several text
    blocks in any order, and only the text ones are the answer. Joining rather
    than taking the first also means a reply split across blocks arrives whole
    instead of truncated at the first boundary.

    This is the failure class a signature check cannot see. The parameters were
    right, the call succeeded, and the shape of what came back had changed.
    """
    blocks = getattr(response, "content", None) or []
    parts = [b.text for b in blocks
             if getattr(b, "type", None) == "text" and getattr(b, "text", None)]
    if parts:
        return "\n".join(parts)

    # No text at all is worth reporting precisely, because the two likely
    # causes need opposite responses: a reply that was entirely thinking is a
    # retry, and a stop_reason of max_tokens needs a bigger budget.
    kinds = sorted({getattr(b, "type", "?") for b in blocks}) or ["nothing"]
    raise RuntimeError(
        f"Anthropic returned no text block. The reply contained: "
        f"{', '.join(kinds)}; stop_reason="
        f"{getattr(response, 'stop_reason', 'unknown')!r}. If that is "
        f"'max_tokens', raise it with {ENV_MAX_OUTPUT_TOKENS} "
        f"(currently {max_output_tokens():,}).")
