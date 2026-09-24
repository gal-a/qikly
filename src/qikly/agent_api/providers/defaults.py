"""
Each provider's default model, readable without importing that provider's SDK.

Two of the three SDKs are optional extras, so `qikly` installed plain can only
import the Gemini provider. Anything that reaches a default model by importing
the provider module therefore works on a developer machine with all three
installed and returns nothing in CI, which is exactly how it failed: the run
banner named `<provider default>` instead of the model, and the test that
caught it passed locally for the same reason it failed remotely.

So the literals live here, in a module that imports nothing. Each provider
still exposes `DEFAULT_MODEL` and reads it from this table, so there is one
place to change a default and no copy to drift, which is what putting a second
hardcoded dict in `router` cost the last time.
"""

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash-lite",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-5",
}


def default_model(provider):
    """The default model for a provider, or None if it is not one of ours."""
    return DEFAULT_MODELS.get(provider)
