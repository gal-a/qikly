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

**No scaffold placeholder is left.** Advisory. A file with `TODO` still in its
requirements or criteria passes every other check, and a run would hand the
placeholder to the agents as the specification.

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


class Note(str):
    """
    A warning that remembers what it is about.

    `render` collapses the same finding repeated across many tasks, and to do
    that it has to know which warnings are the same finding. Parsing that back
    out of the rendered message would mean writing a regex against our own
    prose. A str subclass carries the key instead, and stays a str for every
    caller that only counts warnings or greps one for a substring.
    """
    def __new__(cls, text, group=None):
        note = super().__new__(cls, text)
        note.group = group
        return note

# A criterion carrying a number, a quoted literal or a comparison is naming
# something checkable. One made only of adjectives is not.
_CONCRETE = re.compile(r"\d|\"[^\"]+\"|'[^']+'|>=|<=|==|\bexactly\b|\bempty\b",
                       re.IGNORECASE)

# Words that describe a bar without setting one.
_VAGUE = ("appropriate", "reasonable", "sensible", "properly", "correctly",
          "gracefully", "as needed", "if necessary", "valid data", "large",
          "small", "quickly", "efficiently")

# What a scaffold writes where only the author can fill in, matched by its own
# shape (`TODO:` and `TODO one line summary`) so a requirement that merely
# mentions TODO comments is not flagged. A file still carrying
# one passes every other check here, and a run would send the placeholder to the
# agents as the specification.
_TODO = re.compile(r"\bTODO(?::|\s+one line summary)")


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

    leftover = [field for field in ("task_name", "description", "interface",
                                    "requirements", "acceptance_criteria")
                if task.get(field) is not None and _TODO.search(str(task.get(field)))]
    if leftover:
        warnings.append(
            f"{name}: still has TODO placeholders in {', '.join(leftover)}. A run "
            f"sends them to the agents as written, so replace them first")

    for relative in (task.get("inputs") or []):
        if not _input_exists(relative):
            errors.append(f"{name}: input file not found: {relative}")

    # A requirement that restates a criterion hands that criterion to the
    # coding agent, which reads requirements and must never read criteria. It
    # is the easiest leak in the whole system to create by accident: paste a
    # paragraph from the feature page into requirements and the page usually
    # restates its own criteria just above them. A warning rather than an
    # error, because the overlap measure is blunt and a false positive must
    # not stop a run, but it is worth saying loudly every time.
    from qikly.from_doc import restated
    for req, crit, score in restated(task.get("requirements"),
                                     task.get("acceptance_criteria")):
        warnings.append(Note(
            f"{name}: a requirement restates a criterion ({int(score * 100)}% "
            f"of its words). The coding agent reads requirements and never "
            f"reads criteria, so this hands it the answer key. "
            f"requirement: {req[:60]!r} criterion: {crit[:60]!r}",
            group=("restated", crit)))

    # The same question asked of everything else the coding agent reads.
    #
    # `requirements` is the field people paste into, so it gets its own check
    # above. But the handover is the whole file minus the criteria block, and a
    # comment is prose nobody reviews as input: it reads as a note to the next
    # maintainer while going to the agent word for word. ADAS_HEADWAY's header
    # comment explained that a certain boundary was settled only in the
    # criteria, and then said which way it was settled.
    for line, crit, score in _restated_outside_requirements(raw, task):
        warnings.append(Note(
            f"{name}: a comment or description restates a criterion "
            f"({int(score * 100)}% of its words). Everything in this file "
            f"except the acceptance_criteria block goes to the coding agent, "
            f"comments included, so a note explaining the answer is the "
            f"answer. line: {line[:60]!r} criterion: {crit[:60]!r}",
            group=("restated-comment", crit)))

    return errors, warnings


def _restated_outside_requirements(raw, task, threshold=0.6):
    """
    Lines the coding agent reads, other than `requirements`, that restate a
    criterion. Returns (line, criterion, score) triples.
    """
    from qikly.agent_api.agent_interface import without_acceptance_criteria
    from qikly.from_doc import common_vocabulary, overlap

    criteria = [c for c in (task.get("acceptance_criteria") or [])
                if isinstance(c, str)]
    if not criteria:
        return []

    requirement_text = {str(r).strip() for r in (task.get("requirements") or [])}
    handed_over = without_acceptance_criteria(raw)

    lines = []
    for line in handed_over.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        elif stripped.startswith("- "):
            stripped = stripped[2:].strip().strip('"')
        # Short lines carry no signal, and a line that IS a requirement is the
        # other check's business: reporting it twice trains people to skim both.
        if len(stripped) < 30 or stripped in requirement_text:
            continue
        if any(stripped in req for req in requirement_text):
            continue
        lines.append(stripped)

    common = common_vocabulary(criteria)
    found = []
    for line in lines:
        for crit in criteria:
            score = overlap(line, crit, common=common)
            if score >= threshold:
                found.append((line, crit, round(score, 2)))
    return found


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


# One finding repeated across this many tasks is a fact about the task set, not
# about any one file. Printing it once per file buries the findings that are.
_COLLAPSE_AT = 3


def _repeated(results):
    """Which warning groups appear across enough tasks to print once."""
    tasks = {}
    for task_id in results:
        for note in results[task_id][1]:
            group = getattr(note, "group", None)
            if group is not None:
                tasks.setdefault(group, set()).add(task_id)
    return {g: sorted(t) for g, t in tasks.items() if len(t) >= _COLLAPSE_AT}


def render(results):
    lines, errors, warnings = [], 0, 0
    repeated = _repeated(results)
    collapsed, shown = 0, set()
    for task_id in sorted(results):
        problems, notes = results[task_id]
        errors += len(problems)
        warnings += len(notes)
        if not problems and not notes:
            lines.append(f"  ok      {task_id}")
        for item in problems:
            lines.append(f"  ERROR   {item}")
        for item in notes:
            group = getattr(item, "group", None)
            if group in repeated:
                collapsed += 1
                if group in shown:
                    continue
                shown.add(group)
                where = ", ".join(repeated[group])
                # Drop the leading "<file>: ", the one part that is not shared.
                body = str(item).split(": ", 1)[-1]
                lines.append(f"  warn    {len(repeated[group])} tasks: {body}")
                lines.append(f"          in: {where}")
                continue
            lines.append(f"  warn    {item}")
    lines.append("")
    summary = f"{len(results)} task(s): {errors} error(s), {warnings} warning(s)"
    if collapsed:
        summary += (f", of which {collapsed} were {len(repeated)} finding(s) "
                    f"repeated across tasks and are shown once each")
    summary += ". No model was called and nothing was spent."
    lines.append(summary)
    return "\n".join(lines), errors
