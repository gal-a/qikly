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
            raise ValueError(f"no {what} at {path}")

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

    if os.path.isfile(code):
        sources = [code]
    else:
        sources = []
        for base, dirs, names in os.walk(code):
            # In place, so os.walk does not descend into them.
            dirs[:] = [d for d in dirs if d not in _SKIP]
            for name in names:
                if name.endswith(".py") and not name.startswith("__"):
                    sources.append(os.path.join(base, name))
        sources.sort()

    if not sources:
        raise ValueError(f"no Python files to mutate under {code}")

    return Target(label=os.path.basename(code.rstrip(os.sep)) or code,
                  files=[(s, os.path.relpath(s, root)) for s in sources],
                  suites=[os.path.relpath(tests, root)],
                  root=root,
                  task_id=None)


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


def _suite_passes(workspace, target):
    """True only when every stage of the suite passes in this workspace."""
    return _suite_verdict(workspace, target) == "pass"


def _suite_verdict(workspace, target):
    """
    "pass", "fail" or "error" for the suite in this workspace.

    Three outcomes rather than two, because pytest's return codes are not one
    thing: 0 passed, 1 tests failed, and 2 or more means it could not run the
    suite at all, usually a collection error. Reading anything non-zero as
    "the suite noticed" credits a mutant that broke collection as a fault
    caught, when no assertion ever ran.
    """
    for directory in target.suites:
        where = os.path.join(workspace, directory)
        if not os.path.exists(where):
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", where, "-q", "--tb=no",
             # The project's own addopts already carry -q, and -qq suppresses
             # the count line entirely, so every parsed count reads as zero,
             # which looks exactly like a suite that ran and passed.
             "-o", "addopts=", "-p", "no:cacheprovider"],
            cwd=workspace, capture_output=True, text=True)
        if result.returncode >= 2:
            return "error"
        if result.returncode != 0:
            return "fail"
    return "pass"


def score(target, mutants=DEFAULT_MUTANTS, seed=None, code_root=CODE_ROOT):
    """
    Plant faults one at a time and report which the suite caught.

    Returns a dict, or None when there is nothing to score: no implementation,
    no suite, or an implementation with no mutation sites at all.
    """
    if isinstance(target, str):
        # Kept because a task id reads naturally at a call site and this was
        # the only signature for a release.
        target = from_task(target, code_root)
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
        if not _suite_passes(workspace, target):
            return {"task": target.label, "baseline": False, "caught": [],
                    "missed": [], "unscorable": 0, "total": 0,
                    "generated": target.task_id is not None}

        for path, relative, source, family, index, described in candidates:
            mutant, _ = make_mutant(source, index, family)
            if mutant is None:
                unscorable += 1
                continue
            planted = os.path.join(workspace, relative)
            with open(planted, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(mutant)
            verdict = _suite_verdict(workspace, target)
            if verdict == "error":
                # pytest could not run the suite at all, so nothing was
                # demonstrated about it. Counting this as caught would credit
                # the suite for a collection failure, which is the most
                # flattering possible misreading.
                unscorable += 1
            else:
                (missed if verdict == "pass" else caught).append(
                    {"file": os.path.basename(path), "family": family,
                     "change": described})
            shutil.copy2(path, planted)

    return {"task": target.label, "baseline": True, "caught": caught,
            "missed": missed, "unscorable": unscorable,
            "total": len(caught) + len(missed),
            "generated": target.task_id is not None}


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


def render(result, gaps):
    """The report, with what the number does not mean stated above it."""
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

    total = result["total"]
    caught = len(result["caught"])
    if total:
        lines += [f"**{caught} of {total} planted faults caught "
                  f"({caught * 100 // total}%).**", ""]
        # The sentence that stops the number being read as a grade. A suite
        # scored 8 of 8 here while a suite written from the specification found
        # four real bugs in the same file: mutation scoring asks whether your
        # tests notice changes to the code that exists, and nothing can plant a
        # fault in a rule nobody implemented.
        lines += ["Read that as a floor rather than a verdict. It says how much "
                  "of the code that **is** here your tests would notice being "
                  "changed. It cannot say anything about a rule nobody "
                  "implemented, because there is nothing there to break, so a "
                  "high score is not a clean bill of health.", ""]

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

    if result["missed"]:
        lines += ["## What it missed", "",
                  "Each line is a change to your code that the suite still "
                  "passed. Some are equivalent to the original and cannot be "
                  "caught by any test, which is why a miss is a question "
                  "rather than a verdict.", ""]
        for item in result["missed"]:
            lines.append(f"- `{item['file']}`: {item['change']} ({item['family']})")
        lines.append("")

    if result["caught"]:
        lines += ["## What it caught", ""]
        for item in result["caught"]:
            lines.append(f"- `{item['file']}`: {item['change']} ({item['family']})")
        lines.append("")
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


def write(result, gaps, out_dir=OUT_DIR):
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
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(result, gaps))
    return path


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
    path = write(result, gaps, report_dir(target, invoked_from))

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
    percent = f"{caught * 100 // total}%" if total else "no faults planted"
    print(f"[{task_id}] {caught} of {total} planted faults caught ({percent}).")
    if gaps is None:
        print(f"[{task_id}] reachability could not be checked, so part of that "
              f"number may belong to your data rather than to your suite.")
    elif gaps:
        print(f"[{task_id}] read that beside {len(gaps)} criteria your data "
              f"never triggers: a suite cannot catch what no row exercises. "
              f"Run --propose-fixtures --tasks {task_id} first.")
    print(f"[{task_id}] what it missed, one line each: {path}")
    return path
