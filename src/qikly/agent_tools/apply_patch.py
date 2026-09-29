import os
import posixpath
import shutil
import subprocess


def _find_patch_exe():
    """
    Locate a GNU `patch` binary.

    `gpatch` is tried first, and the order is the point. macOS ships Apple's
    BSD patch as `patch`, which rejects the GNU long options this module sends
    (`--fuzz`, `--dry-run`). The remedy printed below is `brew install gpatch`,
    and Homebrew installs it under the name `gpatch` rather than shadowing the
    system one. Looking for `patch` first therefore found Apple's every time,
    so a user could follow the instructions exactly and see nothing change.

    On Linux and Windows there is no `gpatch`, so this falls through after one
    PATH lookup.

    It is also rarely on PATH on Windows even when Git is installed, since Git
    for Windows ships it under usr\\bin, not cmd\\.
    """
    for name in ("gpatch", "patch"):
        found = shutil.which(name)
        if found:
            return found

    git_exe = shutil.which("git")
    if git_exe:
        candidate = os.path.join(
            os.path.dirname(os.path.dirname(git_exe)), "usr", "bin", "patch.exe"
        )
        if os.path.exists(candidate):
            return candidate

    # Naming the fix, not just the fact. This is the first thing a user on a
    # fresh machine hits, it stops every run dead, and "could not locate" on
    # its own sends them to a search engine for a one-line answer.
    raise RuntimeError(
        "Could not locate the `patch` executable, which qikly needs to apply "
        "the diffs it generates.\n"
        "  Debian/Ubuntu:  apt install patch\n"
        "  macOS:          brew install gpatch  (Apple's own patch is not GNU)\n"
        "  Windows:        install Git for Windows, which ships GNU patch "
        "under usr\\bin; qikly finds it there without any PATH change.")


# Patches may only write here. Nothing else in the tree is the agent's to
# touch, and a diff that resolves anywhere else is a bug rather than a fix.
CODE_ROOT = "outputs/agent_src/code/"


def _resolve_targets(patch_path, code_dir=None):
    """
    Work out which files a diff will write to, and the -p level that yields
    them. Returns (strip_level, [paths]).

    Why this is not just "-p1": that assumes every diff arrives with git's
    a/ and b/ prefixes. The PATCH format in code_agent.md does ask for them,
    but the model does not always comply, and a bare header like

        --- outputs/agent_src/code/CALC_TAX/calc.py

    under -p1 has its *first real component* stripped instead of a prefix,
    so the patch lands in a phantom `agent_src/code/CALC_TAX/calc.py` tree.
    It applies cleanly, the real implementation is untouched, the failure is
    unchanged, and the loop burns an attempt believing it made a change.
    Observed once in 6 patches on a live run, and zero times in 6,056
    archived ones, so it is rare, silent, and expensive when it fires.

    Choosing the level from the header instead makes the applier correct for
    both shapes, and the CODE_ROOT check then catches anything that still
    resolves somewhere it has no business writing to.
    """
    dests = []
    with open(patch_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("+++ "):
                # Strip a trailing timestamp column if the diff carries one.
                dests.append(line[4:].strip().split("	")[0].replace("\\", "/"))

    dests = [d for d in dests if d and d != "/dev/null"]
    if not dests:
        raise RuntimeError("diff names no destination file")

    prefixed = [d.startswith("b/") for d in dests]
    if all(prefixed):
        strip, resolved = 1, [d[2:] for d in dests]
    elif not any(prefixed):
        strip, resolved = 0, list(dests)
    else:
        # One -p applies to the whole file, so a mixed diff cannot be applied
        # correctly at any level. Reject it and let the loop regenerate.
        raise RuntimeError(
            "diff mixes 'b/'-prefixed and bare destination paths, so no single "
            f"-p level is correct for it: {', '.join(dests)}"
        )

    # Repair before the boundary check, never after. A repaired path is one
    # of `code_dir`'s own files, so it passes the check below on its merits;
    # putting the repair afterwards would be putting it outside the boundary,
    # which is the one place it must not be.
    repairs = {}
    if code_dir:
        missing = [r for r in resolved if not os.path.isfile(r)]
        if missing:
            existing = _existing_files(code_dir)
            for target in missing:
                fixed = _repair_destination(target, existing)
                if fixed:
                    repairs[target.replace("\\", "/")] = fixed
            # All or nothing. Repairing some paths and not others would apply
            # some hunks and leave the rest, which is the non-atomic state the
            # dry run exists to prevent.
            #
            # Counted against the DISTINCT missing paths. `repairs` is keyed by
            # path, so a diff naming the same file twice collapsed to one key
            # and then failed this comparison, discarding a repair that was
            # complete. Found by audit 2026-09-29.
            if len(repairs) != len({m.replace("\\", "/") for m in missing}):
                repairs = {}
            else:
                resolved = [repairs.get(r.replace("\\", "/"), r) for r in resolved]

    # Normalise before checking, or `outputs/agent_src/code/../../../x` walks
    # straight out of the sandbox while still matching the prefix.
    outside = [
        r for r in resolved
        if not posixpath.normpath(r).startswith(CODE_ROOT.rstrip("/") + "/")
    ]
    if outside:
        raise RuntimeError(
            f"diff would write outside {CODE_ROOT}: {', '.join(outside)}"
        )
    return strip, resolved, repairs


# What a non-GNU patch says when handed a GNU long option. Consulted only on
# the failure path, so the common case pays nothing for the check.
_WRONG_FLAVOUR = ("unrecognized option", "unknown option", "illegal option",
                  "invalid option", "unrecognised option")


def _existing_files(code_dir):
    """
    Every file under the task's own directory, as posix paths relative to the
    working directory.

    Relative, and that matters rather than being cosmetic: a repaired path
    goes on to face the CODE_ROOT boundary check, which compares against the
    relative literal `outputs/agent_src/code/`. An absolute path fails that
    check however legitimate it is, so a caller passing an absolute
    `code_dir`, which the tests do and a future caller might, would have
    every repair rejected by the guard rather than by the matcher.
    """
    found = []
    for folder, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "old")]
        for name in files:
            path = os.path.join(folder, name)
            try:
                path = os.path.relpath(path)
            except ValueError:
                # A different drive on Windows, so there is no relative form
                # and no repair that could pass the boundary check anyway.
                continue
            found.append(path.replace("\\", "/"))
    return found


def _repair_destination(named, existing):
    """
    The file a diff meant, when the path it wrote does not exist.

    Matched by longest unique path suffix, and only that. Suffixes are tried
    from the whole path downwards, and the first length that matches anything
    decides: exactly one match is the answer, more than one is ambiguous and
    gets no answer at all. Guessing between two files called `money.py` in
    different subpackages would be worse than refusing.

    Returns None when there is no unique answer, which leaves the caller to
    fail exactly as it did before this existed.
    """
    parts = [p for p in named.replace("\\", "/").split("/") if p not in ("", ".")]
    # A bare filename is never enough evidence, so the shortest suffix tried
    # is two components. Raised from one after an audit on 2026-09-29 pointed
    # out the case it opens: a FIX that means to *create* `helpers.py`, while
    # an unrelated `helpers.py` already exists somewhere else under the task,
    # would have its new file silently repointed at the old one. Two
    # components is what the case this exists for actually needs
    # (`salespkg/etl.py`), and it costs only the flat shape `etl.py`, which
    # never had this repair and converged without it for many releases.
    for length in range(len(parts), 1, -1):
        suffix = "/".join(parts[-length:])
        matches = [f for f in existing
                   if f == suffix or f.endswith("/" + suffix)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return None


def _rewrite_destinations(patch_path, repairs):
    """A copy of the diff with its `---`/`+++` paths corrected, on disk.

    A copy rather than an edit: the diff the model actually produced stays
    where it was written, because the transaction log names it and a run's
    record should show what was generated rather than what was salvaged.
    """
    with open(patch_path, encoding="utf-8", errors="replace") as handle:
        lines = handle.read().split("\n")
    out = []
    for line in lines:
        for marker in ("--- ", "+++ "):
            if not line.startswith(marker):
                continue
            body = line[len(marker):].strip().split("\t")[0]
            prefix = body[:2] if body[:2] in ("a/", "b/") else ""
            bare = body[len(prefix):]
            fixed = repairs.get(bare.replace("\\", "/"))
            if fixed:
                # The prefix goes back on. `-p` is chosen once for the whole
                # diff from whether the destinations carried one, so dropping
                # it here would leave the strip level describing the file this
                # was before it was rewritten: at -p1 the corrected path loses
                # its first real component and names nothing again.
                line = marker + prefix + fixed
            break
        out.append(line)
    handle_path = patch_path + ".resolved"
    with open(handle_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(out))
    return handle_path


def _looks_like_wrong_patch_flavour(output):
    lowered = (output or "").lower()
    return any(marker in lowered for marker in _WRONG_FLAVOUR)


def apply_patch(patch_path, code_dir=None):
    """
    Apply a unified diff patch to the codebase.

    `code_dir` is the task's own directory, and passing it turns on one
    narrow repair: a diff naming a file that does not exist is matched, by
    unique path suffix, against the files that do. Small models drop a
    directory from a path they were asked to copy, and with a package-seeded
    implementation there is one more directory to drop, so every patch in a
    run came back naming `outputs/agent_src/code/pkg/etl.py` with the task's
    own directory missing. Ten of ten were rejected, the failure never
    changed, and the stage spent its whole budget on it.

    Left as None, and on any diff whose paths all resolve, nothing about this
    function's behaviour differs from before that repair existed. It is
    reachable only from the state where the patch was about to be discarded,
    and it never searches outside `code_dir`, so it cannot reach another
    task's files.
    Uses GNU `patch` (with fuzz tolerance) rather than `git apply`, since
    LLM-generated diffs are often slightly off on line numbers/context and
    `git apply` refuses those with no fuzz margin.

    Gated behind a --dry-run check so application is all-or-nothing. GNU
    patch applies hunks non-atomically: a multi-hunk diff where some hunks
    succeed and others fail still mutates the file with the successful
    hunks, while exiting nonzero. Without the dry-run gate, the caller
    (orchestrator.py's FIX/PATCH loop) sees that nonzero exit, treats it as
    "nothing changed", and asks the model for a fresh patch against what it
    still believes is the pre-patch file -- but the file has silently
    drifted. The model's next patch then re-includes the hunk that already
    landed; patch reports "previously applied" and (stdin isn't a tty, so it
    defaults to declining the reverse-apply prompt) refuses the *whole*
    patch, including the genuinely new hunk that would have fixed things.
    Observed getting stuck on exactly this for many iterations in a row.
    A clean dry run guarantees the real apply behaves identically, so the
    file on disk always matches what the model was told it looks like.
    """
    try:
        patch_exe = _find_patch_exe()
        strip, _targets, repairs = _resolve_targets(patch_path, code_dir)

        # No repair means no rewrite, and the diff is handed to `patch`
        # exactly as it was written. Every path already resolving is the only
        # way to get here on a correct diff, so the case that has always
        # worked cannot be touched by any of this.
        applied_path = _rewrite_destinations(patch_path, repairs) if repairs else patch_path

        base_args = [patch_exe, f"-p{strip}", "--fuzz=3", "-i", applied_path]

        dry_run = subprocess.run(
            base_args + ["--dry-run"], capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        if dry_run.returncode != 0:
            # Told apart before it is reported, because these look identical to
            # the caller and mean completely different things. A hunk that will
            # not apply is the loop working as designed. An unrecognised flag
            # means this binary is not GNU patch, so no diff will ever apply
            # and every remaining attempt in the run is wasted.
            combined = f"{dry_run.stdout}{dry_run.stderr}"
            if _looks_like_wrong_patch_flavour(combined):
                raise RuntimeError(
                    f"`{patch_exe}` does not accept GNU patch's options, so it "
                    f"is a different implementation (Apple and BSD ship one). "
                    f"qikly needs GNU patch: --fuzz is what lets a diff with "
                    f"slightly wrong line numbers still apply, and without it "
                    f"no generated patch will land.\n"
                    f"  macOS: brew install gpatch, then put it ahead on PATH.\n"
                    f"Original error:\n{combined}")
            # GNU patch writes hunk-failure details to stdout, not stderr.
            raise RuntimeError(f"Patch failed:\n{combined}")

        result = subprocess.run(base_args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            # The dry run passed but the real apply didn't (e.g. a
            # concurrent modification) -- surface it rather than assuming
            # the file matches what the dry run predicted.
            raise RuntimeError(f"Patch failed on real apply after a clean dry run:\n{result.stdout}{result.stderr}")

    except Exception as e:
        raise RuntimeError(f"Error applying patch: {e}")
