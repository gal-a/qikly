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


# The tail of a frame, which is how pytest names one at every traceback rung:
# "code\\pricing.py:5" for a frame under the rootdir, and an absolute
# "C:\\...\\utils.py:2" for one reached through a relative sys.path entry.
#
# Only the tail. The path itself is found by walking backwards from here,
# never by a pattern, and that is a correctness requirement rather than a
# style. A pattern like `[^\s:]+?\.py:` has to retry at every offset inside
# any long run of characters holding neither a space nor a colon, which is
# quadratic: measured on this machine at 0.21s for 5,000 characters and
# 15.6s for 40,000, four times the work for twice the input. pytest's
# assertion rewriting prints exactly that when it compares two long strings,
# `raw_output` is never truncated on its way here, and this runs on every
# attempt of the convergence loop. A diagnostic that can stall a run for
# minutes is a worse defect than the one it was written to report.
_FRAME_TAIL = re.compile(r"\.py:\d+")

# How many space-separated tokens to absorb leftwards before giving up on a
# path that contains spaces. "C:\Program Files\app\utils.py" needs one; the
# bound stops a line of prose being glued onto a filename.
_MAX_SPACE_TOKENS = 3

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


def _frame_candidates(text):
    """
    Every `<path>.py:<line>` in `text`, as candidate paths, shortest first.

    One left-to-right pass over the tails, and a bounded backward walk from
    each. Linear in the length of the input, which is the whole point: see
    `_FRAME_TAIL` above for what the obvious pattern costs instead.

    Several candidates per frame, because a path may contain spaces and the
    walk has no way to know where such a path begins. The shortest candidate
    is the one that stops at the first space, and each one after it absorbs
    another token to its left. The caller picks the first that is a file, so
    a path without spaces costs exactly one check and nothing changes for it.
    """
    for match in _FRAME_TAIL.finditer(text or ""):
        end = match.start()
        start = end
        while start > 0 and not text[start - 1].isspace() and text[start - 1] != ":":
            start -= 1
        # A Windows drive letter carries the one colon that belongs to the
        # path, so it is the one the walk above is allowed to step over.
        if (start >= 2 and text[start - 1] == ":" and text[start - 2].isalpha()
                and (start == 2 or text[start - 3].isspace())):
            start -= 2
        if end == start:
            continue
        yield text[start:end] + ".py"
        # Now the same frame with more of the line in front of it, for a path
        # that has spaces in it. Never crosses a line break.
        absorbed = start
        for _ in range(_MAX_SPACE_TOKENS):
            probe = absorbed - 1
            while probe > 0 and text[probe - 1] == " ":
                probe -= 1
            if probe <= 0 or text[probe - 1] in "\r\n":
                break
            while probe > 0 and not text[probe - 1].isspace():
                probe -= 1
            if probe == absorbed:
                break
            absorbed = probe
            yield text[absorbed:end] + ".py"


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
    found = set()
    # The same file appears in frame after frame, because a helper called in a
    # loop fails once per row, so deciding each distinct candidate once turns
    # the filesystem work from per-frame into per-path. Measured on 40,000
    # repeated frames: 3.3s before, and the stats were all of it.
    seen = {}
    for candidate in _frame_candidates(raw_output or ""):
        if candidate in seen:
            if seen[candidate]:
                found.add(seen[candidate])
            continue
        seen[candidate] = None
        path = _absolute(os.path.normpath(candidate), project_root)
        if not os.path.isfile(path):
            # Not a file, so this candidate is the wrong slice of the line.
            # The next one for the same frame absorbs another token.
            continue
        if not _inside(path, project_root, project_root):
            continue
        if (_inside(path, code_dir, project_root)
                or _inside(path, tests_dir, project_root)
                or _is_test_file(path)):
            continue
        relative = os.path.relpath(path, os.path.abspath(project_root)).replace("\\", "/")
        seen[candidate] = relative
        found.add(relative)
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
