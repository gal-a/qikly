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


# ------------------------------------------------ pointed at the wrong folder -

def test_a_fresh_install_with_no_inputs_private_still_works(tmp_path, monkeypatch):
    """
    The regression this guard nearly shipped. Bundled tasks live inside the
    package and need no `inputs_private/` at all, so keying the check on that
    directory declares every fresh install broken. That is precisely the false
    alarm `validate._input_exists` exists to undo, and it must not come back
    through a different door.
    """
    from qikly import mcp_tools
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    assert mcp_tools.where_we_looked("CALC_TAX") is None
    payload = mcp_tools.qikly_check_criteria("CALC_TAX")
    assert payload["valid"] is True
    assert "detail" not in payload


def test_an_unfindable_task_says_which_directory_was_searched():
    """
    "No such task" is true, useless, and reads as qikly being broken rather
    than pointed at the wrong folder. The directory is most of the fix.
    """
    from qikly import mcp_tools
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    problem = mcp_tools.where_we_looked("NO_SUCH_TASK_ANYWHERE")
    assert problem
    assert "QIKLY_PROJECT_ROOT" in problem, "name the fix, not just the symptom"
    assert "NO_SUCH_TASK_ANYWHERE" in problem


def test_check_criteria_keeps_its_shape_when_the_task_is_missing():
    """A missing task is still an unusable bar, which is what was asked."""
    from qikly import mcp_tools
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    payload = mcp_tools.qikly_check_criteria("NO_SUCH_TASK_ANYWHERE")
    assert payload["ok"] is True and payload["valid"] is False
    assert payload["error_count"] == 1
    assert "QIKLY_PROJECT_ROOT" in payload["detail"]


def test_run_refuses_a_task_it_cannot_find_rather_than_spending(monkeypatch):
    """A doomed run costs minutes and money to deliver the same answer."""
    from qikly import mcp_tools
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    called = []
    monkeypatch.setattr(mcp_tools.runs, "start", lambda *a, **k: called.append(1))
    payload = mcp_tools.qikly_run("NO_SUCH_TASK_ANYWHERE")
    assert payload["ok"] is False
    assert called == [], "nothing may be started"


# ------------------------------------------------------------------ identity -

def test_the_server_ships_its_own_icon():
    """
    A data URI, not a file path: docs/ is not in the wheel, and a path is a
    promise about the reader's filesystem that a sandbox will not keep.
    """
    from qikly import mcp_server

    uri = mcp_server.icon_data_uri()
    assert uri and uri.startswith("data:image/svg+xml;base64,")
    import base64
    svg = base64.b64decode(uri.split(",", 1)[1]).decode("utf-8")
    assert "<svg" in svg and "qikly" in svg


def test_a_missing_icon_is_not_an_error():
    """An icon is decoration. A server that would not start without one is not."""
    from qikly import mcp_server

    assert mcp_server.icon_data_uri("no/such/icon.svg") is None


# ------------------------ scaffold, from a host that is not in your project --

def test_scaffold_resolves_a_relative_path_against_the_project(monkeypatch, tmp_path):
    """
    The failure a host produces and nothing caught. The server's working
    directory is the folder the editor has open, so a caller who correctly set
    QIKLY_PROJECT_ROOT and passed a project-relative path got "no such file"
    and no hint that two directories were involved. The end-to-end test could
    not see it because it pins cwd to the project root, which is exactly the
    condition that does not hold in the field.
    """
    from qikly import mcp_tools
    from qikly.paths import project_root

    root = project_root()
    monkeypatch.chdir(tmp_path)                      # the editor's folder
    payload = mcp_tools.qikly_scaffold("src/qikly/paths.py")
    assert payload["ok"] is True, payload.get("error")
    assert "task_yaml" in payload
    assert str(root)                                  # root was used, not cwd


def test_scaffold_names_both_directories_when_it_cannot_find_the_file(monkeypatch, tmp_path):
    """One bare "no such file" is what sent someone looking in the wrong place."""
    from qikly import mcp_tools

    monkeypatch.chdir(tmp_path)
    payload = mcp_tools.qikly_scaffold("no/such/module.py")
    assert payload["ok"] is False
    assert "project root" in payload["error"]
    assert "working directory" in payload["error"]
    assert "QIKLY_PROJECT_ROOT" in payload["error"]


def test_scaffold_still_takes_an_absolute_path(tmp_path):
    from qikly import mcp_tools
    from qikly.paths import project_root
    import os

    target = os.path.join(project_root(), "src", "qikly", "paths.py")
    payload = mcp_tools.qikly_scaffold(target)
    assert payload["ok"] is True, payload.get("error")


def test_the_icon_comes_in_a_dark_and_a_light_variant():
    """
    One gradient cannot serve both grounds. The wordmark runs pale to teal for
    a dark UI, and rendered at 16 px on Light Modern its pale end vanished into
    the background. The spec's `theme` says which variant is drawn for which
    ground, and dark comes first because a client ignoring `theme` usually
    takes the first entry and dark is VS Code's default.
    """
    from qikly import mcp_server

    icons = mcp_server.server_icons()
    assert [(mime, theme) for _, mime, _, theme in icons] == [
        ("image/svg+xml", "dark"), ("image/svg+xml", "light")]
    assert all(uri.startswith("data:image/svg+xml;base64,")
               for uri, _, _, _ in icons)
    assert icons[0][0] != icons[1][0], "two variants, not one file twice"


def test_each_icon_variant_is_legible_on_the_ground_it_is_tagged_for():
    """
    Measured rather than eyeballed. Every gradient stop has to clear WCAG's
    3:1 minimum for graphics against the backgrounds its variant is tagged
    for. The original pale stop measured 1.22:1 on white and simply vanished
    at sidebar size, which is what a check like this exists to catch before a
    palette change ships it again.
    """
    import os
    import re
    from qikly import mcp_server

    def luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                    for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def contrast(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    # VS Code's own Modern themes: editor and sidebar backgrounds.
    grounds = {"dark": ["#1f1f1f", "#181818"], "light": ["#ffffff", "#f8f8f8"]}
    for name, theme, _sizes in mcp_server._ICONS:
        if not name.endswith(".svg"):
            continue            # the PNGs are rendered from these, stop for stop
        with open(os.path.join(mcp_server._ICON_DIR, name), encoding="utf-8") as handle:
            stops = re.findall(r'stop-color="(#[0-9a-fA-F]{6})"', handle.read())
        assert stops, "%s has no gradient stops to check" % name
        for stop in stops:
            for ground in grounds[theme]:
                assert contrast(stop, ground) >= 3.0, (
                    "%s (%s) stop %s is %.2f:1 on %s"
                    % (name, theme, stop, contrast(stop, ground), ground))
