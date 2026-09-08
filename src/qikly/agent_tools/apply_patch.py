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


def _resolve_targets(patch_path):
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
    return strip, resolved


# What a non-GNU patch says when handed a GNU long option. Consulted only on
# the failure path, so the common case pays nothing for the check.
_WRONG_FLAVOUR = ("unrecognized option", "unknown option", "illegal option",
                  "invalid option", "unrecognised option")


def _looks_like_wrong_patch_flavour(output):
    lowered = (output or "").lower()
    return any(marker in lowered for marker in _WRONG_FLAVOUR)


def apply_patch(patch_path):
    """
    Apply a unified diff patch to the codebase.
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
        strip, _targets = _resolve_targets(patch_path)
        base_args = [patch_exe, f"-p{strip}", "--fuzz=3", "-i", patch_path]

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
