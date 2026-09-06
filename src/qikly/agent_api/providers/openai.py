import os

from qikly.agent_api.providers.timeouts import request_timeout
from qikly.agent_api.usage import record_usage


from openai import APIError, OpenAI

DEFAULT_MODEL = "gpt-4o"


def call_openai(prompt, seed=None):
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY environment variable is not set (required for LLM_PROVIDER=openai)")

    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, timeout=request_timeout())

    kwargs = {}
    if seed is not None:
        # Best-effort reproducibility only, applied the same way across
        # every provider -- see README.
        kwargs["temperature"] = 0
        kwargs["seed"] = seed

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
    except APIError as e:
        raise RuntimeError(
            f"OpenAI API rejected the request: {e}. If this looks like an auth "
            f"error, check API_KEY for typos/whitespace and that it's an active key."
        ) from e
    # Counted here rather than in the router: the router only sees the
    # text, and the token counts live on the SDK response object.
    record_usage(model, response)
    return response.choices[0].message.content
