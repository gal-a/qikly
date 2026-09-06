"""
Checking a task file without calling anything.

This exists because a pre-commit hook has to be free and fast. `--check-criteria`
already looks for contradictions between the requirements and the criteria, but
it costs a model call per task, and a hook that bills you on every commit is a
hook people uninstall on the second day.

So this is the offline half: everything about a task file that can be known
from the file itself. It catches the errors that otherwise surface twenty
minutes and several dollars into a run, which is the worst possible moment to
learn that a task_id was misspelled.

## What it checks, and why each one has cost someone a run

**It parses.** A YAML error is found now rather than at the first prompt.

**The required sections are present.** A missing `interface` produces tests that
reference functions nobody agreed on.

**`acceptance_criteria` is a list of non-empty strings.** A single string
instead of a list silently becomes a bar of one criterion made of every rule
run together, which then generates one enormous test.

**Every input file exists.** A fixture path that does not resolve fails at the
first test run, after the suites have already been generated and paid for.

**The criteria name boundary values.** Advisory, not an error. A criterion
phrased "reject large amounts" produces a test at some arbitrary large number;
"100 is accepted and 101 is rejected" forces the boundary. This is the single
highest-leverage habit in writing a bar, and it is invisible until you measure
what the suite misses.
"""
import os
import re

import yaml

REQUIRED = ("task_id", "requirements", "interface")

# A criterion carrying a number, a quoted literal or a comparison is naming
# something checkable. One made only of adjectives is not.
_CONCRETE = re.compile(r"\d|\"[^\"]+\"|'[^']+'|>=|<=|==|\bexactly\b|\bempty\b",
                       re.IGNORECASE)

# Words that describe a bar without setting one.
_VAGUE = ("appropriate", "reasonable", "sensible", "properly", "correctly",
          "gracefully", "as needed", "if necessary", "valid data", "large",
          "small", "quickly", "efficiently")


def _input_exists(relative):
    """
    Whether a task's declared input can be found, the way a run finds it.

    Declared paths carry the private prefix, e.g.
    "inputs_private/data/CALC_TAX/input_01.csv", and a bundled task's fixtures
    live inside the package until a run copies them out. Checking only the
    literal path therefore reported every shipped task as broken on a fresh
    install: twenty errors, all false, from the command recommended as a
    pre-commit hook.
    """
    from qikly.paths import DEFAULT_PRIVATE_DIR, resolve_input

    if os.path.isfile(relative):
        return True
    parts = relative.replace("\\", "/").split("/")
    if parts and parts[0] in (DEFAULT_PRIVATE_DIR, "inputs_public"):
        return os.path.isfile(resolve_input("/".join(parts[1:])))
    return False


def check_task(path):
    """
    Returns (errors, warnings) for one task file. Errors mean a run cannot
    work; warnings mean it will work and probably measure less than you think.
    """
    errors, warnings = [], []
    name = os.path.basename(path)

    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        task = yaml.safe_load(raw)
    except OSError as exc:
        return [f"{name}: cannot be read: {exc}"], []
    except yaml.YAMLError as exc:
        first = str(exc).split("\n")[0]
        return [f"{name}: is not valid YAML: {first}"], []

    if not isinstance(task, dict):
        return [f"{name}: should be a mapping, not {type(task).__name__}"], []

    for field in REQUIRED:
        if not task.get(field):
            errors.append(f"{name}: no {field}")

    declared = task.get("task_id")
    stem = os.path.splitext(name)[0]
    if declared and declared != stem:
        # Discovery uses the filename and the config carries the id. When they
        # disagree, --tasks names one thing and the run reports another.
        errors.append(f"{name}: task_id is {declared!r} but the file is {stem!r}")

    criteria = task.get("acceptance_criteria")
    if criteria is None:
        warnings.append(f"{name}: no acceptance_criteria, so a run has no bar "
                        f"to hold the code to. Add some, import them with "
                        f"--criteria-from, or draft them with --generate-criteria")
    elif isinstance(criteria, str):
        errors.append(f"{name}: acceptance_criteria is a single string. It has to "
                      f"be a list, or the whole bar becomes one criterion")
    elif not isinstance(criteria, list):
        errors.append(f"{name}: acceptance_criteria should be a list")
    else:
        for i, item in enumerate(criteria, start=1):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{name}: criterion {i} is empty")
                continue
            if not _CONCRETE.search(item):
                hit = next((w for w in _VAGUE if w in item.lower()), None)
                if hit:
                    warnings.append(
                        f"{name}: criterion {i} says {hit!r} without naming a "
                        f"value. A suite tests the boundary when the criterion "
                        f"names the boundary")

    for relative in (task.get("inputs") or []):
        if not _input_exists(relative):
            errors.append(f"{name}: input file not found: {relative}")

    return errors, warnings


def check_all(task_ids=None):
    """Every discoverable task, or the named ones."""
    from qikly.agent_api.agent_interface import task_config_path
    from qikly.orchestrator.orchestrator import discover_task_ids

    results = {}
    for task_id in (task_ids or discover_task_ids()):
        try:
            path = task_config_path(task_id)
        except Exception as exc:
            results[task_id] = ([f"{task_id}: no task file found: {exc}"], [])
            continue
        results[task_id] = check_task(path)
    return results


def render(results):
    lines, errors, warnings = [], 0, 0
    for task_id in sorted(results):
        problems, notes = results[task_id]
        errors += len(problems)
        warnings += len(notes)
        if not problems and not notes:
            lines.append(f"  ok      {task_id}")
        for item in problems:
            lines.append(f"  ERROR   {item}")
        for item in notes:
            lines.append(f"  warn    {item}")
    lines.append("")
    lines.append(f"{len(results)} task(s): {errors} error(s), {warnings} warning(s). "
                 f"Nothing was called and nothing was spent.")
    return "\n".join(lines), errors
