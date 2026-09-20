# -*- coding: utf-8 -*-
"""
Register the qikly MCP server with the hosts that are actually present.

`--mcp-config` prints a block to paste. That is safe and it is also the step
where people give up: registering qikly with Claude Code on the author's own
machine meant discovering that `claude mcp add` is not on `PATH`, because the
CLI is bundled inside the VS Code extension, and then reading `~/.claude.json`
by hand to find out whether the server was already there. That was the author,
on the machine the tool was built on, with the documentation open. A stranger
who hits that closes the tab.

**Project-local files only.** `.mcp.json` for Claude Code and `.vscode/mcp.json`
for VS Code, both inside the project. Never `~/.claude.json` and never the VS
Code user profile. Those hold every other server the user has, and the blast
radius of a bad write there is somebody else's work. The project file is also
the right place on its own terms, because the one setting that reliably goes
wrong is which folder the server treats as the project, and a project-local
file answers that by construction.

**It refuses rather than guesses.** Three ways a write could damage something,
and each is a stop rather than a best effort:

- The file holds comments. VS Code's `mcp.json` is JSONC, and a JSON reader
  that round-trips it deletes every comment the user wrote. Detected, refused,
  and the block printed to paste instead. Acquiring a JSONC round-tripper to
  avoid that is a dependency this does not need.
- An entry named `qikly` already exists and differs from what we would write.
  That is a config somebody edited on purpose. Shown, refused, and `--force`
  is the way to say otherwise.
- Anything else in the file. Every other key and every other server is read,
  kept, and written back untouched, and the file is copied to a timestamped
  backup first.

Running it twice writes nothing the second time and says so.
"""
import io
import json
import os
import shutil
import sys
import time

CLAUDE, VSCODE = "claude", "vscode"

# Host, the file it reads inside a project, and the key servers live under.
# Only these two: both were read on disk before this was written. Cursor and
# Codex CLI are a second stage, and Codex needs a TOML writer, which the
# standard library does not have on any Python this supports.
HOSTS = {
    CLAUDE: {"path": (".mcp.json",), "key": "mcpServers", "label": "Claude Code"},
    VSCODE: {"path": (".vscode", "mcp.json"), "key": "servers", "label": "VS Code"},
}


def server_entry(project_root):
    """
    The server block, with both facts that otherwise go wrong spelled out.

    `sys.executable -m qikly.mcp_server` needs no `PATH` entry, which a bare
    `qikly-mcp` does and frequently does not get on Windows. `QIKLY_PROJECT_ROOT`
    pins the project whatever folder the editor happened to open.
    """
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "qikly.mcp_server"],
        "env": {"QIKLY_PROJECT_ROOT": os.path.abspath(project_root)},
    }


def has_comments(text):
    """
    Whether the text carries a // or /* comment outside a string.

    Deliberately a small scanner rather than a parser. It only has to answer
    "would a JSON round-trip lose something a person wrote", and it answers
    yes when unsure, because a false alarm costs a paste and a miss costs
    the comment.
    """
    in_string = escaped = False
    previous = ""
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif previous == "/" and char in "/*":
            return True
        previous = char
    return False


def _read(path):
    """(text, parsed, error) for a file that may be absent, empty or broken."""
    if not os.path.exists(path):
        return "", {}, None
    if os.path.islink(path):
        # Dotfile managers symlink these out of the project. Following the
        # link writes outside the project, which is the one thing this module
        # promises not to do, so it refuses instead.
        return "", None, ("is a symlink, and following it would write outside "
                          "the project")
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return "", None, "could not be read: %s" % exc
    if not text.strip():
        return text, {}, None
    try:
        # A leading BOM is not valid JSON and PowerShell writes one by
        # default, on the platform this feature exists for. Tolerated for
        # the parse; the comment scan still sees the original text.
        parsed = json.loads(text.lstrip("﻿"))
    except ValueError as exc:
        return text, None, "is not valid JSON: %s" % exc
    if not isinstance(parsed, dict):
        return text, None, "does not hold a JSON object"
    return text, parsed, None


def plan(project_root, hosts=None):
    """
    What would happen to each host's file, without touching any of them.

    Every entry carries an `action`: "create", "add", "current", "differs",
    "comments" or "unreadable". Only the first two write anything.
    """
    out = []
    entry = server_entry(project_root)
    for host in (hosts or sorted(HOSTS)):
        spec = HOSTS[host]
        path = os.path.join(project_root, *spec["path"])
        text, parsed, error = _read(path)
        item = {"host": host, "label": spec["label"], "path": path,
                "key": spec["key"], "entry": entry, "existing": None}
        # Comments first. A JSONC file fails json.loads, so checking the parse
        # error first would report "not valid JSON" for a file that is valid
        # for the host that reads it, and send the user hunting a typo that
        # is not there.
        if text and has_comments(text):
            item["action"] = "comments"
            item["detail"] = ("holds comments, and writing it back as JSON would "
                              "delete them")
        elif error:
            item["action"], item["detail"] = "unreadable", error
        elif not text:
            item["action"] = "create"
        else:
            existing = (parsed.get(spec["key"]) or {}).get("qikly")
            item["existing"] = existing
            if existing is None:
                item["action"] = "add"
            elif existing == entry:
                item["action"] = "current"
            else:
                item["action"] = "differs"
        out.append(item)
    return out


def _backup(path):
    """
    Copy the file aside, to a name nothing can already be using.

    The timestamp alone has one-second resolution, so two writes in the same
    second produced the same name and the second copy silently replaced the
    first, losing the only copy of the original. That is the safety net
    failing in exactly the case it exists for.
    """
    stem = "%s.qikly-backup-%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
    candidate, n = stem, 1
    while os.path.exists(candidate):
        candidate = "%s.%d" % (stem, n)
        n += 1
    shutil.copy2(path, candidate)
    return candidate


def write(item, force=False):
    """
    Apply one planned change, merging into whatever the file already holds.

    Returns (changed, message). Backs the file up first when it exists, since
    the failure this is guarding against is silent loss of somebody else's
    configuration rather than a crash.
    """
    if item["action"] in ("comments", "unreadable"):
        return False, item["detail"] + ". Left alone."

    path = item["path"]
    text, parsed, error = _read(path)
    if error:
        return False, error + ". Left alone."

    # Decide from what is on disk now, not from what plan() saw. The two read
    # the file separately, and between them an editor, another process or a
    # second copy of this command can change it. Trusting the earlier verdict
    # meant an entry appearing in that gap was overwritten without --force ever
    # being consulted, which is the exact case --force exists to gate.
    if text and has_comments(text):
        return False, ("holds comments, and writing it back as JSON would "
                       "delete them. Left alone.")
    existing = (parsed.get(item["key"]) or {}).get("qikly")
    if existing == item["entry"]:
        return False, "already registered, and identical. Nothing to do."
    if existing is not None and not force:
        return False, ("already has a qikly entry that differs from this one. "
                       "Left alone. Use --force to replace it.")

    backup = _backup(path) if os.path.exists(path) else None

    parsed.setdefault(item["key"], {})["qikly"] = item["entry"]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Written beside the target and moved onto it, because "w" truncates on
    # open: a crash between that and the write completing would leave the file
    # holding every other server the user has empty or half written. os.replace
    # is atomic within a directory, so what is on disk is always either the
    # whole old content or the whole new content.
    temporary = path + ".qikly-tmp"
    try:
        with io.open(temporary, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(parsed, indent=2) + "\n")
        os.replace(temporary, path)
    except OSError as exc:
        if os.path.exists(temporary):
            os.remove(temporary)
        return False, "could not be written: %s. Left unchanged." % exc

    what = ("replaced the existing qikly entry in" if existing is not None
            else "created" if not text else "added qikly to")
    return True, "%s %s%s" % (what, path, (", backup at %s" % backup) if backup else "")
