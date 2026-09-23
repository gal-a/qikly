"""
The run says, before the silence starts, that every call will think.

A reasoning model is a reasonable choice and a surprising default: one demo
task that finishes in under a minute on the Gemini default took about sixteen
on Anthropic's, and the console printed nothing throughout, which reads as a
hang rather than as a model thinking. The banner now says so.

Deliberately not a warning, and deliberately quiet for models that do not
reason: a notice that appears when nothing is unusual is a notice people learn
to skip, and the next one that matters goes with it.
"""
import pytest

from qikly.agent_api.providers.router import (effective_model, speed_notice,
                                              thinks_before_answering)


@pytest.mark.parametrize("provider,model,thinks", [
    ("anthropic", "claude-sonnet-5", True),
    ("anthropic", "claude-opus-5", True),
    ("anthropic", "claude-haiku-4-5", False),
    # On Gemini the flash line is the fast one and everything else reasons,
    # pro included. Listing the reasoning models instead would go stale on the
    # next release and call a thinking model fast, which is the wrong way to
    # be wrong.
    ("gemini", "gemini-3.5-flash-lite", False),
    ("gemini", "gemini-3.5-flash", False),
    ("gemini", "gemini-3.5-pro", True),
    ("gemini", "gemini-9-pro-whatever-comes-next", True),
    ("openai", "gpt-4o", False),
    ("openai", "o3-mini", True),
])
def test_which_models_reason_before_answering(provider, model, thinks):
    assert thinks_before_answering(provider, model) is thinks


def test_the_anthropic_default_is_a_thinking_model_and_says_so(monkeypatch):
    """The case that prompted this: the default nobody chose."""
    monkeypatch.delenv("LLM_MODEL", raising=False)

    model = effective_model("anthropic")
    assert model == "claude-sonnet-5"

    notice = speed_notice("anthropic", model)
    assert notice, "the default Anthropic model reasons and the run said nothing"
    text = " ".join(notice)
    assert model in text
    assert "minutes rather than" in text
    assert "claude-haiku-4-5" in text, "say which model is the fast one"


def test_nothing_is_printed_for_a_model_that_does_not_reason(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert speed_notice("gemini", effective_model("gemini")) == []


def test_naming_a_model_overrides_the_provider_default(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5")
    model = effective_model("anthropic")
    assert model == "claude-haiku-4-5"
    assert speed_notice("anthropic", model) == [], (
        "choosing the fast model should not then be told to choose it")


def test_a_pro_model_on_gemini_is_not_treated_as_the_fast_one():
    """
    The first version of this listed the reasoning models by name, so every
    Gemini model except a couple was reported as fast. A release named
    anything new would have been called fast while it reasoned.
    """
    notice = speed_notice("gemini", "gemini-3.5-pro")
    assert notice, "a pro model reasons and the run should say so"
    assert "flash" in " ".join(notice), "say which line is the fast one"


def test_an_unknown_provider_says_nothing():
    """Silence is the safe answer where there is nothing known to say."""
    assert speed_notice("something-else", "some-model") == []
