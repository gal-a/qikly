import os
from qikly.agent_api.providers import keys
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
    # qikly sends no tools, so automatic function calling has nothing to call.
    # The SDK still turns it on by default and warns, once per process, that
    # using AFC through generate_content is not recommended. That warning
    # reached every user's console and the demo recording, describing a feature
    # this code does not use. Disabling it is the honest fix; silencing the
    # logger would only hide it. Guarded, because the config type is not in
    # every version the dependency range allows.
    if hasattr(types, "AutomaticFunctionCallingConfig"):
        config_kwargs["automatic_function_calling"] = (
            types.AutomaticFunctionCallingConfig(disable=True))
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
            f"{e.message.rstrip('.')}. {keys.auth_hint('gemini')} "
            f"It must be an active key from Google AI Studio."
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
