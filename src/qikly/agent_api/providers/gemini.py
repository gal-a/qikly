import os
from qikly.agent_api.usage import record_usage
from qikly.agent_api.providers.timeouts import timeout_milliseconds


from google import genai
from google.genai import types
from google.genai.errors import APIError

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_OUTPUT_TOKENS = 8192


def call_gemini(prompt, seed=None):
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY environment variable is not set (required for LLM_PROVIDER=gemini)")

    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    # Without a timeout this call waits forever on a stalled connection,
    # and a hang cannot be retried because it never raises. See timeouts.py.
    ms = timeout_milliseconds()
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=ms) if ms else None,
    )

    config_kwargs = {"max_output_tokens": MAX_OUTPUT_TOKENS}
    if seed is not None:
        # Best-effort reproducibility only -- no provider guarantees
        # bit-for-bit identical output even with temperature=0 and a fixed
        # seed. Applied the same way across every provider -- see README.
        config_kwargs["temperature"] = 0
        config_kwargs["seed"] = seed

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except APIError as e:
        raise RuntimeError(
            f"Gemini API rejected the request ({e.code} {e.status}): "
            f"{e.message.rstrip('.')}. If this looks like an auth error, check "
            f"API_KEY for typos/whitespace and that it's an active key from "
            f"Google AI Studio."
        ) from e

    finish_reason = response.candidates[0].finish_reason
    if finish_reason == types.FinishReason.MAX_TOKENS:
        raise RuntimeError(
            f"Gemini response was truncated (hit max_output_tokens={MAX_OUTPUT_TOKENS}). "
            "The prompt likely needs a larger output budget for this response."
        )

    # Counted here rather than in the router: the router only sees the
    # text, and the token counts live on the SDK response object.
    record_usage(model, response)
    return response.text
