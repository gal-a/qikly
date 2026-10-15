"""
Tests you can take home: the suite a run wrote, copied into your own tests
folder and rewritten to import your own module.

A run never touches your code. It copies it to
`outputs/agent_src/code/<TASK>/` and tests that copy, so every generated test
begins `from outputs.agent_src.code.<TASK>.pricing import ...`. Copied into a
repository as they are, those tests would go on testing qikly's copy, not
your file, which is the opposite of what anyone copying them wants.

So this copies each stage's tests to `<your tests folder>/qikly_generated/`,
named `test_<task>_<stage>.py` so they cannot clash with each other or with
yours, replaces qikly's import path with the one your own tests already use,
and runs them against your untouched code. A test that fails there marks a
place where your code and your answers disagree; the run fixed its copy, and
the fix is in `outputs/logs/patches/`.

A file this did not write is never overwritten: each copy starts with a
marker line, and only a file carrying it is replaced.
"""
import os
import re
import subprocess
import sys

import yaml

STAGES = ("integration", "system", "unit")
MARKER = "# Written by qikly from your answers"
FOLDER = "qikly_generated"


_CONFTEST = '''"""
Written by qikly. Keeps a plain `pytest` from the project root out of this
folder: the tests here are qikly's working copies, already copied to your own
tests by `qikly --take-tests`, and collecting both ran every test twice.
Naming a path inside outputs/ still runs it, which is how qikly runs them.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def pytest_ignore_collect(collection_path, config):
    base = str(config.invocation_params.dir)
    asked = [os.path.abspath(os.path.join(base, str(a).split("::")[0]))
             for a in config.args]
    if any(a == HERE or a.startswith(HERE + os.sep) for a in asked):
        return None
    return True
'''


def keep_outputs_out_of_pytest(cwd):
    """Write outputs/conftest.py unless one is there already."""
    folder = os.path.join(cwd, "outputs")
    path = os.path.join(folder, "conftest.py")
    if os.path.exists(path):
        return False
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_CONFTEST)
    return True


def _read(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def task_config(cwd, task_id):
    path = os.path.join(cwd, "inputs_private", "config", "tasks", task_id + ".yaml")
    try:
        return yaml.safe_load(_read(path)) or {}
    except yaml.YAMLError:
        return {}


def own_import(cwd, task, test_dir):
    """
    (qikly's import path, the user's), or None when the task tests no code
    of the user's.

    A package seed is already imported by its own dotted name, so only a
    single-file seed needs a new name: the one the user's tests use for that
    module, or, failing that, its plain file name.
    """
    module = str((task.get("interface") or {}).get("module") or "")
    implementation = str((task.get("seed") or {}).get("implementation") or "")
    if not module or not implementation:
        return None
    prefix = "outputs.agent_src.code.%s." % task.get("task_id", "")
    if not module.startswith(prefix):
        return None, None
    stem = os.path.splitext(os.path.basename(implementation))[0]
    for here, dirs, names in os.walk(test_dir):
        dirs[:] = [d for d in dirs if d != FOLDER and not d.startswith(".")]
        for name in names:
            if not name.endswith(".py"):
                continue
            found = re.search(r"^\s*(?:from\s+([\w.]*\b%s)\s+import|import\s+([\w.]*\b%s)\b)"
                              % (re.escape(stem), re.escape(stem)),
                              _read(os.path.join(here, name)), re.M)
            if found:
                return module, found.group(1) or found.group(2)
    return module, stem


def take(cwd, task_id, test_dir, say=print):
    """
    Copy a run's tests home. Returns (written paths, pytest result line), or
    (None, reason) when there is nothing to copy.
    """
    task = task_config(cwd, task_id)
    if not task:
        return None, f"there is no task {task_id} under inputs_private/config/tasks"
    names = own_import(cwd, task, test_dir)
    if names is None:
        return None, (f"{task_id} does not test code of yours: it has no "
                      f"`seed: implementation`")
    theirs, ours = names
    source_root = os.path.join(cwd, "outputs", "tests", task_id)
    if not os.path.isdir(source_root):
        return None, (f"{task_id} has no generated tests yet: run it first, "
                      f"with  qikly --start  or  qikly --tasks {task_id}")
    dest = os.path.join(test_dir, FOLDER)
    os.makedirs(dest, exist_ok=True)
    keep_outputs_out_of_pytest(cwd)
    written, skipped = [], []
    for stage in STAGES:
        folder = os.path.join(source_root, stage)
        files = sorted(f for f in os.listdir(folder) if f.endswith(".py")) \
            if os.path.isdir(folder) else []
        for index, name in enumerate(files):
            text = _read(os.path.join(folder, name))
            if theirs and ours:
                text = text.replace(theirs, ours)
            suffix = "" if index == 0 else "_%d" % (index + 1)
            target = os.path.join(dest, "test_%s_%s%s.py"
                                  % (task_id.lower(), stage, suffix))
            if os.path.exists(target) and not _read(target).startswith(MARKER):
                skipped.append(target)
                continue
            header = (f"{MARKER}, task {task_id}, {stage} stage.\n"
                      f"# Copied from outputs/tests/{task_id}/{stage}/{name}"
                      + (f", with `{theirs}` rewritten to `{ours}`" if theirs else "")
                      + ".\n# Run qikly --take-tests again to refresh it; edits "
                        "here are overwritten.\n\n")
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(header + text)
            written.append(target)
    for path in skipped:
        say(f"  left alone, because qikly did not write it: {path}")
    result = _run(cwd, written) if written else None
    return written, result


def _run(cwd, paths):
    """The copied tests on the user's own code: one summary line."""
    try:
        # A wide terminal, or pytest cuts each summary line to the width and
        # the error type that tells the two kinds of failure apart is lost.
        env = dict(os.environ, COLUMNS="1000")
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rfE",
                               "-p", "no:cacheprovider"] + paths,
                              cwd=cwd, capture_output=True, text=True, env=env,
                              timeout=600, encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return "the copied tests could not be run"
    lines = [l for l in done.stdout.splitlines() if l.strip()]
    summary = next((l for l in reversed(lines)
                    if re.search(r"\b(passed|failed|error)", l)), "")
    # Two kinds of failure, and only one is a disagreement. A test that calls
    # something your code does not have, such as a helper qikly's coding
    # agent added while fixing its copy, fails for that reason alone.
    disagree, missing = [], []
    for l in lines:
        if not l.startswith(("FAILED ", "ERROR ")):
            continue
        name, _, why = l.split(" ", 1)[1].partition(" - ")
        if re.match(r"(ImportError|ModuleNotFoundError|AttributeError|NameError)", why):
            missing.append(name)
        else:
            disagree.append(name)
    return summary.strip("= ").strip(), disagree, missing


def report(say, cwd, written, result, task_id):
    say(f"Copied {len(written)} test file{'' if len(written) == 1 else 's'} into "
        f"your tests, importing your own code:")
    for path in written:
        say(f"  {os.path.relpath(path, cwd)}")
    if not result:
        return
    if isinstance(result, str):
        say(f"Run on your own code: {result}.")
        return
    summary, disagree, missing = result
    say(f"Run on your own code: {summary or 'no result'}.")
    if disagree:
        say("These fail because your code disagrees with your answers. qikly "
            "fixed its copy; apply the same fix to yours, from "
            + os.path.join("outputs", "logs", "patches", task_id) + os.sep
            + ", and they pass:")
        for name in disagree:
            say(f"  {name}")
    if missing:
        say("These call something your code does not have, usually a helper "
            "qikly's coding agent added to its copy while fixing it. Take the "
            "helper from the same patch, or delete these tests:")
        for name in missing:
            say(f"  {name}")
    say("Some read the example data by a path relative to this folder, so run "
        "pytest from here.")


def main(task_id, cwd, test_dir=None):
    """`qikly --take-tests TASK`."""
    task_dir = test_dir or os.path.join(cwd, "tests")
    if not os.path.isdir(task_dir):
        os.makedirs(task_dir, exist_ok=True)
    written, result = take(cwd, task_id, task_dir)
    if written is None:
        print(f"Nothing copied: {result}.")
        return 2
    if not written:
        print("Nothing copied: every target file is one qikly did not write.")
        return 2
    report(print, cwd, written, result, task_id)
    return 0
