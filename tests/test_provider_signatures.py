"""
Does the request we build match the SDK that is actually installed?

`test_providers_offline.py` runs each provider against a fake SDK, which checks
that the code assembles what it intends to. It cannot check that the intention
is still valid, because the fake accepts whatever it is given, and a fake you
wrote yourself agrees with you by construction.

That gap was not hypothetical. `anthropic` SDK 1.x removed `temperature` from
`Messages.create()`, so the provider raised TypeError before a request was ever
sent, while every fake-backed test reported it working. The bug had presumably
been there since the SDK's major bump, and nothing in the project could see it.

This file closes that gap the only way it can be closed without spending money:
by reading the signature of the SDK that is installed and comparing it against
the keyword arguments the provider sends.

## What it covers, and what still needs a paid call

It catches a **removed or renamed parameter**, which is the common breaking
change and the one that produces an immediate TypeError.

It does not catch a parameter that still exists and now means something
different, or a model name retired server-side. Those need one live call per
provider before a release, which is a release step rather than a test.

Every test here skips when the SDK is absent, because only the Gemini SDK is a
dependency. On a machine with all three installed, this is the file that fails
when an upstream bump breaks something.
"""
import inspect

import pytest


def _sdk(name):
    return pytest.importorskip(name, reason=f"{name} SDK not installed")


def _accepted(callable_obj):
    """Keyword names a callable takes, or None when it takes anything."""
    signature = inspect.signature(callable_obj)
    if any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values()):
        return None
    return set(signature.parameters)


def _sent_keywords(source, call_marker):
    """
    The keyword arguments a provider passes, read from its source.

    Source inspection rather than a recorded call, because the point is to
    compare intent against the SDK without running anything: a provider that
    raises TypeError on the way in never gets far enough to record.
    """
    import re

    body = source[source.index(call_marker):]
    depth, end = 0, None
    for i, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    return set(re.findall(r"(\w+)\s*=", body[:end]))


# ------------------------------------------------------------- anthropic ----

def test_anthropic_sends_only_what_messages_create_accepts():
    """
    The one that was broken. SDK 1.x dropped `temperature`, and sending it
    raises TypeError before any request leaves the process.
    """
    anthropic = _sdk("anthropic")
    from qikly.agent_api.providers import anthropic as provider

    accepted = _accepted(anthropic.Anthropic(api_key="x").messages.create)
    if accepted is None:
        pytest.skip("this SDK takes **kwargs, so nothing can be checked")
    sent = _sent_keywords(inspect.getsource(provider.call_anthropic),
                          "client.messages.create(")
    unknown = sent - accepted
    assert not unknown, (
        f"call_anthropic sends {sorted(unknown)}, which anthropic "
        f"{anthropic.__version__} does not accept. This raises TypeError "
        f"before a request is sent.")


def test_anthropic_client_accepts_the_timeout_we_pass():
    anthropic = _sdk("anthropic")
    accepted = _accepted(anthropic.Anthropic.__init__)
    assert accepted is None or "timeout" in accepted


def test_anthropic_has_no_determinism_lever_and_the_code_says_so():
    """
    No seed, and since 1.x no temperature either. An Anthropic run is not
    reproducible even best-effort, which matters when comparing a rate measured
    here against one measured on Gemini, so it is written down at the call site
    rather than left for someone to rediscover.
    """
    anthropic = _sdk("anthropic")
    from qikly.agent_api.providers import anthropic as provider

    accepted = _accepted(anthropic.Anthropic(api_key="x").messages.create)
    if accepted is not None:
        assert "seed" not in accepted
        assert "temperature" not in accepted
    source = inspect.getsource(provider.call_anthropic)
    assert "no determinism lever" in source.lower()


# ---------------------------------------------------------------- openai ----

def test_openai_sends_only_what_chat_completions_accepts():
    openai = _sdk("openai")
    from qikly.agent_api.providers import openai as provider

    accepted = _accepted(openai.OpenAI(api_key="x").chat.completions.create)
    if accepted is None:
        pytest.skip("this SDK takes **kwargs, so nothing can be checked")
    sent = _sent_keywords(inspect.getsource(provider.call_openai),
                          "client.chat.completions.create(")
    # kwargs is unpacked, so its contents are checked separately below.
    unknown = (sent - accepted) - {"kwargs"}
    assert not unknown, (
        f"call_openai sends {sorted(unknown)}, which openai "
        f"{openai.__version__} does not accept.")


def test_the_optional_openai_arguments_are_still_real():
    """
    `temperature` and `seed` go in through a dict, so the check above cannot
    see them. They are the two that carry the determinism claim, so they are
    named here explicitly.
    """
    openai = _sdk("openai")
    accepted = _accepted(openai.OpenAI(api_key="x").chat.completions.create)
    if accepted is None:
        pytest.skip("this SDK takes **kwargs")
    for name in ("temperature", "seed"):
        assert name in accepted, (
            f"openai {openai.__version__} no longer accepts {name!r}, so the "
            f"determinism claim in the README does not hold for this provider")


# ---------------------------------------------------------------- gemini ----

def test_gemini_sends_only_what_its_config_accepts():
    """
    The one provider every measurement in this project has gone through, so a
    break here would be noticed immediately. Checked anyway, because "we would
    notice" is what was true of Anthropic too.
    """
    genai = _sdk("google.genai")
    from qikly.agent_api.providers import gemini as provider

    accepted = _accepted(genai.types.GenerateContentConfig)
    if accepted is None:
        pytest.skip("this SDK takes **kwargs")
    sent = _sent_keywords(inspect.getsource(provider), "GenerateContentConfig(")
    unknown = sent - accepted - {"self"}
    assert not unknown, (
        f"the Gemini provider sets {sorted(unknown)}, which this "
        f"google-genai does not accept.")
