"""
Shared fixtures. Everything here runs offline: no test in this suite may make
a network call, because a test suite that needs an API key is a test suite that
gets skipped in CI and then stops catching anything.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
# research/ holds the statistics that produce the published numbers. Only
# stats_helpers is imported from it: the experiment modules chdir to the
# project root at import time, which would move the working directory out from
# under every other test in the session.
for _path in (_SRC, os.path.join(_ROOT, "research")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly rather than silently reaching the internet."""
    import socket

    def _blocked(*a, **k):
        raise AssertionError("a test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setenv("QIKLY_NO_VERSION_CHECK", "1")


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    """Provider selection reads the environment, so isolate it per test."""
    for var in ("API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
