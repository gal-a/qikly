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
import base64
import json
import os

from qikly import __version__, mcp_tools

SERVER_NAME = "qikly"
SERVER_TITLE = "qikly"
SERVER_SITE = "https://test.qikly.com/"

# Shipped inside the package rather than referenced from docs/, because docs/
# is not in the wheel: a `file://` URI into the source tree resolves on the
# machine this was built on and nowhere else.
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_ICON_FILE = os.path.join(_ICON_DIR, "qikly_icon.svg")

# One gradient cannot serve both grounds. The wordmark runs pale to teal, which
# is right on a dark UI and all but vanishes on a light one: rendered at 16 px
# on Light Modern, the pale end of the bowl disappeared into the background.
# The spec's `theme` means "the theme this icon is designed for", so each file
# is tagged with the ground it was drawn for. Dark first, because it is VS
# Code's default, and a client that ignores `theme` will usually take the
# first entry.
#
# What VS Code does with these, measured rather than assumed: nothing visible.
# On 2026-09-11 its MCP Servers list and the server's details page showed the
# generic MCP mark for this locally configured server whether it was sent SVG
# or PNG, each confirmed on the wire and each after a window reload. So the
# icons are here for hosts that do draw them, and nothing should claim VS Code
# is one. PNGs were tried and removed rather than shipped for no effect. Each
# entry: file, theme, sizes.
_ICONS = (("qikly_icon.svg", "dark", "any"),
          ("qikly_icon_light.svg", "light", "any"))

_MIME = {".svg": "image/svg+xml", ".png": "image/png"}


def icon_data_uri(path=_ICON_FILE):
    """
    The server's icon as a self-contained `data:` URI, or None.

    A `data:` URI rather than a `file://` one on purpose. The host resolves
    whatever we hand it, and a path is a promise about the reader's filesystem
    that an editor sandbox, a container or a remote window will not keep. The
    mark is 1.5 KB of SVG, so embedding it costs nothing worth counting.

    Returns None rather than raising: an icon is decoration, and a server that
    refused to start because a picture was missing would be a poor trade.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/svg+xml")
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def server_icons():
    """Every icon variant present, as (data URI, mime type, sizes, theme)."""
    found = []
    for name, theme, sizes in _ICONS:
        uri = icon_data_uri(os.path.join(_ICON_DIR, name))
        if uri:
            found.append((uri, _MIME[os.path.splitext(name)[1].lower()],
                          sizes, theme))
    return found

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

    # Identity, so a host shows a name and a mark rather than a bare command.
    # Passed through a try, because these arguments arrived with the 2.x SDK
    # and the FastMCP fallback above predates them: an older SDK must still get
    # a working server, just a plainer looking one.
    identity = {"title": SERVER_TITLE, "website_url": SERVER_SITE,
                "version": __version__}
    icons = server_icons()
    if icons:
        try:
            from mcp.types import Icon
            identity["icons"] = [Icon(src=uri, mime_type=mime,
                                      sizes=[sizes], theme=theme)
                                 for uri, mime, sizes, theme in icons]
        except Exception:                            # pragma: no cover
            pass
    try:
        server = server_class(SERVER_NAME, **identity)
    except TypeError:                                # pragma: no cover
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
