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

**GitHub Copilot reads none of them**, which is why it needs a shape of its
own. It reads instruction files out of `.github/instructions/`, so that host
writes the Skill folder there and a `qikly.instructions.md` beside it: the
folder holds the content, and the pointer is the file Copilot opens. Copying
the folder alone would have put files on disk that nothing ever reads, which
is the failure this target exists to avoid rather than repeat.

**Three of the five have now been used in anger**, on 2026-09-27, each in a
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

**The Copilot pointer is the one exception, and it is backed up rather than
left alone.** That file is generated, it has to describe the folder beside it,
and a stale one points at a Skill that has moved. So it is rewritten on every
install, and anything already under that name is moved to a timestamped copy
first, because `.github/instructions/` is a directory people write their own
files into and the name is ours by convention rather than by right.
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
    # GitHub Copilot reads none of the four above. It reads instruction files
    # out of `.github/instructions/`, so this target writes the same folder
    # there and adds the one file Copilot opens, which points at it.
    "copilot": os.path.join(".github", "instructions", SKILL_NAME),
}
HOSTS = ("claude", "agents", "cursor", "gemini", "copilot")

# The file VS Code actually reads for Copilot. It sits beside the folder rather
# than inside it, because `.github/instructions/*.instructions.md` is the
# pattern Copilot looks for and a file one level down is never opened.
POINTER = os.path.join(".github", "instructions", SKILL_NAME + ".instructions.md")

POINTER_TEXT = """---
applyTo: "**"
---

# qikly

When the request is about writing tests, about whether an existing suite is
worth trusting, or about turning a specification into checks, read
`%s/SKILL.md` beside this file and follow it.

In one sentence: qikly writes the tests from the acceptance criteria and keeps
those criteria from the agent that writes the code, so that a passing suite
means something. `qikly --score-code PATH --score-tests PATH` scores a suite
that already exists, free, with no API key and nothing of theirs modified.
""" % SKILL_NAME

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


# What a bare `--install-skill` writes when the project shows no sign of which
# agent is in use. Claude Code's own path, plus the cross-agent one that Codex
# and Gemini CLI both read, which is three of the five runtimes for two
# directories. Cursor is left out on purpose: it reads only its own path, and
# writing a directory for a tool somebody may not have is worse than telling
# them the flag exists.
FALLBACK = ("claude", "agents")


def detect(root):
    """
    Which agent conventions this project already uses.

    A bare `--install-skill` used to write `.claude/skills/` and nothing else,
    so somebody working in Cursor got a directory their editor does not read,
    no error, and no hint that three other conventions existed. The evidence
    is already on disk: a project with `.cursor/` in it belongs to somebody
    using Cursor.
    """
    found = [host for host in HOSTS
             if host != "copilot"
             and os.path.isdir(os.path.join(root, "." + host))]
    # Copilot has no directory of its own to look for. `.github/` is in almost
    # every repository and proves nothing, so the signal is somebody already
    # writing Copilot instructions, which is a decision rather than a default.
    if (os.path.isdir(os.path.join(root, ".github", "instructions"))
            or os.path.isfile(os.path.join(root, ".github",
                                           "copilot-instructions.md"))):
        found.append("copilot")
    # Never both. Gemini CLI reads its own directory and the cross-agent one,
    # and finding the Skill in both makes it report every skill as overriding
    # itself. `.agents/` is the path that has actually been watched loading.
    if "gemini" in found and "agents" in found:
        found.remove("gemini")
    return found


def install_all(root, hosts=None, force=False, dry_run=False):
    """
    Install for each named host. Returns [(host, destination, outcome, backup)].

    A list rather than a dict because the order matters in the output: people
    read the first line and stop, so `claude` comes first and the rest follow
    in the order they were asked for.
    """
    chosen = list(hosts or ["auto"])
    if "all" in chosen:
        chosen = list(HOSTS)
    elif "auto" in chosen:
        chosen = detect(root) or list(FALLBACK)
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
    # Copilot is the one host that writes two things: the folder, and the file
    # Copilot actually opens. Both have to be considered together, or every
    # promise this module makes about the folder is broken for the file.
    pointer = os.path.join(root, POINTER) if host == "copilot" else None

    if not os.path.isfile(os.path.join(source, "SKILL.md")):
        return destination, "missing", None

    # Found before anything is copied. A directory sitting where the pointer
    # goes cannot be written, and discovering that after copytree left the
    # Skill folder on disk while the command reported that nothing was
    # written: partial state, described as failure.
    if pointer and os.path.exists(pointer) and not os.path.isfile(pointer):
        return destination, "blocked", None

    # `exists` has to mean "something is already there", not "a directory is
    # already there". A plain file at that path fell through both branches
    # below and reached copytree, which raised FileExistsError as a raw
    # traceback where every other outcome is a sentence.
    if os.path.exists(destination) and not force:
        # A Copilot folder with no pointer beside it is an install that cannot
        # load, and it reported as "already exists, nothing was changed",
        # which is accurate about the folder and wrong about the install.
        if pointer and not os.path.isfile(pointer):
            if dry_run:
                return destination, "would write pointer", None
            _write_pointer(root)
            return destination, "pointer", None
        return destination, "exists", None
    if dry_run:
        return destination, "would write", None

    saved = _backup(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copytree(source, destination)
    if pointer:
        saved = _write_pointer(root, force=force) or saved
    return destination, "written", saved


def _write_pointer(root, force=False):
    """
    The one file Copilot opens, beside the folder it points at. Returns where
    anything already there was moved, or None.

    Copilot does not read a skills directory, so copying the folder alone
    would put files on disk that nothing ever opens.

    **It backs up whatever was there**, for the same reason `_backup` exists
    for the folder: this path is inside `.github/instructions/`, which is a
    directory people write their own instruction files into, and a bare
    `open(path, "w")` destroyed one with no `--force`, no warning and no
    recovery. The name is ours by convention, not by right.
    """
    path = os.path.join(root, POINTER)
    saved = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                already = handle.read()
        except Exception:
            already = None
        # Rewriting our own generated file is not an overwrite worth a backup.
        if already != POINTER_TEXT:
            saved = _backup(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(POINTER_TEXT)
    return saved


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
