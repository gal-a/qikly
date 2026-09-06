"""
Provider and model selection per agent.

The bug pinned here: _ensure_api_key normalises a provider's conventional key
variable into API_KEY and deliberately never overwrites an API_KEY that is
already set. That is correct when one provider serves the whole run, and a
silent failure the moment two roles use two providers, because the second call
receives the first provider's key and fails to authenticate for reasons the
error message does not explain.
"""
import os

import pytest

from qikly.agent_api.providers import router as R


def test_every_mode_maps_to_a_role():
    """A call site passing an unmapped mode would silently fall back to default."""
    for mode in ("fix", "patch", "test_integration", "test_system", "test_unit",
                 "acceptance_criteria", "acceptance_criteria_review"):
        assert mode in R._MODE_ROLE, f"{mode} has no role"


def test_the_four_agents_are_separately_addressable():
    roles = set(R._MODE_ROLE.values())
    assert {"code", "criteria", "review"} <= roles
    assert {"test_integration", "test_system", "test_unit"} <= roles


def test_criteria_and_review_are_not_the_same_role():
    """They are different agents with different prompts, so different models."""
    assert R._MODE_ROLE["acceptance_criteria"] != R._MODE_ROLE["acceptance_criteria_review"]


def test_selection_applies_then_restores():
    with R._selected({"provider": "anthropic", "model": "claude-sonnet-5"}):
        assert os.environ["LLM_PROVIDER"] == "anthropic"
        assert os.environ["LLM_MODEL"] == "claude-sonnet-5"
    assert "LLM_PROVIDER" not in os.environ
    assert "LLM_MODEL" not in os.environ


def test_an_exported_environment_variable_wins(monkeypatch):
    """Settings configure the default arrangement; the environment overrides it."""
    monkeypatch.setenv("LLM_MODEL", "chosen-by-hand")
    with R._selected({"provider": "anthropic", "model": "from-settings"}):
        assert os.environ["LLM_MODEL"] == "chosen-by-hand"


def test_switching_provider_switches_the_api_key(monkeypatch):
    """The regression: Anthropic must not be handed the Gemini key."""
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    R._ensure_api_key("gemini")
    assert os.environ["API_KEY"] == "gem-key"

    with R._selected({"provider": "anthropic"}):
        assert os.environ["API_KEY"] == "ant-key"
    assert os.environ["API_KEY"] == "gem-key"


def test_missing_key_for_a_role_does_not_clobber_the_current_one(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    R._ensure_api_key("gemini")
    with R._selected({"provider": "anthropic"}):
        # No ANTHROPIC_API_KEY is set, so nothing was substituted. Failing at
        # the call with a clear error beats silently sending the wrong key.
        assert os.environ["API_KEY"] == "gem-key"


def test_no_config_is_a_no_op():
    before = dict(os.environ)
    with R._selected({}):
        pass
    assert dict(os.environ) == before


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
def test_every_provider_is_routable_and_reads_a_model(provider):
    assert provider in R._PROVIDERS
    module_name, fn_name, _ = R._PROVIDERS[provider]
    # Read the source rather than import it. Only one provider SDK is installed
    # at a time by design, so importing would make this test pass or fail on
    # which extras happen to be present rather than on the contract.
    import os
    import qikly
    path = os.path.join(os.path.dirname(os.path.dirname(qikly.__file__)),
                        *module_name.split(".")) + ".py"
    assert os.path.exists(path), f"{provider} module missing at {path}"
    src = open(path, encoding="utf-8").read()
    assert f"def {fn_name}(" in src, f"{provider} has no {fn_name}"
    assert "DEFAULT_MODEL" in src, f"{provider} declares no default model"
    assert "LLM_MODEL" in src, f"{provider} ignores LLM_MODEL, so per-agent models do not reach it"


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
def test_every_provider_has_a_conventional_key_variable(provider):
    assert R._KEY_VARS.get(provider), f"{provider} has no key variable, so a role cannot switch to it"


# ------------------------------- the default, and when it steps aside ------

def test_gemini_stays_the_default_when_it_can_work(monkeypatch):
    """
    The default is not arbitrary. Gemini is the only provider with a free tier
    that needs no card, it is roughly twenty times cheaper than the others, its
    SDK is the one hard dependency, and every published convergence figure was
    measured on it. Someone with a Gemini key should get exactly that.
    """
    for name in ("LLM_PROVIDER", "API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    assert R._resolve_provider_name() == "gemini"


def test_a_lone_other_key_is_used_rather_than_demanding_a_gemini_one(monkeypatch, capsys):
    """
    The friction this removes. Someone whose only key is OPENAI_API_KEY used to
    be told to go and get a different key from a different company before they
    could see the tool run once, which is a poor trade for a first impression.
    """
    for name in ("LLM_PROVIDER", "API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert R._resolve_provider_name() == "openai"
    assert "Using openai" in capsys.readouterr().out


def test_the_inference_is_announced_every_time(monkeypatch, capsys):
    """
    A tool that silently picks a provider silently picks who gets billed, and
    the question after an unexpected charge is which one it used.
    """
    for name in ("LLM_PROVIDER", "API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    R._resolve_provider_name()
    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "LLM_PROVIDER" in out, "it must say how to make the choice explicit"


def test_two_candidates_are_not_guessed_between(monkeypatch):
    """
    Choosing between two configured providers is picking whose bill to run up.
    With no basis to decide, the old error is the right answer.
    """
    for name in ("LLM_PROVIDER", "API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert R._inferred_provider() is None
    assert R._resolve_provider_name() == "gemini"


def test_an_explicit_choice_is_never_overridden(monkeypatch):
    for name in ("API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert R._resolve_provider_name() == "gemini"


def test_a_generic_api_key_belongs_to_the_default(monkeypatch):
    """
    API_KEY says nothing about which provider it is for, so it is the default's
    to use. Inferring from another provider's variable while a generic key sits
    unused would send that key to the wrong company.
    """
    for name in ("LLM_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("API_KEY", "generic")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert R._inferred_provider() is None


# ------------------------------- a model belongs to its provider -----------

def test_a_settings_model_is_dropped_when_the_provider_is_overridden(monkeypatch):
    """
    A real failure, found by running it. settings.yaml said gemini plus
    gemini-3.5-flash-lite, the user exported LLM_PROVIDER=openai, and the
    provider override was correctly skipped while the model override was not.
    OpenAI was asked for `gemini-3.5-flash-lite` and answered, accurately and
    uselessly, that no such model exists.

    The two are a pair. Either both settings values apply or neither does.
    """
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with R._selected({"provider": "gemini", "model": "gemini-3.5-flash-lite"}):
        assert os.environ.get("LLM_PROVIDER") == "openai"
        assert os.environ.get("LLM_MODEL") is None, (
            "a model from a different provider's settings reached the call")


def test_settings_still_apply_when_nothing_is_exported(monkeypatch):
    """The other side: without an override, the settings file is in charge."""
    for name in ("LLM_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    with R._selected({"provider": "gemini", "model": "gemini-3.5-flash-lite"}):
        assert os.environ.get("LLM_PROVIDER") == "gemini"
        assert os.environ.get("LLM_MODEL") == "gemini-3.5-flash-lite"


def test_a_role_naming_only_a_model_still_gets_it(monkeypatch):
    """
    A model with no provider beside it is meant for whichever provider ends up
    running, so overriding the provider must not discard it. Dropping this case
    too would quietly ignore a per-role model choice.
    """
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    with R._selected({"model": "gpt-4o-mini"}):
        assert os.environ.get("LLM_MODEL") == "gpt-4o-mini"


def test_every_provider_default_model_has_a_price():
    """
    The cost forecast is the last thing shown before a run spends money, and an
    unpriced default made it say "no price on file for gpt-4o" about qikly's
    own OpenAI default. A default nobody priced is a default nobody costed.
    """
    import importlib

    from qikly.agent_api.usage import PRICES

    checked = []
    for provider in R._PROVIDERS:
        try:
            module = importlib.import_module(f"qikly.agent_api.providers.{provider}")
        except ModuleNotFoundError:
            # Only the Gemini SDK is a dependency. The others are extras, and a
            # bare `pip install qikly` has to leave the suite green.
            continue
        checked.append(provider)
        default = module.DEFAULT_MODEL
        assert default in PRICES, (
            f"{provider}'s default model {default!r} is not in the price table, "
            f"so --demo cannot estimate what a run will cost")
    assert checked, 'no provider SDK was importable, so this checked nothing'
