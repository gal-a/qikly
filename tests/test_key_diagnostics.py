"""
What the user is told when a provider refuses the credential.

The failure this file pins, hit on release day with a real key. `GEMINI_API_KEY`
held a valid key with one stray printable character in front of it, 54 rather
than 53. Gemini answered 401 UNAUTHENTICATED, and the message told the user to
check `API_KEY` for typos: a variable they had never set and which was not set
at all. Nothing in the error named the variable the key had actually come from,
or its length, so there was no way to see the extra character.

Two behaviours come out of that, and they are deliberately different in kind:

  refusal   only for characters no provider's key ever contains, before any
            model call is made
  hint      length, source variable and expected shape, only after the
            provider has already said no

The split matters. A refusal that has aged badly costs the user their whole
run; a hint that has aged badly costs a sentence. So shape never refuses.
"""
import os

import pytest

from qikly.agent_api.providers import keys
from qikly.agent_api.providers import router as R


REAL_SHAPES = [
    "AIza" + "b" * 35,          # Google AI Studio, older format, 39
    "AQ.Ab8" + "c" * 47,        # Google AI Studio, newer format, 53
    "sk-proj-" + "d" * 40,      # OpenAI
    "sk-ant-api03-" + "e" * 40,  # Anthropic
    "gem-key",                  # the short fakes the rest of the suite uses
    "x",
]


@pytest.fixture(autouse=True)
def _forget_source():
    keys.remember_source(None)
    yield
    keys.remember_source(None)


# --------------------------------------------------------------- defect ----

@pytest.mark.parametrize("value", REAL_SHAPES)
def test_a_usable_key_has_no_defect(value):
    assert keys.defect(value) is None


@pytest.mark.parametrize("value,phrase", [
    (" AIzaxxxx", "whitespace"),
    ("AIzaxxxx ", "whitespace"),
    ("\tAIzaxxxx", "whitespace"),
    ('"AIzaxxxx"', "quotes"),
    ("'AIzaxxxx'", "quotes"),
    ("﻿AIzaxxxx", "byte order mark"),
    ("AIza\x00xxxx", "control character"),
    ("AIza xxxx", "space"),
    ("AIzaxxxxé", "non-ASCII"),
])
def test_characters_no_key_ever_contains_are_named(value, phrase):
    problem = keys.defect(value)
    assert problem is not None
    assert phrase in problem


def test_an_empty_value_is_not_reported_as_defective():
    # Absent is a different failure from malformed, and has its own message.
    assert keys.defect("") is None


def test_the_release_day_key_is_not_refused():
    """
    The exact value that failed was a good key with one printable character in
    front. Nothing can tell that apart from a longer key format, so it must
    NOT be refused. This is the boundary of what refusal can do, and it is
    pinned so nobody later "improves" defect() into rejecting valid keys.
    """
    good = "AQ.Ab8" + "c" * 47
    assert len(good) == 53
    assert keys.defect(good) is None
    assert keys.defect("z" + good) is None


# ------------------------------------------------------------ refusal ------

def test_a_defective_key_is_refused_before_any_model_call(monkeypatch):
    for name in ("API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", " AIzaxxxx")
    with pytest.raises(RuntimeError) as excinfo:
        R._ensure_api_key("gemini")
    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message, "the variable at fault must be named"
    assert "whitespace" in message
    assert "No model call was made" in message


def test_a_defective_generic_key_names_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", '"AIzaxxxx"')
    with pytest.raises(RuntimeError) as excinfo:
        R._ensure_api_key("gemini")
    assert "API_KEY" in str(excinfo.value)
    assert "quotes" in str(excinfo.value)


# ------------------------------------------------------------- source ------

def test_the_source_variable_is_remembered(monkeypatch):
    for name in ("API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    assert R._ensure_api_key("gemini") is True
    assert keys.source() == "GEMINI_API_KEY"


def test_a_preset_generic_key_is_recorded_as_its_own_source(monkeypatch):
    monkeypatch.setenv("API_KEY", "already-set")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    assert R._ensure_api_key("gemini") is True
    assert keys.source() == "API_KEY"


# ---------------------------------------------------------- auth hint ------

def test_the_hint_names_the_variable_the_key_came_from(monkeypatch):
    """The regression. The message used to say API_KEY unconditionally."""
    for name in ("API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.Ab8" + "c" * 48)  # 54, one too many
    R._ensure_api_key("gemini")
    hint = keys.auth_hint("gemini")
    assert "GEMINI_API_KEY" in hint
    assert "54 characters" in hint


def test_the_hint_gives_the_expected_shape_so_a_wrong_length_is_visible(monkeypatch):
    for name in ("API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.Ab8" + "c" * 48)
    R._ensure_api_key("gemini")
    hint = keys.auth_hint("gemini")
    assert "53" in hint, "the reader needs the normal length to compare against"


def test_an_absent_key_says_so_rather_than_reporting_zero_characters(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    assert "empty" in keys.auth_hint("gemini")


def test_an_unknown_provider_still_produces_a_usable_hint(monkeypatch):
    monkeypatch.setenv("API_KEY", "some-key")
    R._ensure_api_key("gemini")
    hint = keys.auth_hint("a-provider-added-later")
    assert "API_KEY" in hint
    assert "normally" not in hint, "no shape is better than a guessed one"


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
def test_every_shipped_provider_has_a_shape_to_offer(provider):
    assert provider in keys._SHAPES


def test_no_provider_still_mentions_the_wrong_variable():
    """
    Every provider's auth error used to hardcode "check API_KEY". Any new
    provider that copies an old one would reintroduce the bug, so the phrase
    is banned from the package outright.
    """
    import pathlib
    root = pathlib.Path(R.__file__).resolve().parent
    offenders = [
        p.name for p in root.glob("*.py")
        if "check API_KEY" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these still hardcode the wrong variable: {offenders}"
