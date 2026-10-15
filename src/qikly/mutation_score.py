"""
Scoring your own suite by breaking your own code, without any model call.

A run tells you the suite passed. It cannot tell you the suite would have
noticed if the code were wrong, and those are different questions: a suite
that tests nothing passes everything. So this plants one deliberate fault at a
time in the implementation a run produced, re-runs the suite against each, and
reports how many it caught.

    qikly --score-suite --tasks CALC_TAX

Caught means the suite failed on the broken code, which is the suite doing its
job. Missed means the suite passed code that is now wrong, which is a gap at
that exact point, named in the report so it can be read rather than guessed at.

## Why it refuses to print a score when the data cannot reach the criteria

This is the one thing the feature had to get right, and it is the reason it
was built second. Run mutation scoring on fixtures that never exercise half
the criteria and it returns roughly the number this project's own research
kept returning: about two thirds missed. A user reading that would draw a
conclusion about their suite that belongs to their data. The suite never had a
chance to catch those faults, because no input row makes the mutated line run.

So the report leads with the reachability check, and when criteria are
unreachable it says so above the score, in those terms.

## No model calls, and nothing of yours is modified

Mutants are written into a temporary workspace that is deleted afterwards.
Your implementation, your suite and your fixtures are read and never written.
"""
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

from qikly.mutation import FAMILIES, count_sites, make_mutant

CODE_ROOT = os.path.join("outputs", "agent_src", "code")
TEST_ROOT = os.path.join("outputs", "tests")
OUT_DIR = os.path.join("outputs", "reports", "mutation_score")
STAGES = ("integration", "system")

# Enough for a number worth reading, few enough to stay in the seconds rather
# than the minutes: each mutant is a full pytest run of two stages.
DEFAULT_MUTANTS = 12


def implementation(task_id, root=CODE_ROOT):
    """
    (real path, path relative to the project) for each implementation file.

    Both, never just the first, because the mutant goes into a temporary copy
    and `os.path.join(workspace, path)` silently discards the workspace
    whenever `path` is absolute. That is not theoretical: with an absolute
    `root` the mutant and its own restore would both land on the user's real
    file, overwriting an implementation this module promises never to touch.
    Carrying the relative half makes the join safe by construction rather than
    by remembering.
    """
    directory = os.path.join(root, task_id)
    if not os.path.isdir(directory):
        return []
    # Walked, not listed. An implementation seeded as a package sits one level
    # down, under the folder's own name, so a flat `os.listdir` found no `.py`
    # files at all and the score reported "nothing to score" for a perfectly
    # ordinary two-module implementation. Indistinguishable from a trivial
    # one, which is the worst way for a measurement to fail. Found by audit
    # 2026-09-29. `load_codebase` has always walked; this now agrees with it.
    found = []
    # Not `sorted(os.walk(...))`. That drains the generator before the body
    # runs, so it has already descended into every subdirectory and the
    # `dirs[:]` pruning below is a no-op: the in-place trick only steers a
    # live walk. Found by audit 2026-09-29, which put a stray `.py` inside a
    # `__pycache__` and watched it come back. Sorting `dirs` in place gives
    # the deterministic order the seeded fault sample needs, and prunes.
    for folder, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if not name.endswith(".py") or name.startswith("__"):
                continue
            real = os.path.join(folder, name)
            relative = os.path.relpath(real, directory)
            found.append((real, os.path.join(CODE_ROOT, task_id, relative)))
    return found


def suite_dirs(task_id, root=TEST_ROOT):
    """The stage directories of the current suite."""
    return [os.path.join(root, task_id, stage) for stage in STAGES
            if os.path.isdir(os.path.join(root, task_id, stage))]


# Directories never worth copying into a scratch workspace, and the ones most
# likely to make a copy enormous rather than merely large.
_SKIP = ("__pycache__", ".git", ".hg", ".svn", ".venv", "venv", "env",
         "node_modules", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
         "site-packages", "dist", "build", ".idea", ".vscode")

# A copy above this is a sign the wrong directory was chosen, not a sign of a
# big project. Refusing with an explanation beats copying a gigabyte in silence.
_MAX_FILES = 4000


class Target(object):
    """
    What to mutate, what to run against it, and what to copy so it runs.

    Both entry points produce one of these. The module used to thread a task
    id through every function, which fixed the layout to
    `outputs/agent_src/code/<task>/` and `outputs/tests/<task>/<stage>/`: a
    converged run's own output, and nothing else. That is the least likely
    thing a newcomer has. Everyone has a suite before they have a task file.
    """

    def __init__(self, label, files, suites, root, task_id=None):
        self.label = label      # what the report calls this
        self.files = files      # [(real path, path relative to root)]
        self.suites = suites    # paths relative to root, passed to pytest
        self.root = root        # the directory copied into the workspace
        self.task_id = task_id  # only a qikly task has one
        # The same files copied from a wider root, tried only when this one
        # cannot run the code. See from_paths.
        self.fallback = None

    def __bool__(self):
        return bool(self.files and self.suites)

    __nonzero__ = __bool__


def from_task(task_id, code_root=CODE_ROOT):
    """The original shape: a converged run's own implementation and suite."""
    return Target(label=task_id,
                  files=implementation(task_id, code_root),
                  suites=suite_dirs(task_id),
                  root=os.getcwd(),
                  task_id=task_id)


def _nearby_suite(code, tests):
    """
    A hint naming test files that do exist, for a `--score-tests` path that
    does not.

    The usual cause is a `test_*.py` sitting beside the module rather than in
    the `tests/` folder the command names. A bare "no suite at ...\\tests" sent
    a first-time user looking for something that was there all along.
    """
    import glob

    here = os.path.dirname(code) if os.path.isfile(code) else code
    seen, found = set(), []
    for folder in (here, os.path.dirname(tests)):
        for pattern in ("test_*.py", "*_test.py"):
            for match in sorted(glob.glob(os.path.join(folder, pattern))):
                if match not in seen:
                    seen.add(match)
                    found.append(match)
    if not found:
        return (". Point --score-tests at a test file or a folder of them, "
                "for example --score-tests tests/ or --score-tests test_my_module.py")
    names = ", ".join(os.path.basename(f) for f in found[:3])
    # Relative to where the command was typed, which is the folder the given
    # --score-tests path sits in: this process has moved to a project root by
    # now, so the working directory says nothing about where the user is.
    pick = found[0]
    try:
        rel = os.path.relpath(found[0], os.path.dirname(tests))
        pick = found[0] if rel.startswith("..") else rel
    except ValueError:
        pass
    return (f". Found {names} next to it: try --score-tests "
            f"{pick if ' ' not in pick else repr(pick)}")


def from_paths(code, tests):
    """
    An implementation and a suite that already exist, anywhere.

    The workspace is a copy of the nearest directory containing both, because
    a suite imports whatever it imports and copying less breaks it in ways
    that look like a caught fault. `_SKIP` keeps that copy to source rather
    than to a virtualenv, and `_MAX_FILES` refuses rather than copying a tree
    that was clearly not what anyone meant.
    """
    code, tests = os.path.abspath(code), os.path.abspath(tests)
    for path, what in ((code, "implementation"), (tests, "suite")):
        if not os.path.exists(path):
            raise ValueError(f"no {what} at {path}" + (
                _nearby_suite(code, tests) if what == "suite" else ""))

    try:
        root = os.path.commonpath(
            [os.path.dirname(code) if os.path.isfile(code) else code,
             os.path.dirname(tests) if os.path.isfile(tests) else tests])
    except ValueError:
        # Different drives on Windows. commonpath's own message is accurate
        # and says nothing about what to do, unlike every other failure here.
        raise ValueError(
            f"the code and the tests are on different drives, so there is no "
            f"directory holding both to copy.\n  code:  {code}\n"
            f"  tests: {tests}")

    # The directory holding both can be a package itself, when the suite lives
    # inside it: `--score-code src/widget --score-tests src/widget/tests`.
    # Copying only that directory leaves no `widget` in the workspace, so a
    # suite doing `from widget.calc import ...` imported the original and
    # every mutant ran against untouched code. The fix is to copy from the
    # directory above the package instead.
    #
    # But not always. A flat project with a stray empty `__init__.py`, whose
    # suite does `from calc import ...`, is broken by that climb: `calc` is no
    # longer importable from the copy's root, and the untouched code was
    # reported as failing its own suite. The two layouts differ only in how
    # the suite imports, which nothing here can see in advance, so the climbed
    # root is kept as a fallback and `score` tries it only when the plain one
    # fails or never runs the code. An audit reproduced both cases.
    climbed = root
    while (os.path.isdir(code) and _inside(tests, code)
           and os.path.isfile(os.path.join(climbed, "__init__.py"))):
        parent = os.path.dirname(climbed)
        if parent == climbed:
            break
        climbed = parent

    if os.path.isfile(code):
        sources = [code]
    else:
        sources = []
        for base, dirs, names in os.walk(code):
            # In place, so os.walk does not descend into them.
            dirs[:] = [d for d in dirs if d not in _SKIP]
            for name in names:
                path = os.path.join(base, name)
                # A suite inside the code directory is not code. Its files
                # were planted with faults too, and a broken test reads as a
                # fault caught, which inflated the score.
                if (name.endswith(".py") and not name.startswith("__")
                        and not _inside(path, tests)):
                    sources.append(path)
        sources.sort()

    if not sources and os.path.isdir(tests) and _inside(code, tests):
        # Everything under the code directory is also under the tests one,
        # so all of it was set aside as suite. Saying "no Python files" would
        # send the reader looking for a missing file instead.
        raise ValueError(
            f"--score-code and --score-tests are the same directory, so "
            f"every file in it counts as a test and there is nothing left to "
            f"mutate.\n  {code}\nPoint --score-tests at the test files "
            f"themselves, for example {os.path.join(code, 'test_*.py')}, or "
            f"move them into a tests/ folder.")
    if not sources:
        raise ValueError(f"no Python files to mutate under {code}")

    def at(base):
        return Target(label=os.path.basename(code.rstrip(os.sep)) or code,
                      files=[(s, os.path.relpath(s, base)) for s in sources],
                      suites=[os.path.relpath(tests, base)],
                      root=base,
                      task_id=None)

    if climbed == root:
        return at(root)
    # The climbed root goes first. The other order was fooled: copying only
    # the package, pytest imported the copy's `__init__.py` as part of
    # collecting its tests, which ran the copied module and fired its marker,
    # while the test itself imported `widget.calc` from the installed copy.
    # The plain root is the fallback, for the flat project whose stray
    # `__init__.py` made the climb happen and whose suite cannot import from
    # the wider copy: that fails its own baseline at once, which is cheap.
    target = at(climbed)
    target.fallback = at(root)
    return target


def _inside(path, directory):
    """
    Whether `path` is `directory` or somewhere under it.

    Case-insensitive where the filesystem is: on Windows `--score-tests
    pkg/tests` names a folder that is `pkg/Tests` on disk, and a
    case-sensitive comparison scored the suite's own files as code.
    """
    n = os.path.normcase
    try:
        return n(os.path.commonpath([path, directory])) == n(directory)
    except ValueError:
        return False


def sites(source):
    """[(family, index, description)] for every fault this can plant."""
    out = []
    for family in FAMILIES:
        for index in range(count_sites(source, family)):
            mutant, described = make_mutant(source, index, family)
            if mutant is not None and mutant != source:
                out.append((family, index, described))
    return out


def _workspace(target, tmp, code_root=CODE_ROOT):
    """A copy of the project a suite can run against, minus the implementation."""
    workspace = os.path.join(tmp, "ws")

    if target.task_id is None:
        # A project qikly did not lay out, so there is no known set of
        # directories to copy: the suite imports what it imports.
        # followlinks, because the copy below dereferences. The two have to
        # agree: counting without following and copying with following was how
        # a project with a linked virtualenv measured as a handful of files and
        # then copied whole. Following needs its own cycle guard, which is why
        # os.walk does not do it by default.
        count, seen = 0, set()
        for base, dirs, names in os.walk(target.root, followlinks=True):
            real = os.path.realpath(base)
            if real in seen:
                # Refuse, rather than prune and carry on. Pruning made the
                # count finish, and the copy below has no visited set of its
                # own, so it followed the same loop until the path length ran
                # out and produced a wall of nested OS errors. A guard that
                # protects the count and not the copy protects nothing.
                raise ValueError(
                    f"a directory link under {target.root} points back at "
                    f"something already inside it, so there is no finite tree "
                    f"to copy:\n  {base}\nPoint --score-code and --score-tests "
                    f"at directories that do not contain that link.")
            seen.add(real)
            dirs[:] = [d for d in dirs if d not in _SKIP]
            count += len(names)
            if count > _MAX_FILES:
                raise ValueError(
                    f"{target.root} holds more than {_MAX_FILES} files, which "
                    f"is almost certainly wider than you meant. Point "
                    f"--score-code and --score-tests at directories closer to "
                    f"the code.")
        # Dereferencing, deliberately, now that the count above follows links
        # too. Recreating the links instead was tried and is worse: a link with
        # an absolute target is recreated pointing at the same place, so the
        # file in the "copy" is the original file, and the first restore raises
        # SameFileError. Worse than that, a mutant written through such a link
        # would land on the user's real source, which is the one thing this
        # module promises can never happen.
        shutil.copytree(target.root, workspace, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*_SKIP))
        return workspace

    for relative in ("inputs_private", "inputs_public", "outputs"):
        if os.path.isdir(relative):
            shutil.copytree(relative, os.path.join(workspace, relative),
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "old"))
    os.makedirs(os.path.join(workspace, code_root, target.task_id), exist_ok=True)
    return workspace


def _resolves_into(workspace, name, env):
    """
    Whether `import name` already lands inside the workspace copy.

    Returns None when the name cannot be imported at all, which is not
    evidence either way: plenty of packages need extras that are not
    installed here.
    """
    if not name.isidentifier() or not os.path.isdir(workspace):
        return None
    try:
        probe = subprocess.run(
            [sys.executable, "-c",
             "import importlib, sys; m = importlib.import_module(sys.argv[1]);"
             " sys.stdout.buffer.write((getattr(m, '__file__', None) or '')"
             ".encode('utf-8'))", name],
            cwd=workspace, capture_output=True, env=env,
            stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        # A probe that cannot even start says nothing about the import, and
        # must not take the whole run down with it.
        return None
    resolved = probe.stdout.decode("utf-8", "replace").strip()
    if probe.returncode != 0 or not resolved:
        return None
    return os.path.realpath(resolved).startswith(
        os.path.realpath(workspace) + os.sep)


def _suite_env(workspace, target):
    """
    The environment the suite runs in, adding a source root only where the
    suite cannot already reach the code being mutated.

    pytest is invoked with cwd=workspace, which puts only the workspace root
    on sys.path. That is enough for a flat layout and not enough for a src/
    one, where the package sits a directory down and the import falls through
    to whatever is installed.

    **Only roots that are not already reachable are prepended**, because a
    prepended directory puts every module in it ahead of the standard
    library. A flat project with a non-package `utils/` holding both `calc.py`
    and `logging.py` would otherwise shadow the real `logging` for the whole
    pytest process, and the suite dies on untouched code. That breaks projects
    that scored correctly before, which is worse than the src/ case this
    exists to fix.
    """
    env = dict(os.environ)
    # No bytecode cache. Mutants come from ast.unparse, so `==` to `!=` or 1
    # to 2 leaves a file the same size, and Python accepts a cached .pyc when
    # the source's size and whole-second mtime match. Two such mutants written
    # within one second, which a small suite manages easily, meant the second
    # ran the first one's bytecode: the same project gave four different
    # "missed" sets across four seeds, including faults its tests plainly
    # catch. Found by an audit on 2026-10-10, and older than the guard below.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    roots = []
    for name, parent in _import_roots(target):
        if not parent:
            # The workspace root is already sys.path[0] under `python -m`.
            continue
        # Only a real package earns a path entry. That is precisely the src/
        # layout this exists for: `src/mdformat/` is a package, so `src` has
        # to be importable from. A loose module such as `utils/calc.py` is
        # not, and adding `utils` would expose every other file beside it,
        # including one named after a standard library module.
        if not os.path.isfile(os.path.join(
                target.root, *(parent.split("/") + [name, "__init__.py"]))):
            continue
        if _resolves_into(workspace, name, env):
            continue
        where = os.path.join(workspace, *parent.split("/"))
        if where not in roots:
            roots.append(where)
    if not roots:
        return env
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        roots + ([existing] if existing else []))
    return env


def _suite_passes(workspace, target, env=None):
    """True only when every stage of the suite passes in this workspace."""
    return _suite_verdict(workspace, target, env) == "pass"


def _drop_bytecode(workspace):
    """
    Delete every cached .pyc in the workspace before a suite run.

    PYTHONDONTWRITEBYTECODE alone was not enough: a test that starts a child
    process with an environment of its own does not pass it on, the child
    writes a cache, and a later same-size mutant written within the same
    second ran that cache. An audit reproduced faults in tested code reported
    missed in four of six seeds that way.
    """
    for base, dirs, _ in os.walk(workspace):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(base, "__pycache__"), ignore_errors=True)
            dirs.remove("__pycache__")


def _suite_verdict(workspace, target, env=None, plugin=None):
    """
    "pass", "fail" or "error" for the suite in this workspace.

    Three outcomes rather than two, because pytest's return codes are not one
    thing: 0 passed, 1 tests failed, and 2 or more means it could not run the
    suite at all, usually a collection error. Reading anything non-zero as
    "the suite noticed" credits a mutant that broke collection as a fault
    caught, when no assertion ever ran.
    """
    _drop_bytecode(workspace)
    for directory in target.suites:
        where = os.path.join(workspace, directory)
        if not os.path.exists(where):
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", where, "-q", "--tb=no",
             # The project's own addopts already carry -q, and -qq suppresses
             # the count line entirely, so every parsed count reads as zero,
             # which looks exactly like a suite that ran and passed.
             "-o", "addopts=", "-p", "no:cacheprovider"]
            + (["-p", plugin] if plugin else []),
            cwd=workspace, capture_output=True, text=True, env=env)
        if result.returncode >= 2:
            return "error"
        if result.returncode != 0:
            return "fail"
    return "pass"


def _import_roots(target):
    """
    Each top-level package or module the mutated files belong to, with the
    directory it has to be imported from, both relative to the workspace.

    A file climbs out of its package by following `__init__.py` upwards, so
    `src/mdformat/_cli.py` yields ("mdformat", "src") and `sqlparse/sql.py`
    yields ("sqlparse", "").
    """
    roots = set()
    for _, relative in target.files:
        parts = relative.replace("\\", "/").split("/")
        if not parts[-1].endswith(".py"):
            continue
        # Climb while the directory above is still a package.
        i = len(parts) - 1
        while i > 0 and os.path.exists(
                os.path.join(target.root, *(parts[:i] + ["__init__.py"]))):
            i -= 1
        name = parts[i][:-3] if parts[i].endswith(".py") else parts[i]
        roots.add((name, "/".join(parts[:i])))
    return sorted(roots)


# Put into each scored file for one watching run. It leaves a hit file beside
# the module, named from its own `__file__`, so it needs nothing from the
# environment. A version that imported a helper off PYTHONPATH never fired in
# a subprocess the suite started with its own environment, and a version that
# embedded a path was long enough to fail a line-length check and named a
# missing directory when the path was not ASCII. builtins, because a module is
# free to shadow `open`; every failure is swallowed so the marker can never be
# the thing that breaks a run.
MARKER = ("try:\n"
          "    __import__('builtins').open(__file__ + '.qkhit', 'w').close()\n"
          "except Exception:\n"
          "    pass\n")
HIT = ".qkhit"

# A pytest plugin for the watching run, recording every file the suite's own
# process loaded. A marker firing says the copy ran; it cannot say the copy
# was the one the tests used. With a namespace package whose suite lives
# inside it, pytest's collection ran the copy's `__init__.py` and fired its
# marker, while the test imported `acme.widgets` from the user's original.
_WATCH_PLUGIN = (
    "import os, sys\n"
    "def pytest_sessionfinish(session, exitstatus):\n"
    "    out = os.environ.get('QIKLY_LOADED')\n"
    "    if not out:\n"
    "        return\n"
    "    with open(out, 'w', encoding='utf-8') as handle:\n"
    "        for module in list(sys.modules.values()):\n"
    "            name = getattr(module, '__file__', None)\n"
    "            if name:\n"
    "                handle.write(os.path.realpath(name) + '\\n')\n")


def _marker_line(source):
    """
    The 0-based line index the marker goes before, as early as Python allows.

    At the top rather than the end, because a script ending in
    `if __name__ == "__main__": sys.exit(main())` exits before an appended
    line runs, and was reported as never run while its faults were being
    caught. After the docstring, so `__doc__` survives; after any `from
    __future__` import, which must come first; and after a coding line, which
    only counts in the first two lines.
    """
    import ast

    lines = source.splitlines()
    at = 0
    try:
        body = ast.parse(source).body
    except (SyntaxError, ValueError):
        body = []
    i = 0
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        i = 1
    while (i < len(body) and isinstance(body[i], ast.ImportFrom)
           and body[i].module == "__future__"):
        i += 1
    if i:
        at = body[i - 1].end_lineno
        # `"""D."""; X = (1,` with the rest on later lines: the next
        # statement starts on the docstring's line and must be stepped over.
        while i < len(body) and body[i].lineno <= at:
            at = body[i].end_lineno
            i += 1
    while at < 2 and at < len(lines) and lines[at].lstrip().startswith("#"):
        at += 1
    return at


def _unreached(workspace, target, env=None):
    """
    The scored files the suite never executed, found by watching it once.

    Returns a list of paths relative to the workspace, or None when the
    watching run did not pass and so says nothing either way. The caller must
    treat None as "unknown", never as "everything ran": reading it as the
    latter turned the guard off for any suite a marker trips, such as one
    that checks line lengths, and the invented score came back.

    Probing a package by name is a guess about what the suite imports, and
    two layouts defeat it: a namespace package, where the probed name resolves
    in the workspace while the suite imports `acme.widgets` from an installed
    copy, and a suite living inside its own package. Observing beats guessing:
    a marker in each scored file writes a file when that module runs, and the
    suite is run once. The originals are copied back afterwards whatever
    happens.
    """
    marks = tempfile.mkdtemp()
    try:
        for _, relative in target.files:
            planted = os.path.join(workspace, relative)
            # Bytes, so a file in any declared encoding gets an ASCII line
            # inserted rather than a re-encoding of everything around it.
            try:
                with open(planted, "rb") as handle:
                    raw = handle.read()
            except OSError:
                # Nothing to watch means nothing confirmed, not a crash.
                return None
            # A byte-order mark stays first. ast.parse refuses a leading
            # U+FEFF, which put the marker in front of the mark, and Python
            # then refused the file.
            bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            raw = raw[len(bom):]
            at = _marker_line(raw.decode("utf-8", errors="replace"))
            chunks = raw.splitlines(keepends=True)
            if at and chunks and not chunks[min(at, len(chunks)) - 1].endswith(
                    (b"\n", b"\r")):
                chunks[min(at, len(chunks)) - 1] += b"\n"
            chunks.insert(at, MARKER.encode("ascii"))
            with open(planted, "wb") as handle:
                handle.write(bom + b"".join(chunks))
        with open(os.path.join(marks, "_qikly_watch.py"), "w",
                  encoding="utf-8") as handle:
            handle.write(_WATCH_PLUGIN)
        loaded_list = os.path.join(marks, "loaded.txt")
        # The marks directory holds only the plugin, so putting it first on
        # the path cannot shadow anything the suite imports.
        watching = dict(env if env is not None else os.environ)
        existing = watching.get("PYTHONPATH", "")
        watching["PYTHONPATH"] = os.pathsep.join(
            [marks] + ([existing] if existing else []))
        watching["QIKLY_LOADED"] = loaded_list
        if _suite_verdict(workspace, target, watching,
                          plugin="_qikly_watch") != "pass":
            return None
        try:
            with open(loaded_list, encoding="utf-8") as handle:
                loaded = set(handle.read().splitlines())
        except OSError:
            loaded = set()
        never = []
        n = os.path.normcase
        inside = n(os.path.realpath(workspace)) + os.sep
        # Indexed by file name once. Rescanning every loaded path for each
        # scored file took 51 seconds for 500 files against 50,000 modules.
        outside = {}
        for p in loaded:
            if not n(p).startswith(inside):
                outside.setdefault(n(os.path.basename(p)), []).append(p)
        for path, relative in target.files:
            hit = os.path.exists(os.path.join(workspace, relative) + HIT)
            same_name = outside.get(n(os.path.basename(path)), [])
            if not hit or _shadowed(path, same_name):
                never.append(relative)
        return never
    finally:
        for path, relative in target.files:
            planted = os.path.join(workspace, relative)
            shutil.copy2(path, planted)
            try:
                os.remove(planted + HIT)
            except OSError:
                pass
        shutil.rmtree(marks, ignore_errors=True)


def _shadowed(original, loaded_outside):
    """
    Whether the suite loaded this file from somewhere other than the copy.

    A marker firing says the copy ran; it cannot say the copy was the one the
    tests used. Two ways the original turns up instead: the user's own file,
    loaded in place, as an editable install or a path entry does; and a copy
    of it elsewhere on the path, as a plain `pip install .` leaves in
    site-packages. The second is found by content, since its path has nothing
    in common with the original's: a loaded file with the same name and the
    same bytes is the same module. Paths are compared case-insensitively where
    the filesystem is, because realpath does not normalise case on every
    volume.
    """
    n = os.path.normcase
    real = n(os.path.realpath(original))
    name = n(os.path.basename(original))
    same_name = [p for p in loaded_outside if n(os.path.basename(p)) == name]
    if not same_name:
        return False
    if any(n(p) == real for p in same_name):
        return True
    try:
        with open(original, "rb") as handle:
            mine = handle.read()
    except OSError:
        return False
    for p in same_name:
        try:
            with open(p, "rb") as handle:
                if handle.read() == mine:
                    return True
        except OSError:
            continue
    return False


class NeverRan(ValueError):
    """The suite passed without running the code being scored."""


def score(target, mutants=DEFAULT_MUTANTS, seed=None, code_root=CODE_ROOT):
    """
    Plant faults one at a time and report which the suite caught.

    Returns a dict, or None when there is nothing to score: no implementation,
    no suite, or an implementation with no mutation sites at all.

    When `from_paths` found the suite inside a package, the target is copied
    from above that package and carries the package's own directory as a
    fallback, tried only if the wider copy fails its baseline or never runs
    the code. Which of the two works depends on how the suite imports, and
    only running it shows that.
    """
    if isinstance(target, str):
        # Kept because a task id reads naturally at a call site and this was
        # the only signature for a release.
        target = from_task(target, code_root)
    fallback = getattr(target, "fallback", None)
    try:
        result = _score_once(target, mutants, seed, code_root)
    except ValueError:
        # NeverRan, or the wider copy tripping the file-count limit. Either
        # way the plain root is still worth trying, and if it fails too its
        # own error is the one the reader needs.
        if fallback is None:
            raise
        return _score_once(fallback, mutants, seed, code_root)
    if result is not None and not result["baseline"] and fallback is not None:
        wider = _score_once(fallback, mutants, seed, code_root)
        if wider is not None and wider["baseline"]:
            return wider
    return result


_GENERATED_IMPORT = re.compile(r"\boutputs\.agent_src\.code\.(\w+)\.")


def _generated_suite_task(target):
    """The task whose generated suite this is, or None for anyone else's."""
    for suite in target.suites:
        path = os.path.join(target.root, suite)
        names = ([path] if os.path.isfile(path) else
                 [os.path.join(d, f) for d, _, fs in os.walk(path)
                  for f in fs if f.endswith(".py")])
        for name in names:
            try:
                with open(name, encoding="utf-8", errors="replace") as handle:
                    found = _GENERATED_IMPORT.search(handle.read())
            except OSError:
                continue
            if found:
                return found.group(1)
    return None


def _score_once(target, mutants, seed, code_root):
    files = target.files
    if not target:
        return None

    candidates = []
    for path, relative in files:
        # utf-8-sig, matching scaffold.py, which carries the same comment
        # because this was learned once already. A byte-order mark is normal on
        # Windows: PowerShell 5.1's `Set-Content -Encoding utf8` writes one, as
        # did older Notepad. Read as plain utf-8 the mark survives as U+FEFF and
        # ast.parse rejects a file Python itself runs happily. Found four hours
        # after 0.5.4 shipped, by running the release walkthrough on Windows.
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            source = handle.read()
        for family, index, described in sites(source):
            candidates.append((path, relative, source, family, index, described))
    if not candidates:
        return None

    random.Random(seed).shuffle(candidates)
    candidates = candidates[:mutants]

    caught, missed, unscorable = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        workspace = _workspace(target, tmp, code_root)

        # The control. A suite that already fails on the untouched code cannot
        # say anything about a mutant, because every mutant would "fail" for
        # the reason the original does.
        for path, relative in files:
            shutil.copy2(path, os.path.join(workspace, relative))
        env = _suite_env(workspace, target)
        if not _suite_passes(workspace, target, env):
            return {"task": target.label, "baseline": False, "caught": [],
                    "missed": [], "unscorable": 0, "total": 0,
                    "generated": target.task_id is not None}

        # A green baseline is not enough on its own: a suite that imports an
        # installed copy also passes, and then reports every mutant missed.
        unreached = _unreached(workspace, target, env)
        unverified = unreached is None
        unreached = unreached or []
        if unreached and len(unreached) == len(files):
            generated = _generated_suite_task(target)
            if generated:
                # The obvious move after a run: score the new suite against
                # your own file. It imports qikly's copy instead, so the
                # general explanation below, an installed package, was wrong
                # for exactly the case a new user hits first.
                raise NeverRan(
                    "these tests are the suite qikly generated for %s, and "
                    "they import qikly's copy of your code under "
                    "outputs/agent_src/, not your file. Score them where "
                    "they run:\n  qikly --score-suite --tasks %s"
                    % (generated, generated))
            raise NeverRan(
                "the suite never ran the code being scored.\n"
                "  planting faults in: %s\n"
                "The suite passed, so it imported this code from somewhere "
                "else: usually an installed copy of the package, which a src/ "
                "layout, a namespace package or an editable install can all "
                "lead to. Every planted fault would run against untouched "
                "code and read as missed, which would be wrong rather than "
                "alarming. Score from an environment where the package is "
                "not installed."
                % ", ".join(sorted(unreached)[:5]))
        # Kept in the score, which stays a floor: a module no test imports
        # really is untested. Named, so its misses are not read as weak tests.
        never_ran = sorted(unreached)

        for path, relative, source, family, index, described in candidates:
            mutant, _ = make_mutant(source, index, family)
            if mutant is None:
                unscorable += 1
                continue
            planted = os.path.join(workspace, relative)
            with open(planted, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(mutant)
            verdict = _suite_verdict(workspace, target, env)
            if verdict == "error":
                # pytest could not run the suite at all, so nothing was
                # demonstrated about it. Counting this as caught would credit
                # the suite for a collection failure, which is the most
                # flattering possible misreading.
                unscorable += 1
            else:
                # `path` is kept so a missed fault can be turned into a
                # question that shows the line it was planted in.
                (missed if verdict == "pass" else caught).append(
                    {"file": os.path.basename(path), "family": family,
                     "change": described, "path": path})
            shutil.copy2(path, planted)

    if unverified and missed and not caught:
        # The one combination that looks exactly like the bug this guards
        # against: nothing confirmed the suite ran this code, and nothing it
        # planted was noticed. Printing that as 0% with a caveat still puts
        # an invented number in front of someone, so it is refused instead.
        raise NeverRan(
            "every planted fault was missed, and the check that the suite "
            "runs this code could not complete, usually because a test reads "
            "the source files themselves, such as a line-length or snapshot "
            "check. Together those look exactly like a suite importing an "
            "installed copy of the package, so no score is given. Score from "
            "an environment where the package is not installed, or with the "
            "source-reading tests left out of --score-tests.")

    return {"task": target.label, "baseline": True, "caught": caught,
            "missed": missed, "unscorable": unscorable,
            "total": len(caught) + len(missed),
            "generated": target.task_id is not None,
            "unreached": never_ran,
            "unverified": unverified}


def unreachable_criteria(task_id):
    """
    Criteria this task's data cannot trigger, or [] when it cannot be checked.

    Returns [] for a suite qikly did not write: there is no task file, so
    there are no criteria to be unreachable. That is a different thing from
    None, which means the check could not be run and the caveat is therefore
    unknown, and the report says so in both cases.

    The score is read beside this, never on its own: a suite cannot catch a
    fault in behaviour no input row exercises, so an unreachable criterion
    lowers the score for a reason that has nothing to do with the suite.
    """
    if task_id is None:
        return []
    try:
        import yaml

        from qikly.agent_api.agent_interface import task_config_path
        from qikly.fixture_reach import unreachable
        from qikly.validate import _readable_input

        with open(task_config_path(task_id), encoding="utf-8") as handle:
            task = yaml.safe_load(handle) or {}
        return unreachable(task, _readable_input)
    except Exception:
        # A score is still worth printing when the task file cannot be read;
        # the caveat is what is lost, and the report says when it is missing.
        return None


def headline(caught, total):
    """
    The score in one line, misses first: "3 of 12 planted faults missed (25%),
    9 caught".

    Misses first because they are the finding. "9 of 12 caught" reads as a
    pass mark, and the three it did not catch are the lines worth reading.
    One function, so the report and the console cannot say it differently.
    """
    missed = total - caught
    return (f"{missed} of {total} planted faults missed "
            f"({missed * 100 // total}%), {caught} caught")


def render(result, gaps):
    """The report, with what the number does not mean stated after the lists."""
    task = result["task"]
    lines = [f"# Suite score for {task}", "",
             f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
             f"No model calls, and nothing of yours was modified.", ""]

    if not result["baseline"]:
        # The console message was made mode-aware and this one was not, so the
        # file a user actually keeps and pastes into a pull request still told
        # them to converge a run they had never started.
        nothing_yet = ("Check that the path given to `--score-tests` holds "
                       "tests that run and pass on their own."
                       if result.get("generated") is False
                       else "Get the run to converge first.")
        lines += ["**Not scored.** The suite does not pass the untouched "
                  "implementation, so a mutant failing says nothing: it would "
                  "fail for the reason the original does. " + nothing_yet, ""]
        return "\n".join(lines) + "\n"

    if result.get("unverified"):
        # Above the score, not below it: this is the case where the number
        # may be invented, so it has to be read first.
        lines += ["**Could not confirm the suite ran the code being "
                  "scored.** The run that checks failed, which usually means "
                  "a test reads the source files themselves, such as a "
                  "line-length or snapshot check. If the score below is near "
                  "zero, make sure the suite is not importing an installed "
                  "copy of the package instead of this one.", ""]

    total = result["total"]
    caught = len(result["caught"])
    if total:
        # Both counts, each on its own line, so neither has to be worked out
        # from the other. The console keeps the one-line headline().
        missed = total - caught
        lines += [f"**{caught} of {total} planted faults caught "
                  f"({caught * 100 // total}%).**", "",
                  f"**{missed} of {total} planted faults missed "
                  f"({missed * 100 // total}%).**", ""]

    if gaps is None:
        lines += ["Reachability could not be checked for this task, so read "
                  "the score knowing that part of it may belong to the data "
                  "rather than to the suite.", ""]
    elif gaps:
        lines += [f"**Read the score with this first: {len(gaps)} "
                  f"{'criterion' if len(gaps) == 1 else 'criteria'} name a "
                  f"value your data never holds.** A suite cannot catch a "
                  f"fault in behaviour no input row exercises, so those "
                  f"criteria lower this number for a reason that is about "
                  f"your fixtures, not your tests. "
                  f"`qikly --propose-fixtures --tasks {task}` drafts the "
                  f"rows.", ""]
        for index, criterion, missing, fields in gaps:
            lines.append(f"- criterion {index} names {', '.join(missing[:3])} "
                         f"for {' or '.join(fields[:2])}: {criterion[:70]}")
        lines.append("")

    if result.get("unreached"):
        # A miss in a file the suite never ran says nothing about the tests'
        # assertions, and the two call for different work. Not "every fault
        # was missed" or "no tests at all": a file run only in a subprocess
        # can still have its faults caught, and a shadowed import is not the
        # same thing as an untested file.
        lines += [f"**{len(result['unreached'])} scored file(s) never ran "
                  f"during the suite** ({', '.join(result['unreached'][:5])}), "
                  f"so faults planted there cannot be caught: either nothing "
                  f"tests them, or the suite loaded them from somewhere else. "
                  f"Their misses are counted, so the score stays a floor.", ""]

    if result["missed"]:
        lines += ["## What it missed", "",
                  "Each line is a change to your code that the suite still "
                  "passed. Some are equivalent to the original and cannot be "
                  "caught by any test, which is why a miss is a question "
                  "rather than a verdict.", ""]
        for number, item in enumerate(result["missed"], 1):
            lines.append(f"{number}. `{item['file']}`: {item['change']} ({item['family']})")
        lines.append("")
        if result.get("questions"):
            from qikly import score_questions

            lines += score_questions.report_lines(
                result["questions"], len(result["missed"]),
                result.get("questions_advice") or [])

    if result["caught"]:
        lines += ["## What it caught", ""]
        for number, item in enumerate(result["caught"], 1):
            lines.append(f"{number}. `{item['file']}`: {item['change']} ({item['family']})")
        lines.append("")
    if total:
        # The sentence that stops the number being read as a grade. A suite
        # scored 8 of 8 here while a suite written from the specification found
        # four real bugs in the same file: mutation scoring asks whether your
        # tests notice changes to the code that exists, and nothing can plant a
        # fault in a rule nobody implemented. At the end, after the lists it
        # qualifies, so the counts are the first thing read.
        lines += ["## What the score cannot tell you", "",
                  "The score says how much of the code that **is** here your "
                  "tests would notice being changed. It cannot say anything "
                  "about a rule nobody implemented, because there is nothing "
                  "there to break, so a high score is not a clean bill of "
                  "health (read the result as a floor rather than a verdict).",
                  ""]
    lines += _invite_lines(result)
    return "\n".join(lines) + "\n"


def report_dir(target, invoked_from=None):
    """
    Where the report goes, which is not the same place for the two modes.

    A qikly task's report belongs in the project's `outputs/`, beside every
    other artefact of the run that produced it. A report about somebody else's
    code does not: this process has already moved to a resolved project root,
    which may be a clone of qikly on the other side of the disk, and writing
    there both loses the report and litters a tree the user never asked us to
    touch. That happened on the first run of this feature, into this
    repository's own `outputs/`.
    """
    if target.task_id is not None:
        return OUT_DIR
    return os.path.join(invoked_from or os.getcwd(), "qikly-suite-score")


def write(result, gaps, out_dir=OUT_DIR, invoked_from=None):
    """
    The report, with the questions in it, and beside it the same questions
    saved for `--scaffold` to put into a task file.

    Questions are asked only about a suite qikly did not write. A qikly task
    already has its criteria, and `--scaffold` will not rewrite it, so there
    they would lead nowhere.
    """
    os.makedirs(out_dir, exist_ok=True)
    # A task id is already a safe name; a label taken from a path is not, and
    # "src/pricing.py" in a filename is a directory that does not exist.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", result["task"]) or "suite"
    base = os.path.join(
        out_dir, f"{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    # Two reports of the same thing inside one second overwrote each other in
    # silence, which is the one outcome a report is supposed to prevent.
    path, suffix = base + ".md", 2
    while os.path.exists(path):
        path = f"{base}_{suffix}.md"
        suffix += 1
    scored = [item["path"] for item in result.get("caught", []) + result.get("missed", [])
              if item.get("path")]
    if result.get("generated") is False and scored:
        from qikly import score_questions

        questions = score_questions.build(result["missed"])
        # Saved where `--scaffold` looks, so the next command can put the
        # questions into the task file, which is where acceptance criteria
        # live. Saved even when there are none: a score that now catches
        # everything has to replace the older one that asked.
        asked = path[:-len(".md")] + score_questions.QUESTIONS_SUFFIX
        score_questions.save(questions, asked, result["task"], scored)
        if questions:
            result.update(questions=questions, questions_path=asked,
                          questions_advice=score_questions.advice(
                              questions, invoked_from))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(result, gaps))
    return path


def _invite_lines(result):
    """
    A short request at the end of the report, made only when the user has
    just learned something they did not know.

    The Skill is built to make qikly invisible: it installs into an agent
    somebody already uses, so a user whose agent quietly scored their suite
    has no reason to think about this project at all. A fault their own tests
    did not notice is the exception, and the most useful thing anyone outside
    this project can send: the generated suites are measured against what
    real suites miss, and there is no other source for that.

    In the report, not the terminal. Printed after the next-step advice, it
    competed with it, and a first-time user read it, in two wordings, as part
    of their result. In the report it sits right below the misses it asks
    about. Silent when nothing was missed, because a request after good news
    is an advertisement. Silent for a suite qikly wrote, because there the
    misses are qikly's own, not evidence of what real suites miss (found by
    audit before 0.5.7).
    """
    result = result or {}
    if not result.get("missed") or result.get("generated") is not False:
        return []
    return ["## Optional: tell me what this found", "",
            "If a miss above surprised you, a one-line note about it at "
            "https://github.com/gal-a/qikly/discussions helps me make "
            "qikly's own tests better, for example \"nothing checked "
            "rate = 100\". Please don't post your code.", ""]


def run(target, mutants=DEFAULT_MUTANTS, seed=None, invoked_from=None):
    """The command's body: score, report, and say what the number is worth."""
    if isinstance(target, str):
        target = from_task(target)
    task_id = target.label

    result = score(target, mutants=mutants, seed=seed)
    if result is None:
        if target.task_id is None:
            print(f"[{task_id}] nothing to score: no Python files to mutate, "
                  f"or no tests at the path given.")
        else:
            print(f"[{task_id}] nothing to score: this needs an implementation "
                  f"and a generated suite from a run that converged.")
        return None

    gaps = unreachable_criteria(target.task_id)
    path = write(result, gaps, report_dir(target, invoked_from), invoked_from)

    if not result["baseline"]:
        if target.task_id is None:
            # No run exists in this mode, so "get the run to converge" is
            # advice about something the user does not have. The usual cause
            # is that pytest collected nothing at all.
            print(f"[{task_id}] your suite does not pass your untouched code, "
                  f"so planting a fault would prove nothing: every mutant "
                  f"would fail for the reason the original does. Check that "
                  f"--score-tests points at tests that run and pass. Report "
                  f"at {path}")
        else:
            print(f"[{task_id}] the suite does not pass your current code, so a "
                  f"score would mean nothing. Report at {path}")
        return path

    total, caught = result["total"], len(result["caught"])
    print(f"[{task_id}] {headline(caught, total)}." if total
          else f"[{task_id}] no faults planted.")
    if total and len(target.files) > 1:
        # The cap is per run, not per file, and a folder looked as if each
        # file had been given the same scrutiny as a single module.
        print(f"[{task_id}] those {total} were spread at random over "
              f"{len(target.files)} files, so a larger folder gets fewer per "
              f"file. Plant more with --score-mutants, such as "
              f"--score-mutants {total * 4}, or score one module.")
    if gaps is None:
        print(f"[{task_id}] reachability could not be checked, so part of that "
              f"number may belong to your data rather than to your suite.")
    elif gaps:
        print(f"[{task_id}] read that beside {len(gaps)} criteria your data "
              f"never triggers: a suite cannot catch what no row exercises. "
              f"Run --propose-fixtures --tasks {task_id} first.")
    print(f"[{task_id}] what it missed, one line each: {path}")
    if result.get("questions_path"):
        # The step people stopped at was the blank task file. This is the
        # moment they know what their tests leave open, so the way from here
        # to a suite is printed in full rather than left to the docs.
        count = len(result["questions"])
        print(f"[{task_id}] {count} question{'' if count == 1 else 's'} your "
              f"tests leave open, in the same report.")
        for line in result["questions_advice"]:
            print(f"[{task_id}] {line}")
    return path
