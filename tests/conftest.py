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


_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """
    Fail loudly rather than silently reaching the internet.

    Loopback is allowed. The rule this enforces is "no test needs an API key or
    the internet", and 127.0.0.1 is neither: blocking it was incidental, and it
    blocked a legitimate local case, because asyncio's Windows event loop builds
    itself from a loopback socketpair. `tests/test_mcp_end_to_end.py` spawns a
    real MCP server as a subprocess and could not run at all until this
    distinguished the two.
    """
    import socket

    real_connect = socket.socket.connect

    def _blocked(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) and address else None
        if host in _LOOPBACK:
            return real_connect(self, address, *a, **k)
        raise AssertionError(
            "a test attempted a network connection to %r" % (address,))

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setenv("QIKLY_NO_VERSION_CHECK", "1")


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    """Provider selection reads the environment, so isolate it per test."""
    for var in ("API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
