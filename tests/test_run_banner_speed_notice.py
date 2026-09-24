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


def test_the_default_model_is_known_without_the_optional_sdks(monkeypatch):
    """
    CI installs qikly plain. Two of the three provider SDKs are extras.

    This test's neighbour above asserted that the Anthropic default is
    `claude-sonnet-5`, and it passed on a machine with all three SDKs
    installed and failed in CI, where importing the Anthropic provider module
    is impossible. `effective_model` had been reaching the default by
    importing that module, so it answered `<provider default>` and the run
    banner named no model at all.

    So this asks the question the way CI does, by making the optional SDKs
    unimportable first.
    """
    import importlib
    import sys

    class Blocked:
        def find_module(self, name, path=None):
            return self if name.split(".")[0] in ("anthropic", "openai") else None

        def load_module(self, name):
            raise ImportError("optional SDK not installed")

    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(sys, "meta_path", [Blocked()] + list(sys.meta_path))
    for name in [m for m in sys.modules if m.split(".")[0] in ("anthropic", "openai")]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    from qikly.agent_api.providers import router
    importlib.reload(router)

    assert router.effective_model("anthropic") == "claude-sonnet-5"
    assert router.effective_model("openai") == "gpt-4o"
    assert router.effective_model("gemini") == "gemini-3.5-flash-lite"


def test_no_provider_restates_its_default_model_as_a_literal():
    """
    One source of truth, checked without importing anything.

    The first version of this imported each provider module to compare its
    DEFAULT_MODEL against the table, and two of the three modules cannot be
    imported without an optional SDK. It therefore failed in CI for exactly
    the condition the table exists to handle, which is a neat demonstration of
    the trap and a poor test.

    So this reads the source. What matters is not the value, which the table
    already holds, but that each module takes it from the table instead of
    writing it out again: a literal here and a literal there is how the run
    banner and the provider come to disagree about what a run is using.
    """
    import ast
    import os

    from qikly.agent_api.providers import defaults

    providers_dir = os.path.dirname(os.path.abspath(defaults.__file__))
    checked = []

    for provider in sorted(defaults.DEFAULT_MODELS):
        path = os.path.join(providers_dir, "%s.py" % provider)
        assert os.path.isfile(path), "no module for provider %r" % provider
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        assignments = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "DEFAULT_MODEL"
                    for t in node.targets)
        ]
        assert len(assignments) == 1, (
            "%s should set DEFAULT_MODEL exactly once, found %d"
            % (provider, len(assignments)))

        value = assignments[0].value
        assert isinstance(value, ast.Subscript), (
            "%s.py sets DEFAULT_MODEL to a literal again. Read it from "
            "providers/defaults.py, or the banner and the provider will "
            "disagree about which model a run used." % provider)
        assert isinstance(value.value, ast.Name) and value.value.id == "DEFAULT_MODELS", (
            "%s.py should subscript DEFAULT_MODELS" % provider)
        checked.append(provider)

    assert checked == sorted(defaults.DEFAULT_MODELS), checked


def test_the_table_and_the_importable_provider_agree():
    """
    The value itself, for the one provider a plain install can import.

    Gemini is a required dependency, so this runs everywhere. The other two are
    covered by the source check above, which needs no SDK.
    """
    from qikly.agent_api.providers import defaults, gemini

    assert gemini.DEFAULT_MODEL == defaults.DEFAULT_MODELS["gemini"]
