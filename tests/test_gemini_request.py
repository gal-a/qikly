"""
What the Gemini provider actually sends.

`test_providers_offline.py` covers OpenAI and Anthropic against fake SDKs and
stops there, because Gemini's SDK is a hard dependency rather than an optional
one. The effect was that the **default** provider, the one every first run
uses, had no offline test of its request shape at all. This file closes that.

The specific thing that prompted it: every run printed

    Direct use of automatic function calling (AFC) in Models.generate_content
    is not recommended. Instead, we recommend to use AFC in Chat.send_message.

qikly sends no tools, so AFC had nothing to call. The SDK enables it by default
and warns once per process, and that warning reached every user's console and
the recorded demo, describing a feature this code does not use. It is now
switched off at the source rather than filtered out of the log.
"""
import pytest

from qikly.agent_api.providers import gemini as G


class _Recorder:
    """Stands in for genai.Client and keeps what it was handed."""

    def __init__(self, **kwargs):
        self.client_kwargs = kwargs
        self.models = self
        _Recorder.last = self

    def generate_content(self, model=None, contents=None, config=None):
        self.model, self.contents, self.config = model, contents, config
        return _Reply()


class _Reply:
    text = "a reply"

    class _Candidate:
        finish_reason = "STOP"

    candidates = [_Candidate()]
    usage_metadata = None


@pytest.fixture
def sent(monkeypatch):
    """Call the provider with a fake SDK and give back the config it built."""
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(G.genai, "Client", _Recorder)

    def call(**kwargs):
        G.call_gemini("a prompt", **kwargs)
        return _Recorder.last

    return call


def test_the_prompt_and_default_model_are_sent(sent):
    r = sent()
    assert r.contents == "a prompt"
    assert r.model == G.DEFAULT_MODEL


def test_llm_model_overrides_the_default(sent, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemini-9-experimental")
    assert sent().model == "gemini-9-experimental"


def test_the_output_budget_is_always_sent(sent):
    assert sent().config.max_output_tokens == G.MAX_OUTPUT_TOKENS


def test_automatic_function_calling_is_disabled(sent):
    """
    The regression. qikly passes no tools, so leaving AFC on bought nothing and
    cost every user a warning about a feature they were not using.
    """
    afc = sent().config.automatic_function_calling
    assert afc is not None, "AFC must be explicitly configured, not left default"
    assert afc.disable is True


def test_a_seed_sets_temperature_zero(sent):
    cfg = sent(seed=42).config
    assert cfg.seed == 42
    assert cfg.temperature == 0


def test_no_seed_means_no_temperature_override(sent):
    """Sending temperature=0 unasked would change behaviour, not just repeat it."""
    cfg = sent().config
    assert cfg.seed is None
    assert cfg.temperature is None


def test_a_missing_key_is_refused_before_the_sdk_is_touched(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    def explode(**kwargs):
        raise AssertionError("the SDK must not be constructed without a key")

    monkeypatch.setattr(G.genai, "Client", explode)
    with pytest.raises(RuntimeError) as caught:
        G.call_gemini("a prompt")
    assert "API_KEY" in str(caught.value)
