"""
The MCP server: protocol only, no behaviour.

Everything this exposes lives in `mcp_tools`, deliberately. That module is
plain functions returning plain dicts, so the thing that matters most here,
that no tool response carries acceptance criteria, is tested without the SDK
installed and without a protocol handshake. This file must stay thin enough
that reading it tells you it cannot change what a tool returns.

Run it with:

    pip install "qikly[mcp]"
    qikly-mcp

and register that command with the host. It speaks stdio, which is what Claude
Code, Codex CLI and the rest expect from a local server.

**Why the tools are shaped the way they are.** A run takes minutes to hours and
a tool call cannot block for that long, so `qikly_run` starts a run and returns
an id, and `qikly_status` is how the caller learns what happened. That split is
the whole reason this needed designing rather than wrapping.
"""
import json

from qikly import mcp_tools

SERVER_NAME = "qikly"

# The descriptions a host's agent reads to decide whether to call something.
# They say what comes back as well as what it does, because an agent that
# expects a result and receives an id will sit and wait for the wrong thing.
TOOL_SPECS = [
    {
        "name": "qikly_run",
        "description": (
            "Start a qikly run for one task and return its run id immediately. "
            "This does NOT wait for the run: a run takes minutes to hours. "
            "Poll qikly_status with the returned run_id. The acceptance "
            "criteria are never returned by any qikly tool, because the agent "
            "writing the code must not see them."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string",
                            "description": "The task_id to run, as named in "
                                           "inputs_private/config/tasks/"},
                "provider": {"type": "string", "enum": ["gemini", "openai", "anthropic"],
                             "description": "Optional. Defaults to the project's setting."},
                "model": {"type": "string", "description": "Optional model override."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "qikly_status",
        "description": (
            "Report on a run started by qikly_run. States: running, passed, "
            "failed, stalled, unknown. 'stalled' means the process is gone "
            "without writing a summary, which is a crash rather than a failing "
            "suite. Includes the stage and iteration while a run is in flight."),
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "qikly_check_criteria",
        "description": (
            "Validate one task offline and return counts and a verdict. Free, "
            "no model call. It returns no criterion text: validation messages "
            "quote the criterion they are about, so read those with "
            "`qikly --validate` in a terminal instead."),
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "qikly_scaffold",
        "description": (
            "Read a Python file and return the task YAML for it: module path, "
            "real signatures, a guessed entrypoint. requirements and "
            "acceptance_criteria are left as TODO on purpose and will not be "
            "filled in, because criteria derived from an implementation can "
            "only describe what that implementation already does."),
        "inputSchema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]


def call_tool(name, arguments):
    """
    Dispatch one tool call and return its JSON text.

    Serialising here rather than in each tool keeps the wire format in one
    place, which is the same place `tests/test_mcp_withholding.py` asserts on.
    """
    handler = getattr(mcp_tools, name, None)
    if name not in mcp_tools.TOOLS or handler is None:
        payload = {"ok": False, "error": "unknown tool: %s" % name}
    else:
        try:
            payload = handler(**(arguments or {}))
        except TypeError as exc:
            payload = {"ok": False, "error": "bad arguments for %s: %s" % (name, exc)}
    return json.dumps(payload, indent=2, default=str)


def build_server():
    """
    The MCP server object, or a clear error if the SDK is not installed.

    Imported lazily so that `mcp` is an optional dependency: the rest of qikly,
    and every test in this repository, works without it.
    """
    # The SDK renamed its server class in 2.0: FastMCP became MCPServer. Both
    # are tried, so a user who has pinned mcp<2 for something else still gets a
    # server, and the error names the fix rather than the symptom.
    server_class = None
    try:
        from mcp.server.mcpserver import MCPServer as server_class
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as server_class
        except ImportError as exc:                   # pragma: no cover - import guard
            raise SystemExit(
                "the MCP server needs the protocol SDK, which is an optional "
                "extra:\n    pip install \"qikly[mcp]\"\n(%s)" % exc)

    server = server_class(SERVER_NAME)

    @server.tool(name="qikly_run", description=TOOL_SPECS[0]["description"])
    def _run(task_id: str, provider: str = None, model: str = None) -> str:
        return call_tool("qikly_run", {"task_id": task_id, "provider": provider,
                                       "model": model})

    @server.tool(name="qikly_status", description=TOOL_SPECS[1]["description"])
    def _status(run_id: str) -> str:
        return call_tool("qikly_status", {"run_id": run_id})

    @server.tool(name="qikly_check_criteria", description=TOOL_SPECS[2]["description"])
    def _check(task_id: str) -> str:
        return call_tool("qikly_check_criteria", {"task_id": task_id})

    @server.tool(name="qikly_scaffold", description=TOOL_SPECS[3]["description"])
    def _scaffold(file_path: str) -> str:
        return call_tool("qikly_scaffold", {"file_path": file_path})

    return server


def main():
    """Console entry point: speak MCP over stdio until the host disconnects."""
    build_server().run()
    return 0


if __name__ == "__main__":               # pragma: no cover
    raise SystemExit(main())
