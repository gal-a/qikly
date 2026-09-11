"""
The server as a host actually meets it: a real process, a real handshake.

Every other MCP test here calls the functions directly, which is deliberate and
keeps them fast and free of the optional SDK. The gap that leaves is the whole
protocol layer: a server that registered its tools under the wrong names, or
crashed on startup, or advertised a schema no host could satisfy, would pass
all of them. This spawns `python -m qikly.mcp_server` over stdio and talks to
it, which is the only way to find that out.

Skipped when the `mcp` extra is not installed, so the base suite stays
dependency-free. Install it with `pip install "qikly[mcp]"` to run this.

Only the free tools are called. Nothing here spends a model call.
"""
import asyncio
import json
import os
import sys

import pytest

pytest.importorskip("mcp", reason="the MCP extra is not installed")

from mcp import ClientSession, StdioServerParameters          # noqa: E402
from mcp.client.stdio import stdio_client                     # noqa: E402

from qikly import paths                                       # noqa: E402


def _text(result):
    """The text payload of a CallToolResult, across SDK shapes."""
    return "\n".join(getattr(item, "text", "") or ""
                     for item in (getattr(result, "content", None) or []))


async def _session(run):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qikly.mcp_server"],
        cwd=paths.project_root(), env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await run(session)


def _run(coro_fn):
    return asyncio.run(_session(coro_fn))


def test_the_server_starts_and_advertises_exactly_its_four_tools():
    async def go(session):
        listed = await session.list_tools()
        return sorted(t.name for t in listed.tools), [t.description for t in listed.tools]

    names, descriptions = _run(go)
    assert names == ["qikly_check_criteria", "qikly_run",
                     "qikly_scaffold", "qikly_status"]
    assert all(descriptions), "a tool was advertised with no description"


def test_an_unknown_run_is_answered_rather_than_crashing_the_server():
    """
    A host asking about a run that has been cleaned up is ordinary. An
    exception crossing the protocol boundary is not.
    """
    async def go(session):
        a = await session.call_tool("qikly_status", {"run_id": "NOPE_20260101_000000"})
        b = await session.call_tool("qikly_status", {"run_id": "garbage"})
        return json.loads(_text(a)), json.loads(_text(b))

    unknown, garbage = _run(go)
    assert unknown["state"] == "unknown"
    assert garbage["state"] == "unknown"


def test_a_traversing_task_id_is_refused_over_the_wire():
    """
    The unit test covers `check_task_id`. This covers the path a hostile value
    actually travels: through the host, the SDK's own validation, and the tool.
    """
    async def go(session):
        return _text(await session.call_tool("qikly_run", {"task_id": "../../evil"}))

    body = _run(go)
    assert json.loads(body)["ok"] is False
    assert "one path segment" in body


def test_check_criteria_returns_counts_and_no_criterion_text():
    async def go(session):
        listed = await session.list_tools()
        assert listed.tools
        return _text(await session.call_tool("qikly_check_criteria",
                                             {"task_id": "TEXT_PATCH"}))

    body = _run(go)
    payload = json.loads(body)
    assert payload["ok"] is True
    assert isinstance(payload["error_count"], int)
    assert isinstance(payload["warning_count"], int)
    # The verdict crosses. The messages, which quote criteria, do not.
    assert "message" not in payload and "errors" not in payload


def test_scaffold_over_the_wire_carries_no_real_criteria():
    async def go(session):
        return _text(await session.call_tool("qikly_scaffold",
                                             {"file_path": "src/qikly/from_doc.py"}))

    payload = json.loads(_run(go))
    if not payload.get("ok"):
        pytest.skip("scaffold could not read that file in this checkout")
    inside, checked = False, 0
    for line in payload["task_yaml"].splitlines():
        if line.startswith("acceptance_criteria:"):
            inside = True
            continue
        if inside:
            if line.strip().startswith("- "):
                checked += 1
                assert "TODO" in line or "withheld" in line, line
            elif line.strip() and not line.startswith((" ", "\t", "#")):
                break
    assert checked, "no criteria section came back at all"
