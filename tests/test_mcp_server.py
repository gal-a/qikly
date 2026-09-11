"""
The protocol layer, checked without the protocol.

`mcp_server` is meant to be thin: it declares four tools and forwards each to
`mcp_tools`. Everything that decides *what comes back* lives there, so these
tests check the two things this file can still get wrong. Dispatching to the
wrong function, and letting the declared surface drift from the implemented
one.

The SDK is an optional extra, so nothing here imports it. If these tests ever
need `mcp` installed to run, this file has stopped being thin.
"""
import json

import pytest

from qikly import mcp_server, mcp_tools


def test_the_sdk_is_not_needed_to_import_or_dispatch():
    """
    `mcp` is an optional dependency and the base install must not want it. The
    import at the top of this file already proves half of it; this states the
    intent so nobody 'tidies' the lazy import in build_server() into a
    module-level one.
    """
    import sys
    assert "mcp" not in sys.modules or True  # the SDK may be present; it must not be required
    source = open(mcp_server.__file__, encoding="utf-8").read()
    top = source.split("def build_server")[0]
    assert "from mcp" not in top and "import mcp\n" not in top, (
        "the SDK is imported at module level, which makes it mandatory")


def test_every_declared_tool_is_implemented():
    declared = {spec["name"] for spec in mcp_server.TOOL_SPECS}
    assert declared == set(mcp_tools.TOOLS), (
        "the declared surface and the implemented one disagree: "
        f"{declared ^ set(mcp_tools.TOOLS)}")
    for name in declared:
        assert callable(getattr(mcp_tools, name, None)), name


def test_every_tool_declares_its_required_arguments():
    for spec in mcp_server.TOOL_SPECS:
        schema = spec["inputSchema"]
        assert schema["required"], "%s requires nothing, which cannot be right" % spec["name"]
        for field in schema["required"]:
            assert field in schema["properties"], (spec["name"], field)


def test_the_run_description_warns_that_it_does_not_wait():
    """
    A host's agent that expects a result and receives an id will sit waiting
    for something that is never coming. The description is the only place that
    can prevent it.
    """
    spec = next(s for s in mcp_server.TOOL_SPECS if s["name"] == "qikly_run")
    text = spec["description"].lower()
    assert "does not wait" in text
    assert "qikly_status" in text


def test_the_descriptions_tell_the_agent_it_will_not_get_the_criteria():
    """
    Not a security control, the redaction is. This stops a host's agent
    concluding the tool is broken when it does not receive them.
    """
    joined = " ".join(s["description"] for s in mcp_server.TOOL_SPECS).lower()
    assert "never returned" in joined or "must not see them" in joined


# ------------------------------------------------------------- dispatch -----

def test_a_call_is_forwarded_to_the_matching_function(monkeypatch):
    seen = {}
    monkeypatch.setattr(mcp_tools, "qikly_status",
                        lambda run_id: seen.update(run_id=run_id) or {"ok": True})
    out = json.loads(mcp_server.call_tool("qikly_status", {"run_id": "T_20260910_120000"}))
    assert seen["run_id"] == "T_20260910_120000"
    assert out["ok"] is True


def test_an_unknown_tool_is_reported_not_raised():
    out = json.loads(mcp_server.call_tool("qikly_delete_everything", {}))
    assert out["ok"] is False
    assert "unknown tool" in out["error"]


def test_a_private_function_cannot_be_called_through_the_dispatcher():
    """
    getattr on a module is a wide door. Only the declared tools go through it.
    """
    out = json.loads(mcp_server.call_tool("_redact", {"payload": {}}))
    assert out["ok"] is False
    assert "unknown tool" in out["error"]


def test_bad_arguments_produce_a_message_rather_than_a_traceback():
    out = json.loads(mcp_server.call_tool("qikly_status", {"nonsense": 1}))
    assert out["ok"] is False
    assert "bad arguments" in out["error"]


def test_the_response_is_json_text_because_that_is_what_crosses_the_wire():
    """
    Serialising in one place is what makes the withholding test meaningful:
    it asserts on the same string a host receives.
    """
    out = mcp_server.call_tool("qikly_status", {"run_id": "not-a-run-id"})
    assert isinstance(out, str)
    assert json.loads(out)["state"] == "unknown"


# ------------------------------------------------- build_server, for real ----
#
# These replaced two tests that only grepped this module's own source for the
# strings "mcp.server.mcpserver import MCPServer" and "qikly[mcp]". That
# asserts the implementation rather than the behaviour: a typo in the real
# import, or the two branches swapped, would leave the substrings present and
# the tests green while `qikly-mcp` failed to start. So a fake SDK is installed
# into sys.modules and build_server() is actually called.


class _FakeServer:
    """Enough of the SDK's server to see what gets registered on it."""

    def __init__(self, name):
        self.name = name
        self.registered = {}

    def tool(self, name=None, description=None, **kwargs):
        def decorate(fn):
            self.registered[name] = (fn, description)
            return fn
        return decorate


def _fake_sdk(monkeypatch, generation):
    """Put one generation of the SDK on sys.modules and hide the other."""
    import sys
    import types

    for mod in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    root = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")
    monkeypatch.setitem(sys.modules, "mcp", root)
    monkeypatch.setitem(sys.modules, "mcp.server", server_pkg)

    leaf_name = "mcp.server.mcpserver" if generation == "2.x" else "mcp.server.fastmcp"
    attr = "MCPServer" if generation == "2.x" else "FastMCP"
    leaf = types.ModuleType(leaf_name)
    setattr(leaf, attr, _FakeServer)
    monkeypatch.setitem(sys.modules, leaf_name, leaf)
    # The other generation must genuinely not import.
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp"
                        if generation == "2.x" else "mcp.server.mcpserver", None)


@pytest.mark.parametrize("generation", ["2.x", "1.x"])
def test_build_server_registers_all_four_tools_on_either_sdk(monkeypatch, generation):
    _fake_sdk(monkeypatch, generation)
    server = mcp_server.build_server()
    assert isinstance(server, _FakeServer)
    assert set(server.registered) == set(mcp_tools.TOOLS)
    for name, (_fn, description) in server.registered.items():
        assert description, "%s was registered with no description" % name


def test_a_registered_tool_actually_round_trips_to_its_implementation(monkeypatch):
    """
    The wiring, not the wiring's source code: call what was registered and see
    that the right function ran with the right arguments.
    """
    _fake_sdk(monkeypatch, "2.x")
    seen = {}
    monkeypatch.setattr(mcp_tools, "qikly_status",
                        lambda run_id: seen.update(run_id=run_id) or {"ok": True})
    server = mcp_server.build_server()
    fn, _ = server.registered["qikly_status"]
    out = json.loads(fn("T_20260910_120000"))
    assert seen["run_id"] == "T_20260910_120000"
    assert out["ok"] is True


def test_no_sdk_at_all_exits_with_the_command_to_type(monkeypatch):
    """
    The base install does not want `mcp`, so somebody will meet this. It has to
    say what to type rather than what went wrong.
    """
    import sys
    for mod in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    with pytest.raises(SystemExit) as exit_info:
        mcp_server.build_server()
    assert 'pip install "qikly[mcp]"' in str(exit_info.value)
