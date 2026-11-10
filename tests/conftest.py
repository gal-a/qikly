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
    # And never a drafting call from --scaffold, even with a key in a
    # settings file: a test that wants one patches the call itself.
    monkeypatch.setenv("QIKLY_NO_DRAFT", "1")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """
    Put each test marked `xdist_group(name)` in its group, for
    `--dist loadgroup` (see CONTRIBUTING.md).

    pytest-xdist does this itself by appending "@<name>" to `item._nodeid`,
    but pytest 9.2 reads a test's id from `item._id`, so with xdist 3.8.0 the
    groups were silently ignored and the "project_root" tests ran on several
    workers at once, writing to the same project folder. trylast runs this
    after xdist's own hook, so a test xdist has already tagged (older pytest)
    is left alone; an "@" inside a parametrize id's brackets is not a tag.
    """
    if not getattr(config.option, "loadgroup", False):
        return
    for item in items:
        names = sorted({str(m.args[0] if m.args else m.kwargs.get("name", "default"))
                        for m in item.iter_markers("xdist_group")})
        nodeid = item.nodeid
        if not names or nodeid.rfind("@") > nodeid.rfind("]"):
            continue
        tagged = "%s@%s" % (nodeid, "_".join(names))
        if hasattr(item, "_id"):
            from _pytest.nodeid import coerce_node_id
            item._id = coerce_node_id(tagged)
        else:
            item._nodeid = tagged
