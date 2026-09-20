"""
Registering the MCP server into a host's config without damaging it.

Printing a block to paste is safe and it is also where people stop. This
writes instead, which means it can destroy configuration that has nothing to
do with qikly, so most of what is pinned here is what it declines to do.

Project-local files only, `.mcp.json` and `.vscode/mcp.json`. Nothing here
touches a home directory, and no test may introduce one: a suite that writes
to `~/.claude.json` would rewrite the developer's own editor setup on every
run.
"""
import io
import json
import os

from qikly import mcp_install


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    io.open(path, "w", encoding="utf-8").write(text)


def _entry(root):
    return mcp_install.server_entry(str(root))


# -------------------------------------------------------- what it writes ----

def test_the_entry_names_this_python_and_this_project(tmp_path):
    """
    The two facts the one-click install cannot know, and both have failed on
    a real machine: a bare `qikly-mcp` is not on PATH after a pip install on
    Windows, and the host starts the server in whatever folder the editor
    opened rather than the project.
    """
    import sys

    entry = _entry(tmp_path)
    assert entry["command"] == sys.executable
    assert entry["args"] == ["-m", "qikly.mcp_server"]
    assert entry["env"]["QIKLY_PROJECT_ROOT"] == os.path.abspath(str(tmp_path))


def test_an_absent_file_is_created_with_the_host_s_own_key(tmp_path):
    for host, key, rel in ((mcp_install.CLAUDE, "mcpServers", ".mcp.json"),
                           (mcp_install.VSCODE, "servers", os.path.join(".vscode", "mcp.json"))):
        item = mcp_install.plan(str(tmp_path), [host])[0]
        assert item["action"] == "create"
        changed, _ = mcp_install.write(item)
        assert changed
        written = json.loads(io.open(os.path.join(str(tmp_path), rel), encoding="utf-8").read())
        assert list(written[key]) == ["qikly"]


# ------------------------------------------------ what it must not damage ----

def test_every_other_server_in_the_file_survives(tmp_path):
    """
    The file holds the user's other servers. A writer that rewrites it
    destroys work unrelated to qikly, and that is the kind of damage nobody
    notices until they need the thing that is gone.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, json.dumps({
        "mcpServers": {"other": {"command": "x"}},
        "someOtherKey": {"kept": True},
    }, indent=2))

    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "add"
    assert mcp_install.write(item)[0]

    written = json.loads(io.open(path, encoding="utf-8").read())
    assert written["mcpServers"]["other"] == {"command": "x"}
    assert written["someOtherKey"] == {"kept": True}
    assert "qikly" in written["mcpServers"]


def test_the_file_is_backed_up_before_it_is_touched(tmp_path):
    path = os.path.join(str(tmp_path), ".mcp.json")
    original = json.dumps({"mcpServers": {"other": {"command": "x"}}})
    _write(path, original)

    mcp_install.write(mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0])

    backups = [f for f in os.listdir(str(tmp_path)) if ".qikly-backup-" in f]
    assert len(backups) == 1
    assert io.open(os.path.join(str(tmp_path), backups[0]), encoding="utf-8").read() == original


def test_running_it_twice_writes_nothing_the_second_time(tmp_path):
    first = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert mcp_install.write(first)[0]

    second = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert second["action"] == "current"
    changed, message = mcp_install.write(second)
    assert not changed
    assert "identical" in message
    assert not [f for f in os.listdir(str(tmp_path)) if ".qikly-backup-" in f]


def test_an_entry_edited_by_hand_is_left_alone_unless_forced(tmp_path):
    """
    A qikly entry that differs is a config somebody changed on purpose,
    perhaps to point at a different interpreter. Overwriting it silently is
    the second way this feature could take something away from a user.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    mine = {"type": "stdio", "command": "my-own-python", "args": ["-m", "qikly.mcp_server"]}
    _write(path, json.dumps({"mcpServers": {"qikly": mine}}))

    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "differs"
    changed, message = mcp_install.write(item)
    assert not changed and "--force" in message
    assert json.loads(io.open(path, encoding="utf-8").read())["mcpServers"]["qikly"] == mine

    changed, _ = mcp_install.write(item, force=True)
    assert changed
    assert json.loads(io.open(path, encoding="utf-8").read())["mcpServers"]["qikly"] != mine


# ------------------------------------------------------------- JSONC ----

def test_a_file_with_comments_is_refused_rather_than_stripped(tmp_path):
    """
    VS Code's mcp.json is JSONC. A JSON round-trip deletes every comment the
    user wrote, silently, in the one file they were editing. Refusing and
    printing the block is the cheap honest answer; a JSONC round-tripper is a
    dependency this does not need.
    """
    path = os.path.join(str(tmp_path), ".vscode", "mcp.json")
    original = '{\n  // my note\n  "servers": {"other": {"command": "x"}}\n}\n'
    _write(path, original)

    item = mcp_install.plan(str(tmp_path), [mcp_install.VSCODE])[0]
    assert item["action"] == "comments"
    changed, _ = mcp_install.write(item)
    assert not changed
    assert io.open(path, encoding="utf-8").read() == original


def test_a_comment_check_that_is_really_a_string_does_not_fire():
    """A URL in a value is not a comment, and must not block a write."""
    assert not mcp_install.has_comments('{"a": "https://example.com/x"}')
    assert not mcp_install.has_comments('{"a": "b // not a comment"}')
    assert not mcp_install.has_comments('{"a": "escaped \\" quote // still a string"}')
    assert mcp_install.has_comments('{"a": 1} // trailing')
    assert mcp_install.has_comments('{\n /* block */ "a": 1}')


def test_a_comment_is_reported_as_comments_not_as_broken_json(tmp_path):
    """
    JSONC fails json.loads, so checking the parse error first reported "not
    valid JSON" for a file the host reads happily, and sent the user hunting
    a typo that was not there.
    """
    path = os.path.join(str(tmp_path), ".vscode", "mcp.json")
    _write(path, '{\n  // note\n  "servers": {}\n}\n')
    item = mcp_install.plan(str(tmp_path), [mcp_install.VSCODE])[0]
    assert item["action"] == "comments"
    assert "comments" in item["detail"]


# --------------------------------------------------------- broken input ----

def test_genuinely_broken_json_is_refused_and_named(tmp_path):
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, '{"mcpServers": {')
    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "unreadable"
    changed, message = mcp_install.write(item)
    assert not changed and "Left alone" in message
    assert io.open(path, encoding="utf-8").read() == '{"mcpServers": {'


def test_an_empty_file_is_treated_as_an_empty_config(tmp_path):
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, "\n")
    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "add"
    assert mcp_install.write(item)[0]
    assert "qikly" in json.loads(io.open(path, encoding="utf-8").read())["mcpServers"]


def test_a_json_file_that_is_not_an_object_is_refused(tmp_path):
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, "[1, 2, 3]")
    assert mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]["action"] == "unreadable"


# ---------------------------------------------------------------- scope ----

def test_only_project_local_paths_are_ever_targeted(tmp_path):
    """
    The global files hold every other server the user has. Nothing here may
    grow a path into a home directory without this test being changed
    deliberately.
    """
    for item in mcp_install.plan(str(tmp_path)):
        assert os.path.abspath(item["path"]).startswith(os.path.abspath(str(tmp_path)))
        assert ".claude.json" not in item["path"]


def test_the_planner_touches_nothing(tmp_path):
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, "{}")
    before = sorted(os.listdir(str(tmp_path)))
    mcp_install.plan(str(tmp_path))
    assert sorted(os.listdir(str(tmp_path))) == before
    assert io.open(path, encoding="utf-8").read() == "{}"


# ------------------------------------------- found in review, 2026-09-20 ----

def test_the_write_is_atomic_so_a_crash_cannot_truncate_the_config(tmp_path,
                                                                   monkeypatch):
    """
    Opening the target with "w" truncates it immediately. A crash between that
    and the write completing left a file holding every other server the user
    has empty or half written, and recovering meant knowing a backup existed.
    The content is built beside the file and moved onto it instead, so what is
    on disk is always one whole version or the other.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    original = json.dumps({"mcpServers": {"other": {"command": "x"}}}, indent=2)
    _write(path, original)

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    monkeypatch.setattr(mcp_install.os, "replace", explode)
    changed, message = mcp_install.write(item)

    assert not changed and "Left unchanged" in message
    assert io.open(path, encoding="utf-8").read() == original
    assert not [f for f in os.listdir(str(tmp_path)) if f.endswith(".qikly-tmp")]


def test_an_entry_appearing_between_plan_and_write_is_not_overwritten(tmp_path):
    """
    plan() and write() read the file separately. Trusting plan's verdict meant
    an entry written into that gap, by an editor or a second copy of this
    command, was replaced with no --force ever consulted, which is the exact
    case --force exists to gate.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, json.dumps({"mcpServers": {}}))

    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "add"

    theirs = {"type": "stdio", "command": "someone-elses-python"}
    _write(path, json.dumps({"mcpServers": {"qikly": theirs}}))

    changed, message = mcp_install.write(item)
    assert not changed and "--force" in message
    assert json.loads(io.open(path, encoding="utf-8").read())["mcpServers"]["qikly"] == theirs


def test_comments_arriving_between_plan_and_write_are_also_respected(tmp_path):
    path = os.path.join(str(tmp_path), ".vscode", "mcp.json")
    _write(path, '{"servers": {}}')
    item = mcp_install.plan(str(tmp_path), [mcp_install.VSCODE])[0]
    assert item["action"] == "add"

    later = '{\n  // added since\n  "servers": {}\n}\n'
    _write(path, later)
    changed, _ = mcp_install.write(item)
    assert not changed
    assert io.open(path, encoding="utf-8").read() == later


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    """
    The name carried a timestamp to the second, and shutil.copy2 overwrites.
    Two writes inside one second produced one backup, so the true original was
    lost: the safety net failing in the case it exists for.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    _write(path, json.dumps({"mcpServers": {"first": {}}}))
    first = mcp_install._backup(path)
    _write(path, json.dumps({"mcpServers": {"second": {}}}))
    second = mcp_install._backup(path)

    assert first != second
    assert "first" in io.open(first, encoding="utf-8").read()
    assert "second" in io.open(second, encoding="utf-8").read()


def test_a_symlinked_config_is_refused_rather_than_followed(tmp_path):
    """
    Dotfile managers symlink these files out of the project. Following one
    writes outside the project, which is the single thing this module promises
    not to do.
    """
    import pytest

    real = tmp_path / "elsewhere.json"
    real.write_text('{"mcpServers": {}}', encoding="utf-8")
    link = os.path.join(str(tmp_path), ".mcp.json")
    try:
        os.symlink(str(real), link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("this platform or account cannot create symlinks")

    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "unreadable"
    assert "symlink" in item["detail"]
    changed, _ = mcp_install.write(item)
    assert not changed
    assert real.read_text(encoding="utf-8") == '{"mcpServers": {}}'


def test_a_byte_order_mark_does_not_make_the_file_look_broken(tmp_path):
    """
    PowerShell writes a BOM by default, on the platform this feature exists
    for, and a BOM is not valid JSON. Reporting "not valid JSON" sent the user
    hunting a typo that was not there.
    """
    path = os.path.join(str(tmp_path), ".mcp.json")
    io.open(path, "w", encoding="utf-8-sig").write(json.dumps({"mcpServers": {}}))
    item = mcp_install.plan(str(tmp_path), [mcp_install.CLAUDE])[0]
    assert item["action"] == "add"
    assert mcp_install.write(item)[0]


# --------------------------------------------------------- the CLI layer ----

def test_the_cli_writes_only_the_host_it_was_asked_for(tmp_path, monkeypatch, capsys):
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)
    assert cli._do_install_mcp("claude", dry_run=False, force=False) == 0
    capsys.readouterr()

    assert os.path.exists(os.path.join(str(tmp_path), ".mcp.json"))
    assert not os.path.exists(os.path.join(str(tmp_path), ".vscode", "mcp.json"))


def test_the_cli_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)
    assert cli._do_install_mcp("all", dry_run=True, force=False) == 0
    assert "would create" in capsys.readouterr().out
    assert os.listdir(str(tmp_path)) == []


def test_the_cli_exits_non_zero_when_it_refused_everything(tmp_path, monkeypatch,
                                                           capsys):
    """
    A provisioning step has to tell "already done" from "refused everything",
    and both printed a friendly message and exited 0.
    """
    from qikly import cli

    _write(os.path.join(str(tmp_path), ".mcp.json"), '{"bad json')
    _write(os.path.join(str(tmp_path), ".vscode", "mcp.json"),
           '{\n // note\n "servers": {}\n}')
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)

    assert cli._do_install_mcp("all", dry_run=False, force=False) == 2
    assert "Paste this" in capsys.readouterr().err


def test_the_cli_exits_zero_when_everything_was_already_registered(tmp_path,
                                                                   monkeypatch,
                                                                   capsys):
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)
    cli._do_install_mcp("all", dry_run=False, force=False)
    capsys.readouterr()
    assert cli._do_install_mcp("all", dry_run=False, force=False) == 0
    assert "identical" in capsys.readouterr().out


def test_the_cli_writes_where_you_stand_not_where_the_env_var_points(tmp_path,
                                                                     monkeypatch,
                                                                     capsys):
    """
    Found on the first real use of this command. QIKLY_PROJECT_ROOT was left
    in the shell from an earlier session, so `qikly --install-mcp` created
    .mcp.json two directories away and the only clue was one line of output
    that is easy to read past. Printing a path is not consent, and a command
    that writes files has to write where the user is standing.
    """
    from qikly import cli

    elsewhere = tmp_path / "elsewhere"
    here = tmp_path / "here"
    elsewhere.mkdir()
    here.mkdir()

    monkeypatch.setattr(cli, "INVOKED_FROM", str(here))
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(elsewhere))
    cli._do_install_mcp("claude", dry_run=False, force=False)

    assert (here / ".mcp.json").exists()
    assert not (elsewhere / ".mcp.json").exists()

    out = capsys.readouterr().out
    assert str(elsewhere) in out and "is not used here" in out


def test_the_entry_points_the_server_at_the_directory_it_was_written_into(
        tmp_path, monkeypatch, capsys):
    """
    A project-local file that pinned a different project would be worse than
    no pin at all: the file says one thing and the server does another.
    """
    import json as _json

    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setenv("QIKLY_PROJECT_ROOT", str(tmp_path / "somewhere-else"))
    cli._do_install_mcp("claude", dry_run=False, force=False)
    capsys.readouterr()

    written = _json.loads(io.open(os.path.join(str(tmp_path), ".mcp.json"),
                                  encoding="utf-8").read())
    assert written["mcpServers"]["qikly"]["env"]["QIKLY_PROJECT_ROOT"] == \
        os.path.abspath(str(tmp_path))


def test_the_claude_path_tells_you_it_still_needs_approval(tmp_path, monkeypatch,
                                                           capsys):
    """
    Found on the first end-to-end check. The write succeeded and `claude mcp
    list` showed qikly as "Pending approval", which is correct of Claude Code:
    a project file must not be trusted on sight. But the command said
    "created" and stopped, so a user following it exactly ends with a server
    that is registered and never starts.
    """
    from qikly import cli

    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.delenv("QIKLY_PROJECT_ROOT", raising=False)
    cli._do_install_mcp("claude", dry_run=False, force=False)

    out = capsys.readouterr().out
    assert "pending approval" in out.lower()
    assert "approve" in out.lower()
