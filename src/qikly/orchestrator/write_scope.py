"""
Which files a task is allowed to write, and what to say when the fault is not
in one of them.

A task owns exactly one directory, ``outputs/agent_src/code/<task_id>/``.
``apply_patch`` refuses any diff that lands outside it, so the coding agent
cannot repair a helper module the implementation merely imports. That
restriction is deliberate and is not what this module changes.

What it changes is what happens next. Until now a fault in an imported helper
was **detected and not repaired**: the generated test failed, correctly, the
agent could not patch the helper, and so it did the only thing left open to
it and changed the module it does own until the test went green. A workaround
that leaves the real defect in place is a worse outcome than not converging,
and nothing in the run said it had happened.

## Two signals, because one of them is blind

**The traceback names a helper only when the helper raises.** Verified
against pytest 9.1 at all three rungs on 2026-09-29: when ``utils.to_cents``
raises, ``utils.py`` appears at ``line``, ``short`` and ``auto`` alike. When
it merely *returns the wrong number*, no rung mentions it at all, because the
only frame is the assertion in the test. The wrong-value case is both the
commoner one and the one that produces the workaround, so a guard reading
tracebacks alone would catch the loud half and miss the dangerous half.

So there are two:

``unwritable_imports`` is static and answers "could this happen here?". It
reads the task's own source and reports the project-local modules it imports
from outside its directory. Cheap, deterministic, no model call.

``implicated_files`` is dynamic and answers "did it just happen?". It reads
pytest's output for project files that are neither the task's code nor its
tests. Precise when it fires, silent when the helper returns quietly.

## Why neither one stops a run

A task that imports a helper is not in trouble; it is normal. Almost every
real project has a ``utils``. Stopping a run at the first sight of one would
refuse work that would have succeeded, which is a worse failure than the one
being prevented. So nothing here aborts anything. The static signal is held
until something else goes wrong and then explains it; the dynamic signal
narrates while the loop keeps working, and is reported at the end whichever
way the run went.

The case worth shouting about is the quiet one: a run that **converged** after
a failure had been traced into a file it could not write. That is the
workaround signature, and it is the one line in here that is a warning rather
than a note.
"""
import ast
import os
import re


# A frame, as pytest prints one at every traceback rung. This is the whole of
# the parsing, and it is one line-anchored pattern on purpose.
#
# Two earlier versions searched the whole output for `.py:` and then worked
# backwards to find where the path began. One used a lazy pattern and went
# quadratic, 15.6s on 40,000 characters and 315s on 200,000, because it had to
# retry at every offset inside any long run of characters holding no space or
# colon, which is exactly what pytest's assertion rewriting prints when it
# compares two long strings. The other walked backwards by hand and needed
# special cases for drive letters and for paths containing spaces.
#
# Both were solving a problem that does not exist. **pytest puts the path at
# the start of the line**, at every rung:
#
#     line    C:\proj\utils.py:2: ValueError: bad amount
#     short   utils.py:2: in to_cents
#     auto    code\pricing.py:5: in total_cents
#
# Anchoring at `^` leaves exactly one place per line where a match can start,
# so the work is linear in the length of the output and no input shape can
# make it otherwise. A drive letter's colon and a space inside a path both
# fall out of `.+?` without being mentioned, which is why the special cases
# they needed are gone rather than fixed.
_FRAME_LINE = re.compile(r"^[ \t]*(.+?\.py):\d+[:\s]", re.MULTILINE)

# Test infrastructure is never the subject of this check, whatever directory
# it is found in.
_TEST_NAMES = ("conftest.py",)


def _is_test_file(path):
    base = os.path.basename(path)
    return base in _TEST_NAMES or base.startswith("test_")


def _absolute(path, base):
    """`path` made absolute against `base` rather than against the process.

    `os.path.abspath` would resolve a relative path against the working
    directory. That is the same thing today, because every entry point calls
    `chdir_to_project_root()` first, and it is an invariant this module has
    no way to enforce. Resolving against the base that was passed in makes
    the answer depend on the arguments alone.
    """
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return os.path.normcase(os.path.abspath(path))


def _inside(path, directory, base="."):
    """True when `path` is `directory` or sits under it."""
    if not directory:
        return False
    path = _absolute(path, base)
    directory = _absolute(directory, base)
    return path == directory or path.startswith(directory + os.sep)


def _module_files(name, project_root):
    """Where a dotted module name could live under the project root."""
    relative = name.replace(".", os.sep)
    return (
        os.path.join(project_root, relative + ".py"),
        os.path.join(project_root, relative, "__init__.py"),
    )


def _imported_names(source):
    """Top-level module names a source file imports, absolute imports only.

    Relative imports are skipped on purpose: `from .helpers import x` cannot
    reach outside the package it is written in, so it is inside the task's
    own directory by construction and can never be the thing this module is
    looking for.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        # A half-written implementation between patches. Nothing to report,
        # and certainly nothing to fail the run over.
        #
        # Not only SyntaxError, which is what this caught until an audit on
        # 2026-09-29. A NUL byte in the source raises ValueError instead
        # ("source code string cannot contain null bytes"), which would have
        # escaped this handler and killed the run from a diagnostic. That is
        # the same class of anomaly the patch writer already works around for
        # a cp1252 byte, and the model is equally capable of emitting this
        # one. Deep nesting raises RecursionError, by the same argument.
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.append(node.module)
    return names


def unwritable_imports(code_dir, project_root="."):
    """
    Project-local modules the task's code imports from outside its own
    directory, as paths relative to the project root, sorted.

    Empty is the normal answer and the common one: every bundled task is
    self-contained. A non-empty answer is not a problem on its own, only a
    reason a later stall might have a cause the loop cannot reach.
    """
    if not os.path.isdir(code_dir):
        return []
    found = set()
    for folder, _dirs, files in os.walk(code_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
            except OSError:
                continue
            for module in _imported_names(source):
                # The task's own directory first. A seeded package keeps its
                # folder name, so `from mypkg.money import ...` resolves
                # inside the code directory, and the user's original `mypkg/`
                # usually still sits at the project root as well. Looking
                # there first stops the copy the task owns and repairs being
                # reported as a file it may not write.
                if any(os.path.isfile(c) for c in _module_files(module, code_dir)):
                    continue
                for candidate in _module_files(module, project_root):
                    if not os.path.isfile(candidate):
                        continue
                    if _inside(candidate, code_dir, project_root):
                        continue
                    found.add(os.path.relpath(candidate, project_root).replace("\\", "/"))
    return sorted(found)


def implicated_files(raw_output, code_dir, tests_dir, project_root="."):
    """
    Project files named in pytest's output that the task may not write and
    that are not its tests, as paths relative to the project root, sorted.

    Anything outside the project root is ignored, which is what keeps pytest's
    own frames and every installed dependency out of the answer.
    """
    # Collected into a set before anything touches the filesystem. The same
    # file appears in frame after frame, because a helper called once per row
    # fails once per row, so the distinct paths are far fewer than the frames:
    # 40,000 repeated frames cost one `isfile` rather than 40,000.
    candidates = {m.group(1) for m in _FRAME_LINE.finditer(raw_output or "")}

    found = set()
    for candidate in candidates:
        path = _absolute(os.path.normpath(candidate), project_root)
        if not os.path.isfile(path):
            continue
        if not _inside(path, project_root, project_root):
            continue
        if (_inside(path, code_dir, project_root)
                or _inside(path, tests_dir, project_root)
                or _is_test_file(path)):
            continue
        found.add(os.path.relpath(path, os.path.abspath(project_root)).replace("\\", "/"))
    return sorted(found)


def blocked_fault_message(files, code_dir):
    """The sentence appended to a stall whose cause is outside the task."""
    if not files:
        return ""
    listed = ", ".join(files)
    return (
        f" A failure was traced into {listed}, which this task may not write: "
        f"it owns {code_dir.replace(os.sep, '/')} and nothing else. Fix it there, "
        f"or give it its own task, because the agent can only work around a "
        f"defect it cannot reach."
    )


def unreachable_import_hint(files, code_dir):
    """The softer sentence for a stall with no traceback evidence."""
    if not files:
        return ""
    listed = ", ".join(files)
    return (
        f" This task imports {listed}, which it may not write: it owns "
        f"{code_dir.replace(os.sep, '/')} and nothing else. If the defect is in "
        f"one of those, no patch here can reach it."
    )


def workaround_warning(files, code_dir):
    """Said on a run that converged after a fault was traced somewhere else."""
    if not files:
        return ""
    listed = ", ".join(files)
    return (
        f"Tests passed, but a failure during this run was traced into {listed}, "
        f"which this task may not write: it owns "
        f"{code_dir.replace(os.sep, '/')} and nothing else. The suite may be "
        f"green because the implementation was changed to work around a defect "
        f"that is still there. Worth reading the final diff before trusting "
        f"this one."
    )
