"""
`qikly --mcp-config`: a config that starts a server on this machine.

The one-click install badge writes a bare `qikly-mcp` and trusts two things it
cannot know: that pip's `Scripts` folder is on `PATH`, and that the editor will
start the server in the project folder. On Windows neither reliably holds, and
both failed on the author's own machine the first time the badge was clicked.
This command prints both facts in full instead. The test that matters most is
the last one: that what it prints actually starts a server.
"""
import json
import os
import subprocess
import sys
import threading

import pytest

from qikly import cli

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _config(host, monkeypatch, capsys, root):
    monkeypatch.setattr(cli, "INVOKED_FROM", str(root))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)
    assert cli._do_mcp_config(host) == 0
    return capsys.readouterr()


def test_vscode_config_names_this_python_and_this_folder(monkeypatch, capsys, tmp_path):
    out = _config("vscode", monkeypatch, capsys, tmp_path).out
    server = json.loads(out)["servers"]["qikly"]
    assert server["command"] == sys.executable, "a full path needs no PATH entry"
    assert server["args"] == ["-m", "qikly.mcp_server"]
    assert server["type"] == "stdio"
    assert server["env"]["QIKLY_PROJECT_ROOT"] == os.path.abspath(str(tmp_path))


def test_claude_shape_uses_mcpServers(monkeypatch, capsys, tmp_path):
    out = _config("claude", monkeypatch, capsys, tmp_path).out
    assert list(json.loads(out)) == ["mcpServers"]


def test_stdout_is_only_the_json(monkeypatch, capsys, tmp_path):
    """Guidance goes to stderr, so the whole of stdout can be pasted or piped."""
    captured = _config("vscode", monkeypatch, capsys, tmp_path)
    json.loads(captured.out)
    assert "Paste it into" in captured.err


def test_an_explicit_project_root_wins_over_the_current_folder(monkeypatch, capsys, tmp_path):
    other = tmp_path / "project"
    other.mkdir()
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(other))
    cli._do_mcp_config("vscode")
    server = json.loads(capsys.readouterr().out)["servers"]["qikly"]
    assert server["env"]["QIKLY_PROJECT_ROOT"] == os.path.abspath(str(other))


def test_the_update_notice_cannot_land_inside_the_config(monkeypatch, capsys):
    """
    The notice prints to stdout. Pasted into mcp.json it is a parse error, in
    the one file the user was trying to fix, so this command runs before it.
    """
    import qikly.version_check as vc

    monkeypatch.setattr(vc, "check_for_update",
                        lambda: print("qikly 9.9.9 is available") or "x")
    monkeypatch.setattr(sys, "argv", ["qikly", "--mcp-config"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    json.loads(out)
    assert "available" not in out


def test_python_dash_m_qikly_runs_the_cli():
    """
    For the users the `qikly` command fails for: when `qikly-mcp` is not on
    PATH, neither is `qikly`, but `python` is.
    """
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-m", "qikly", "--version"],
                          capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("qikly ")


def test_the_printed_config_actually_starts_a_server(monkeypatch, capsys, tmp_path):
    """
    Everything above checks what was printed. This runs it: the command and
    args exactly as printed, the env exactly as printed, and a real MCP
    handshake over stdio.
    """
    pytest.importorskip("mcp")
    server = json.loads(_config("vscode", monkeypatch, capsys, tmp_path).out)["servers"]["qikly"]
    env = dict(os.environ, **server["env"])
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    hello = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}}})
    proc = subprocess.Popen([server["command"]] + server["args"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    try:
        proc.stdin.write(hello + "\n")
        proc.stdin.flush()
        box = []
        reader = threading.Thread(target=lambda: box.append(proc.stdout.readline()),
                                  daemon=True)
        reader.start()
        reader.join(90)
        assert box and box[0].strip(), "the printed config did not start a server"
        reply = json.loads(box[0])
        assert reply["result"]["serverInfo"]["name"] == "qikly"
    finally:
        proc.kill()
