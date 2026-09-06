"""
The three providers that have never actually run.

`requirements.txt` carries only the Gemini SDK, so `openai` and `anthropic` are
not installed in this environment and never have been. Every sweep, every
measurement and every demo in this project's history went through one provider.
The other three are 131 lines that have compiled but not executed, and the only
signal that they work is that somebody wrote them carefully.

That is a bad position for code on the critical path of anyone who sets
`LLM_PROVIDER=openai`, so the SDKs are faked here. A fake module is installed
into `sys.modules` before the provider module is imported, which exercises the
real code against a stand-in that behaves the way the real client does.

## What this can and cannot tell you

It **can** tell you the request is assembled correctly: the right model, the
timeout applied, the seed and temperature set where the API supports them, the
response unwrapped from the right place, and an SDK error turned into a message
naming the likely cause. Those are the things that break silently and that a
user would experience as "it does not work".

It **cannot** tell you the real API accepts that request. A parameter renamed
upstream would pass here and fail in the wild. The way to catch that is a live
smoke test per provider, which needs four paid keys, and is worth doing once
before a release rather than on every commit.
"""
import sys
import types

import pytest


# ------------------------------------------------------------ fake SDKs ----

class FakeAPIError(Exception):
    """Stands in for the SDK's own error type, which the code catches by name."""


class _Recorder:
    """Captures how the client was constructed and called."""

    def __init__(self):
        self.init_kwargs = {}
        self.call_kwargs = {}
        self.raise_with = None


def _openai_module(recorder, text="hello"):
    """A stand-in for the `openai` package."""
    module = types.ModuleType("openai")

    class _Completions:
        def create(self, **kwargs):
            recorder.call_kwargs = kwargs
            if recorder.raise_with:
                raise recorder.raise_with
            message = types.SimpleNamespace(content=text)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(
                choices=[choice],
                usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                model="recorded",
            )

    class _Client:
        def __init__(self, **kwargs):
            recorder.init_kwargs = kwargs
            self.chat = types.SimpleNamespace(completions=_Completions())

    module.OpenAI = _Client
    module.APIError = FakeAPIError
    return module


def _anthropic_module(recorder, text="hello"):
    module = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **kwargs):
            recorder.call_kwargs = kwargs
            if recorder.raise_with:
                raise recorder.raise_with
            # A thinking block first, because that is what claude-sonnet-5
            # sends and what the fake used to omit. The old fake returned a
            # lone text block, agreed with the code, and hid a bug that killed
            # the first real Anthropic run before it generated one test.
            return types.SimpleNamespace(
                content=[
                    types.SimpleNamespace(type="thinking", thinking="reasoning"),
                    types.SimpleNamespace(type="text", text=text),
                ],
                stop_reason="end_turn",
                usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
                model="recorded",
            )

    class _Client:
        def __init__(self, **kwargs):
            recorder.init_kwargs = kwargs
            self.messages = _Messages()

    module.Anthropic = _Client
    module.APIError = FakeAPIError
    return module


@pytest.fixture
def sdk(monkeypatch):
    """
    Install fake SDKs and give back a factory that imports a provider fresh.

    The provider modules import their SDK at module level, so the fake has to
    be in place before the import and the module has to be evicted afterwards,
    or a later test gets the fake by accident.
    """
    recorder = _Recorder()
    monkeypatch.setenv("API_KEY", "test-key")

    def load(provider):
        monkeypatch.setitem(sys.modules, "openai", _openai_module(recorder))
        monkeypatch.setitem(sys.modules, "anthropic", _anthropic_module(recorder))
        name = f"qikly.agent_api.providers.{provider}"
        monkeypatch.delitem(sys.modules, name, raising=False)
        import importlib

        return importlib.import_module(name), recorder

    yield load
    for name in list(sys.modules):
        if name.startswith("qikly.agent_api.providers."):
            sys.modules.pop(name, None)


CASES = [
    ("openai", "call_openai", "gpt-4o"),
    ("anthropic", "call_anthropic", "claude-sonnet-5"),
]


# ----------------------------------------------------- the request shape ----

@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_the_response_text_is_unwrapped_from_the_right_place(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    Each SDK buries the text somewhere different: `choices[0].message.content`
    for OpenAI, `content[0].text` for Anthropic. Getting this wrong returns a
    repr of an object into the FIX loop, which then fails in a way that looks
    like the model being incoherent.
    """
    module, _ = sdk(provider)
    assert getattr(module, fn_name)("a prompt") == "hello"


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_the_default_model_is_used_when_nothing_overrides_it(
        provider, fn_name, default_model, sdk, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    module, recorder = sdk(provider)
    getattr(module, fn_name)("a prompt")
    assert recorder.call_kwargs["model"] == default_model
    assert module.DEFAULT_MODEL == default_model


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_llm_model_overrides_the_default(
        provider, fn_name, default_model, sdk, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "some-other-model")
    module, recorder = sdk(provider)
    getattr(module, fn_name)("a prompt")
    assert recorder.call_kwargs["model"] == "some-other-model"


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_the_request_timeout_is_applied(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    The setting that exists because a sweep once sat silent for two hours. A
    provider that forgot to pass it would reintroduce that failure for anyone
    using it, and nothing else in the system can notice a call that never
    returns.
    """
    module, recorder = sdk(provider)
    getattr(module, fn_name)("a prompt")
    assert "timeout" in recorder.init_kwargs
    assert recorder.init_kwargs["timeout"]


@pytest.mark.parametrize("provider,fn_name,default_model",
                         [c for c in CASES if c[0] != "anthropic"])
def test_a_seed_sets_temperature_zero_where_the_api_has_one(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    Determinism is best-effort and applied the same way wherever it is
    available, which is what makes two runs comparable at all.

    Anthropic is excluded, and the exclusion is the finding. This test used to
    cover all three and passed, because the fake accepted **kwargs. Against the
    installed SDK the same call raises TypeError: 1.x removed `temperature`
    from Messages.create(). A fake you wrote yourself agrees with you by
    construction, which is why tests/test_provider_signatures.py exists.
    """
    module, recorder = sdk(provider)
    getattr(module, fn_name)("a prompt", seed=7)
    assert recorder.call_kwargs.get("temperature") == 0


def test_anthropic_sends_no_sampling_parameters_at_all(sdk):
    """
    No seed, and since SDK 1.x no temperature either, so an Anthropic run is
    not reproducible even best-effort. Worth pinning rather than leaving as an
    absence: the natural tidy-up is to unify these three modules, and that
    would put `temperature` back and break the provider outright.
    """
    module, recorder = sdk("anthropic")
    module.call_anthropic("a prompt", seed=7)
    assert "temperature" not in recorder.call_kwargs
    assert "seed" not in recorder.call_kwargs


def test_only_the_providers_with_a_seed_parameter_send_one(sdk, monkeypatch):
    """
    Anthropic's Messages API has no seed. Sending one would be rejected, so the
    asymmetry is deliberate and worth pinning: someone tidying these three
    modules into a shared helper would naturally unify them and break it.
    """
    for provider, fn_name, _ in CASES:
        module, recorder = sdk(provider)
        getattr(module, fn_name)("a prompt", seed=7)
        if provider == "anthropic":
            assert "seed" not in recorder.call_kwargs
        else:
            assert recorder.call_kwargs["seed"] == 7


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_no_seed_means_no_temperature_override(
        provider, fn_name, default_model, sdk, monkeypatch):
    module, recorder = sdk(provider)
    getattr(module, fn_name)("a prompt")
    assert "temperature" not in recorder.call_kwargs


def test_anthropic_sends_a_max_tokens_because_its_api_requires_one(sdk, monkeypatch):
    module, recorder = sdk("anthropic")
    module.call_anthropic("a prompt")
    assert recorder.call_kwargs["max_tokens"] == module.max_output_tokens()


def test_the_output_budget_covers_thinking_as_well_as_the_answer(sdk):
    """
    4096 was wrong for a reasoning model. claude-sonnet-5 thinks before it
    answers, thinking comes out of the same budget, and a first real run spent
    the whole 4096 on it: stop_reason max_tokens, no text block, nothing
    generated. The budget has to fit a chain of thought plus a pytest file.
    """
    module, _ = sdk("anthropic")
    assert module.DEFAULT_MAX_OUTPUT_TOKENS >= 8192


def test_the_output_budget_is_overridable_without_editing_source(sdk, monkeypatch):
    module, recorder = sdk("anthropic")
    monkeypatch.setenv(module.ENV_MAX_OUTPUT_TOKENS, "32000")
    module.call_anthropic("a prompt")
    assert recorder.call_kwargs["max_tokens"] == 32000


def test_a_nonsense_budget_falls_back_rather_than_failing_the_run(sdk, monkeypatch):
    module, recorder = sdk("anthropic")
    monkeypatch.setenv(module.ENV_MAX_OUTPUT_TOKENS, "lots")
    module.call_anthropic("a prompt")
    assert recorder.call_kwargs["max_tokens"] == module.DEFAULT_MAX_OUTPUT_TOKENS


# --------------------------------------------------------- the failures ----

@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_a_missing_api_key_names_the_variable_and_the_provider(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    The most common first failure with any of these. A message naming both the
    variable and which provider wanted it is the difference between a fix and
    a support thread.
    """
    module, _ = sdk(provider)
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(RuntimeError) as caught:
        getattr(module, fn_name)("a prompt")
    assert "API_KEY" in str(caught.value)
    assert provider in str(caught.value)


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_an_sdk_error_becomes_a_message_that_suggests_a_cause(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    A raw SDK traceback tells a user nothing actionable. Every provider catches
    its own error type and re-raises with the likeliest cause named, which for
    all of these is a bad key.
    """
    module, recorder = sdk(provider)
    recorder.raise_with = FakeAPIError("401 Unauthorized")
    with pytest.raises(RuntimeError) as caught:
        getattr(module, fn_name)("a prompt")
    message = str(caught.value)
    assert "401 Unauthorized" in message, "the original error must survive"
    assert "API_KEY" in message, "and the message must say what to check"


@pytest.mark.parametrize("provider,fn_name,default_model", CASES)
def test_usage_is_recorded_so_a_run_can_report_what_it_spent(
        provider, fn_name, default_model, sdk, monkeypatch):
    """
    Recorded inside each provider, because the router only ever sees the text
    and the token counts live on the SDK response object. A provider that
    forgot this would report a cost of zero for real spend.
    """
    from qikly.agent_api.usage import USAGE

    module, _ = sdk(provider)
    before = USAGE.as_dict()["calls"]
    getattr(module, fn_name)("a prompt")
    assert USAGE.as_dict()["calls"] == before + 1


# ------------------------------------------------------------ the router ----

def test_a_missing_sdk_names_the_package_to_install(monkeypatch):
    """
    Only the Gemini SDK is in requirements.txt, so choosing another provider on
    a fresh install hits this path first. It must say which package, not raise
    an ImportError from three frames down.
    """
    from qikly.agent_api.providers import router

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.delitem(sys.modules, "qikly.agent_api.providers.openai", raising=False)
    with pytest.raises(RuntimeError) as caught:
        router._resolve_call_fn("openai")
    message = str(caught.value)
    assert "openai" in message.lower()
    assert "install" in message.lower(), "it must say what to do, not only what broke"


def test_an_unknown_provider_lists_the_ones_that_exist(monkeypatch):
    from qikly.agent_api.providers import router

    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    with pytest.raises(RuntimeError) as caught:
        router.validate_config()
    message = str(caught.value)
    assert "not-a-provider" in message
    for known in ("gemini", "openai", "anthropic"):
        assert known in message
    assert "azure" not in message, (
        "azure was dropped; a provider listed as supported but absent sends "
        "someone down a path that ends in ImportError")


# ------------------------------- the Anthropic response shape --------------

def _blocks(*specs):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(**spec) for spec in specs],
        stop_reason="end_turn")


def test_text_is_found_after_a_thinking_block():
    """
    The failure that killed the first real Anthropic run.
    `response.content[0].text` looked right for as long as every reply began
    with text. claude-sonnet-5 returns extended thinking, so block zero is a
    ThinkingBlock carrying `.thinking` and no `.text`, and the run died with an
    AttributeError before generating a single test.
    """
    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from qikly.agent_api.providers.anthropic import _text_from

    got = _text_from(_blocks({"type": "thinking", "thinking": "hmm"},
                             {"type": "text", "text": "the answer"}))
    assert got == "the answer"


def test_blocks_are_selected_by_type_not_position():
    """
    A reply can carry thinking, redacted thinking and tool use in any order.
    Position is not a contract; type is.
    """
    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from qikly.agent_api.providers.anthropic import _text_from

    got = _text_from(_blocks({"type": "redacted_thinking"},
                             {"type": "tool_use"},
                             {"type": "text", "text": "the answer"}))
    assert got == "the answer"


def test_text_split_across_blocks_arrives_whole():
    """
    Taking the first text block would silently truncate a reply at a boundary
    the model chose, which for a unified diff means a patch that will not apply
    and a failure that reads as the model being bad at diffs.
    """
    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from qikly.agent_api.providers.anthropic import _text_from

    got = _text_from(_blocks({"type": "text", "text": "part one"},
                             {"type": "text", "text": "part two"}))
    assert got == "part one\npart two"


def test_a_reply_with_no_text_names_the_likely_cause():
    """
    The two causes need opposite responses: an all-thinking reply is a retry,
    and stop_reason max_tokens needs a bigger budget. An AttributeError names
    neither.
    """
    import pytest as _pytest

    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from qikly.agent_api.providers.anthropic import _text_from

    response = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="thinking", thinking="x")],
        stop_reason="max_tokens")
    with _pytest.raises(RuntimeError) as caught:
        _text_from(response)
    message = str(caught.value)
    assert "thinking" in message
    assert "max_tokens" in message
    assert "MAX_OUTPUT_TOKENS" in message


def test_an_empty_reply_does_not_raise_an_index_error():
    import pytest as _pytest

    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from qikly.agent_api.providers.anthropic import _text_from

    with _pytest.raises(RuntimeError):
        _text_from(types.SimpleNamespace(content=[], stop_reason="end_turn"))
