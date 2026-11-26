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
SERVER_SITE = "https://qikly.com/"

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
        # Writes: it clears and regenerates this task's implementation and
        # suite, keeping a timestamped backup, and it calls a model provider
        # over the network. Not idempotent: each call is a fresh run and the
        # agents are not deterministic even at a fixed seed.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": True},
        "description": (
            "Start a qikly run for one task and return its run id immediately. "
            "This does NOT wait for the run: a run takes minutes to hours. "
            "Poll qikly_status with the returned run_id. The acceptance "
            "criteria are never returned by any qikly tool, because the agent "
            "writing the code must not see them. Returns {ok, run_id, state, "
            "next}, or {ok: false, error} if the task is not found or an "
            "argument is invalid."),
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
        # Reads this machine's run records and nothing else.
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
        "description": (
            "Report on a run started by qikly_run. States: running, passed, "
            "failed, stalled, unknown. 'stalled' means the process is gone "
            "without writing a summary, which is a crash rather than a failing "
            "suite. Includes the stage and iteration while a run is in flight. "
            "Returns an object with ok (false only when the state is unknown) "
            "and state."),
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string",
                                      "description": "The run_id returned by "
                                                     "qikly_run."}},
            "required": ["run_id"],
        },
    },
    {
        "name": "qikly_validate",
        # Offline by construction: no model call, so no network and no cost.
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
        "description": (
            "Validate one task offline and return counts and a verdict: the "
            "same check as `qikly --validate`. Free, no model call. It does NOT "
            "look for contradictions between requirements and criteria; that is "
            "the separate `qikly --check-criteria`, which costs a model call and "
            "is not exposed here. It returns no criterion text: validation "
            "messages quote the criterion they are about, so read those with "
            "`qikly --validate` in a terminal instead. Returns {ok, task_id, "
            "valid, error_count, warning_count, note}."),
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string",
                                       "description": "The task_id to "
                                                      "validate, as named in "
                                                      "inputs_private/config/"
                                                      "tasks/"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "qikly_scaffold",
        # Returns the task YAML as text rather than writing it. Saving it is
        # the caller's decision, which is why this is read-only.
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
        "description": (
            "Read a Python file and return a task YAML that tests that code: "
            "module path, real signatures, a guessed entrypoint, and a seed "
            "pointing at the file. Save it under inputs_private/config/tasks/ "
            "as <task_id>.yaml. requirements and "
            "acceptance_criteria are left as TODO on purpose and will not be "
            "filled in, because criteria derived from an implementation can "
            "only describe what that implementation already does. Returns "
            "{ok, task_yaml, note}. Writes nothing to disk."),
        "inputSchema": {
            "type": "object",
            "properties": {"file_path": {"type": "string",
                                         "description": "One Python (.py) "
                                                        "file, absolute or "
                                                        "relative to the "
                                                        "project root."}},
            "required": ["file_path"],
        },
    },
]


def _parameters(handler):
    import inspect
    return inspect.signature(handler).parameters


def _example(handler):
    params = _parameters(handler)
    first = next(iter(params), "")
    return '{"%s": "..."}' % first


def _argument_problem(name, handler, arguments):
    """
    A missing or unknown argument, said in the tool's terms. Python's own
    TypeError ("qikly_run() missing 1 required positional argument") is what
    an agent used to get back, and it names the function, not the fix.
    """
    import inspect
    params = _parameters(handler)
    unknown = sorted(str(k) for k in arguments if k not in params)
    if unknown:
        return "%s does not take %s. It takes: %s" % (
            name, ", ".join(repr(k) for k in unknown), ", ".join(params))
    missing = [p for p, spec in params.items()
               if spec.default is inspect.Parameter.empty and p not in arguments]
    if missing:
        return "%s is required" % " and ".join(missing)
    return None


def call_tool(name, arguments):
    """
    Dispatch one tool call and return its JSON text.

    Serialising here rather than in each tool keeps the wire format in one
    place, which is the same place `tests/test_mcp_withholding.py` asserts on.
    """
    handler = getattr(mcp_tools, name, None)
    if name not in mcp_tools.TOOLS or handler is None:
        payload = {"ok": False, "error": "unknown tool: %s" % name}
    elif arguments is not None and not isinstance(arguments, dict):
        payload = {"ok": False, "error": "bad arguments for %s: it takes its "
                   "arguments as an object, such "
                   "as %s, not %s" % (name, _example(handler), type(arguments).__name__)}
    elif _argument_problem(name, handler, arguments or {}):
        payload = {"ok": False, "error": "bad arguments for %s: %s" % (
            name, _argument_problem(name, handler, arguments or {}))}
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

    # Behaviour hints, so a host can decide what may run unattended and what
    # needs a person. Without them a client has to assume the worst of every
    # tool, which for three of these four is wrong: only qikly_run writes
    # anything, costs anything, or touches the network. Registered through a
    # helper because the argument arrived with the 2.x SDK and the FastMCP
    # fallback above predates it, so an older SDK must still get a working
    # server, just one that says less about itself.
    def register(index, fn):
        spec = TOOL_SPECS[index]
        try:
            return server.tool(name=spec["name"], description=spec["description"],
                               annotations=spec["annotations"])(fn)
        except TypeError:                            # pragma: no cover
            return server.tool(name=spec["name"],
                               description=spec["description"])(fn)

    # The SDK builds a tool's argument schema from the Python signature, not
    # from TOOL_SPECS["inputSchema"], so a description written only in the spec
    # never reached a host: tools/list served "Task Id" and a type. The spec
    # stays the one place the words live, and each parameter pulls its
    # description and limits from it here.
    from typing import Annotated

    def _arg(tool, prop):
        from pydantic import Field
        spec = next(s for s in TOOL_SPECS if s["name"] == tool)[
            "inputSchema"]["properties"][prop]
        limits = {}
        if "minimum" in spec:
            limits["ge"] = spec["minimum"]
        if "maximum" in spec:
            limits["le"] = spec["maximum"]
        extra = {"enum": spec["enum"]} if "enum" in spec else None
        return Field(description=spec.get("description"),
                     json_schema_extra=extra, **limits)

    def _run(task_id: Annotated[str, _arg("qikly_run", "task_id")],
             provider: Annotated[str, _arg("qikly_run", "provider")] = None,
             model: Annotated[str, _arg("qikly_run", "model")] = None) -> str:
        return call_tool("qikly_run", {"task_id": task_id, "provider": provider,
                                       "model": model})

    def _status(run_id: Annotated[str, _arg("qikly_status", "run_id")]) -> str:
        return call_tool("qikly_status", {"run_id": run_id})

    def _check(task_id: Annotated[str, _arg("qikly_validate", "task_id")]) -> str:
        return call_tool("qikly_validate", {"task_id": task_id})

    def _scaffold(file_path: Annotated[str, _arg("qikly_scaffold", "file_path")]) -> str:
        return call_tool("qikly_scaffold", {"file_path": file_path})

    for index, fn in enumerate((_run, _status, _check, _scaffold)):
        register(index, fn)

    return server


def main():
    """Console entry point: speak MCP over stdio until the host disconnects."""
    build_server().run()
    return 0


if __name__ == "__main__":               # pragma: no cover
    raise SystemExit(main())
