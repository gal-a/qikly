"""
Which code produced a run, precisely enough to go back to it.

A run summary already recorded `qikly_version`, and for an install from PyPI
that is exact: a released version is one immutable artefact. For a source
checkout it is not. The version string only moves on release day, so 420 runs in this
project's own history are stamped `0.1.0` across weeks of changing code, and
"reproduce the run that produced this number" has no answer left in the file.

So when qikly is running out of its own git checkout, the commit is recorded
as well, with whether the tree had uncommitted changes and whether that commit
is a tag.

**The trap this is written around.** A virtual environment commonly lives
inside the user's own repository, which puts `site-packages/qikly` under
*their* git root. Asking git about the package directory would then record
their commit as qikly's: not a gap but a wrong answer, and one that looks
authoritative. So a git root is only believed when it actually contains
`src/qikly`, which is qikly's own layout and nobody else's.

Never raises. A run that produced real output must not fail while recording
what produced it, so anything unavailable is simply absent.
"""
import os
import shutil
import subprocess
import sys

# Long enough for a cold git on Windows, short enough that a hung git cannot
# hold up a run that has already done the work.
_TIMEOUT = 5

_CACHE = None


def _git(args, cwd):
    """One git command, its stripped stdout, or None for anything unusable."""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        done = subprocess.run([exe] + list(args), cwd=cwd, timeout=_TIMEOUT,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True)
    except Exception:                                # noqa: BLE001
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def checkout_root(package_dir):
    """
    The qikly checkout this package lives in, or None.

    None covers both ordinary cases: an install from PyPI, and a package that
    happens to sit inside somebody else's repository. The second is the one
    worth refusing rather than guessing at.
    """
    top = _git(["rev-parse", "--show-toplevel"], package_dir)
    if not top:
        return None
    if not _same_path(os.path.join(top, "src", "qikly"), package_dir):
        return None
    return top


def _collect():
    import qikly

    out = {"qikly_version": getattr(qikly, "__version__", None),
           "python_version": sys.version.split()[0]}
    try:
        package_dir = os.path.dirname(os.path.abspath(qikly.__file__))
        root = checkout_root(package_dir)
        if root:
            out["git_commit"] = _git(["rev-parse", "--short=12", "HEAD"], root)
            # Scoped to src: a change under tests/ or docs/ did not alter what
            # ran. Untracked files count, because a new module is a change.
            out["git_dirty"] = bool(_git(["status", "--porcelain", "--", "src"], root))
            tag = _git(["describe", "--tags", "--exact-match", "HEAD"], root)
            if tag:
                out["git_tag"] = tag
    except Exception:                                # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v is not None}


def identity(refresh=False):
    """
    What is running, as a dict to fold into a run's provenance.

    Cached, because a run asks three or four times (summary, both report
    headers, the opening line) and the answer cannot change inside one
    process. Returns a copy so a caller cannot corrupt the cache.
    """
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = _collect()
    return dict(_CACHE)


def describe(info=None):
    """One line for a console banner or a report header."""
    info = identity() if info is None else info
    text = "qikly %s" % info.get("qikly_version", "unknown")
    if info.get("git_tag"):
        text += " (tag %s)" % info["git_tag"]
    elif info.get("git_commit"):
        text += " (commit %s)" % info["git_commit"]
    if info.get("git_dirty"):
        text += ", uncommitted changes"
    return text
