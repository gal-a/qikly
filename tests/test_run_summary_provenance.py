"""
Does a run summary name the model that actually ran?

The bug pinned here, found on 2026-09-08 by running the demo against OpenAI.
`settings.yaml` pairs a provider with a model:

    agents:
      default:
        provider: gemini
        model: gemini-3.5-flash-lite

and `_provenance` read the two independently, environment first, settings
second. Setting `LLM_PROVIDER=openai` and leaving `LLM_MODEL` alone therefore
recorded `provider: openai` with `model: gemini-3.5-flash-lite`, which is not a
configuration that can exist. The usage report for that same run, which takes
the model string the SDK was actually handed, said `gpt-4o` for all 24 calls.

Why this one matters more than it looks. Every stored figure in this project
carries its model, because a convergence rate belongs to a model and a
configuration as much as to the tool. A summary that names the wrong model does
not fail loudly, it quietly attributes one model's numbers to another, and the
research harnesses read these files.
"""
import pytest

from qikly.agent_api.providers import router as R
from qikly.orchestrator import run_summary as RS


SETTINGS = {"agents": {"default": {"provider": "gemini",
                                   "model": "gemini-3.5-flash-lite"}}}


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "qikly.orchestrator.orchestrator.load_settings", lambda *a, **k: SETTINGS,
        raising=False)
    return monkeypatch


# ------------------------------------------------- what a provider defaults to

@pytest.mark.parametrize("provider,expected", [
    ("gemini", "gemini-3.5-flash-lite"),
    ("openai", "gpt-4o"),
    ("anthropic", "claude-sonnet-5"),
])
def test_each_provider_reports_its_own_default_model(provider, expected):
    got = R.default_model_for(provider)
    if got is None:
        pytest.skip(f"{provider} SDK not installed, so its module cannot be imported")
    assert got == expected


def test_an_unknown_provider_yields_none_rather_than_raising():
    assert R.default_model_for("a-provider-added-later") is None


# ---------------------------------------------------------------- provenance

def test_switching_provider_alone_does_not_keep_the_old_model(clean_env):
    """The regression. provider=openai with a gemini model is impossible."""
    if R.default_model_for("openai") is None:
        pytest.skip("openai SDK not installed")
    clean_env.setenv("LLM_PROVIDER", "openai")
    out = RS._provenance()
    assert out["provider"] == "openai"
    assert out["model"] == "gpt-4o"
    assert "gemini" not in (out["model"] or ""), (
        "the settings default's model belongs to the settings default's provider"
    )


def test_the_settings_default_is_used_when_nothing_switched(clean_env):
    out = RS._provenance()
    assert out["provider"] == "gemini"
    assert out["model"] == "gemini-3.5-flash-lite"


def test_an_explicit_model_always_wins(clean_env):
    clean_env.setenv("LLM_PROVIDER", "openai")
    clean_env.setenv("LLM_MODEL", "gpt-4o-mini")
    out = RS._provenance()
    assert out["provider"] == "openai"
    assert out["model"] == "gpt-4o-mini"


def test_naming_the_same_provider_keeps_the_settings_model(clean_env):
    """Setting LLM_PROVIDER to what settings already says changes nothing."""
    clean_env.setenv("LLM_PROVIDER", "gemini")
    out = RS._provenance()
    assert out["model"] == "gemini-3.5-flash-lite"


def test_provider_and_model_are_never_from_different_providers(clean_env):
    """
    The invariant, stated once. Whatever the environment says, the recorded
    model must be one that the recorded provider could actually have used.
    """
    for provider in ("gemini", "openai", "anthropic"):
        if R.default_model_for(provider) is None:
            continue
        clean_env.setenv("LLM_PROVIDER", provider)
        out = RS._provenance()
        assert out["model"] == R.default_model_for(provider), (
            f"{out['provider']} recorded with {out['model']}"
        )


def test_provenance_never_raises_even_with_settings_broken(monkeypatch):
    """
    A run that produced real output must not fail while recording what produced
    it. The docstring promises this; the new lookup must not break it.
    """
    def boom(*a, **k):
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr("qikly.orchestrator.orchestrator.load_settings", boom,
                        raising=False)
    out = RS._provenance()
    assert "recorded_at" in out, "the timestamp survives whatever else fails"
