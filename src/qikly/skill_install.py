"""
Copying the bundled Skill into the project you are standing in.

A Skill is a folder an agent reads, and agents look for it under
`.claude/skills/<name>/`. qikly ships one inside the wheel, so this is a copy
rather than a download, and it is the same folder a clone has.

## What it will not do

**Where each agent looks differs**, and the paths come from each tool's
documentation: `.claude/skills/` for Claude Code, `.agents/skills/` as the
cross-agent convention several tools now read, `.cursor/skills/` for Cursor
and `.gemini/skills/` for Gemini CLI.

**Three of the four have now been used in anger**, on 2026-09-27, each in a
throwaway project with a rival skill installed beside this one and a request
that never mentioned qikly:

- `.claude/skills/` loaded in Claude Code.
- `.agents/skills/` loaded in Gemini CLI and in Codex.
- `.cursor/skills/` loaded in Cursor.

`.gemini/skills/` is still only documented, not observed: Gemini CLI reads
both its own directory and the cross-agent one, and installing to both makes
it report every skill as overriding itself, so the test used `.agents/`.

Putting a file where the documentation says is not the same as knowing the
tool loads it, and this module should not imply otherwise for the path where
it is still true.

**It writes where you stand**, not where `QIKLY_PROJECT_ROOT` points. That
variable is how you aim a run at another project, and honouring it here would
write files into a directory you are not in, which is how `--install-mcp` once
created config two folders away with one easily missed line of output.

**It never overwrites without being asked.** A Skill you have edited is yours;
`--force` replaces it, and without that flag an existing folder is left alone
and reported.
"""
import os
import shutil

SKILL_NAME = "qikly"

# Where each agent looks, from each tool's own documentation, read 2026-09-26.
# `agents` is the cross-agent convention several tools now read, and it is the
# one to use when publishing a skill rather than installing it for yourself.
#
# Only the Claude path is tested here. The others are where the documentation
# says to put the file, which is not the same as knowing the tool loads it, and
# the help text says so rather than implying a coverage nobody has checked.
TARGETS = {
    "claude": os.path.join(".claude", "skills", SKILL_NAME),
    "agents": os.path.join(".agents", "skills", SKILL_NAME),
    "cursor": os.path.join(".cursor", "skills", SKILL_NAME),
    "gemini": os.path.join(".gemini", "skills", SKILL_NAME),
}
HOSTS = ("claude", "agents", "cursor", "gemini")

# Kept for callers that predate the other hosts.
TARGET = TARGETS["claude"]


def bundled_dir():
    """Where the Skill lives inside the installed package, or in a clone."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "skills", SKILL_NAME)


def _declared_version(path):
    """
    `metadata.version` out of a SKILL.md, as a comparable tuple, or None.

    Deliberately not a YAML parse: this runs against a file a user may have
    edited, and a malformed one must produce "I cannot tell" rather than an
    exception in the middle of an install.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("version:"):
                    raw = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    return tuple(int(part) for part in raw.split("."))
    except Exception:
        return None
    return None


def is_stale(destination):
    """
    True when the installed Skill is older than the one this qikly ships.

    `pip install --upgrade qikly` replaces the package and cannot touch a Skill
    already copied into somebody's project, so an upgrade leaves them with
    instructions that name a different set of commands. Nothing said so: the
    installer reported "already exists, nothing was changed" whether the copy
    on disk was identical or three releases behind.

    Returns None when either version cannot be read, because "I do not know"
    and "it is current" must not print the same thing.
    """
    theirs = _declared_version(os.path.join(destination, "SKILL.md"))
    ours = _declared_version(os.path.join(bundled_dir(), "SKILL.md"))
    if theirs is None or ours is None:
        return None
    return theirs < ours


def install_all(root, hosts=None, force=False, dry_run=False):
    """
    Install for each named host. Returns [(host, destination, outcome, backup)].

    A list rather than a dict because the order matters in the output: people
    read the first line and stop, so `claude` comes first and the rest follow
    in the order they were asked for.
    """
    chosen = list(hosts or ["claude"])
    if "all" in chosen:
        chosen = list(HOSTS)
    out = []
    for host in chosen:
        try:
            destination, outcome, backup = install(
                root, force=force, dry_run=dry_run, host=host)
        except Exception as exc:
            # One host failing must not take the others with it, and must not
            # arrive as a traceback. A plain file sitting where `.cursor/`
            # should be raises from makedirs, and with `all` that abandoned
            # the run after two hosts had already been written, with no
            # summary of what had happened.
            out.append((host, os.path.join(root, TARGETS[host]),
                        "failed: %s: %s" % (type(exc).__name__, exc), None))
            continue
        out.append((host, destination, outcome, backup))
    return out


def install(root, force=False, dry_run=False, host="claude"):
    """
    Copy the Skill into `root`. Returns (destination, outcome, backup).

    The outcomes a caller has to tell apart are "written", "exists",
    "would write" and "missing": "exists" is not a failure, and "missing"
    means a wheel built without its package data, which is worth saying
    plainly rather than reporting as an empty success. `backup` is where
    anything already there was moved, or None.
    """
    source = bundled_dir()
    destination = os.path.join(root, TARGETS[host])

    if not os.path.isfile(os.path.join(source, "SKILL.md")):
        return destination, "missing", None
    # `exists` has to mean "something is already there", not "a directory is
    # already there". A plain file at that path fell through both branches
    # below and reached copytree, which raised FileExistsError as a raw
    # traceback where every other outcome is a sentence.
    if os.path.exists(destination) and not force:
        return destination, "exists", None
    if dry_run:
        return destination, "would write", None

    saved = _backup(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copytree(source, destination)
    return destination, "written", saved


def _backup(destination):
    """
    Move anything already there aside, and say where it went.

    `--install-mcp` backs up every file it overwrites, and this did not: it
    deleted the destination outright, so `--force` over a Skill somebody had
    edited destroyed it with no recovery path. Two sibling commands should not
    disagree about whether your edits survive.
    """
    if not os.path.exists(destination):
        return None
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = "%s.backup-%s" % (destination, stamp)
    # Seconds are not unique enough. Two --force installs inside one second
    # gave the same name, and `shutil.move` onto an existing directory moves
    # the source *inside* it, so the second backup ended up one level deeper
    # while the message still pointed at the top. Nothing was lost and
    # everything was misreported.
    suffix = 2
    while os.path.exists(saved):
        saved = "%s.backup-%s-%d" % (destination, stamp, suffix)
        suffix += 1
    shutil.move(destination, saved)
    return saved


def files_in(directory):
    """Every file the Skill consists of, relative to its own folder."""
    out = []
    for base, _dirs, names in os.walk(directory):
        for name in sorted(names):
            out.append(os.path.relpath(os.path.join(base, name), directory))
    return sorted(out)
