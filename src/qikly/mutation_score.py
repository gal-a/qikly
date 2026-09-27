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
    return [(os.path.join(directory, name), os.path.join(CODE_ROOT, task_id, name))
            for name in sorted(os.listdir(directory))
            if name.endswith(".py") and not name.startswith("__")]


def suite_dirs(task_id, root=TEST_ROOT):
    """The stage directories of the current suite."""
    return [os.path.join(root, task_id, stage) for stage in STAGES
            if os.path.isdir(os.path.join(root, task_id, stage))]


def sites(source):
    """[(family, index, description)] for every fault this can plant."""
    out = []
    for family in FAMILIES:
        for index in range(count_sites(source, family)):
            mutant, described = make_mutant(source, index, family)
            if mutant is not None and mutant != source:
                out.append((family, index, described))
    return out


def _workspace(task_id, tmp, code_root=CODE_ROOT):
    """A copy of the project a suite can run against, minus the implementation."""
    workspace = os.path.join(tmp, "ws")
    for relative in ("inputs_private", "inputs_public", "outputs"):
        if os.path.isdir(relative):
            shutil.copytree(relative, os.path.join(workspace, relative),
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "old"))
    os.makedirs(os.path.join(workspace, code_root, task_id), exist_ok=True)
    return workspace


def _suite_passes(workspace, task_id):
    """True only when every stage of the suite passes in this workspace."""
    return _suite_verdict(workspace, task_id) == "pass"


def _suite_verdict(workspace, task_id):
    """
    "pass", "fail" or "error" for the suite in this workspace.

    Three outcomes rather than two, because pytest's return codes are not one
    thing: 0 passed, 1 tests failed, and 2 or more means it could not run the
    suite at all, usually a collection error. Reading anything non-zero as
    "the suite noticed" credits a mutant that broke collection as a fault
    caught, when no assertion ever ran.
    """
    for directory in suite_dirs(task_id):
        target = os.path.join(workspace, directory)
        if not os.path.isdir(target):
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q", "--tb=no",
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


def score(task_id, mutants=DEFAULT_MUTANTS, seed=None, code_root=CODE_ROOT):
    """
    Plant faults one at a time and report which the suite caught.

    Returns a dict, or None when there is nothing to score: no implementation,
    no suite, or an implementation with no mutation sites at all.
    """
    files = implementation(task_id, code_root)
    if not files or not suite_dirs(task_id):
        return None

    candidates = []
    for path, relative in files:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for family, index, described in sites(source):
            candidates.append((path, relative, source, family, index, described))
    if not candidates:
        return None

    random.Random(seed).shuffle(candidates)
    candidates = candidates[:mutants]

    caught, missed, unscorable = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        workspace = _workspace(task_id, tmp, code_root)

        # The control. A suite that already fails on the untouched code cannot
        # say anything about a mutant, because every mutant would "fail" for
        # the reason the original does.
        for path, relative in files:
            shutil.copy2(path, os.path.join(workspace, relative))
        if not _suite_passes(workspace, task_id):
            return {"task": task_id, "baseline": False, "caught": [],
                    "missed": [], "unscorable": 0, "total": 0}

        for path, relative, source, family, index, described in candidates:
            mutant, _ = make_mutant(source, index, family)
            if mutant is None:
                unscorable += 1
                continue
            target = os.path.join(workspace, relative)
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(mutant)
            verdict = _suite_verdict(workspace, task_id)
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
            shutil.copy2(path, target)

    return {"task": task_id, "baseline": True, "caught": caught,
            "missed": missed, "unscorable": unscorable,
            "total": len(caught) + len(missed)}


def unreachable_criteria(task_id):
    """
    Criteria this task's data cannot trigger, or [] when it cannot be checked.

    The score is read beside this, never on its own: a suite cannot catch a
    fault in behaviour no input row exercises, so an unreachable criterion
    lowers the score for a reason that has nothing to do with the suite.
    """
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
        lines += ["**Not scored.** The suite does not pass the untouched "
                  "implementation, so a mutant failing says nothing: it would "
                  "fail for the reason the original does. Get the run to "
                  "converge first.", ""]
        return "\n".join(lines) + "\n"

    total = result["total"]
    caught = len(result["caught"])
    if total:
        lines += [f"**{caught} of {total} planted faults caught "
                  f"({caught * 100 // total}%).**", ""]

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


def write(result, gaps, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"{result['task']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(result, gaps))
    return path


def run(task_id, mutants=DEFAULT_MUTANTS, seed=None):
    """The command's body: score, report, and say what the number is worth."""
    result = score(task_id, mutants=mutants, seed=seed)
    if result is None:
        print(f"[{task_id}] nothing to score: this needs an implementation and "
              f"a generated suite from a run that converged.")
        return None

    gaps = unreachable_criteria(task_id)
    path = write(result, gaps)

    if not result["baseline"]:
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
