"""
Tests you can take home: the suite a run wrote, copied into your own tests
folder and rewritten to import your own module.

A run never touches your code. It copies it to
`outputs/agent_src/code/<TASK>/` and tests that copy, so every generated test
imports `outputs.agent_src.code.<TASK>...`. Copied into a repository as they
are, those tests would go on testing qikly's copy, not your file, which is the
opposite of what anyone copying them wants.

So this copies each stage's files to
`<your tests folder>/qikly_generated/<task>/<stage>/`, keeping their names, so
a generated `conftest.py` or helper module still works beside the tests that
use it. It rewrites every import of qikly's copy to the one your own tests
use, refuses any copy that would still reach `outputs/`, writes a
`qikly_generated/conftest.py` that makes your code importable from wherever it
lives, and runs the copies on your untouched code.

Each failure there is classified from pytest's own JUnit XML: a disagreement
between your code and your criteria; a call to something your code lacks,
usually a helper qikly's coding agent added to its copy; a copy that could
not import your module; or a test that could not be collected. Only the first
is said to be a disagreement.

A file this did not write is never overwritten: each copy starts with a marker
line, and only a file carrying it is replaced. Copies left over from an
earlier take that this one did not write are removed, so a rerun leaves no
duplicates.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import yaml

STAGES = ("integration", "system", "unit")
MARKER = "# Written by qikly from your answers"
FOLDER = "qikly_generated"
# Folders that are qikly's or the environment's, never the user's tests.
_NOT_TESTS = {"outputs", "inputs_private", "inputs_public", "qikly-suite-score",
              "venv", ".venv", "env", "__pycache__", "node_modules", "build",
              "dist", FOLDER}


def _read(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


_CONFTEST = '''"""
Written by qikly. Keeps a plain `pytest` from the project root out of this
folder: the tests here are qikly's working copies, which `qikly --take-tests`
copies into your own tests, and collecting both ran every test twice.
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
    """Write outputs/conftest.py unless one is there already. Returns its path if written."""
    folder = os.path.join(cwd, "outputs")
    path = os.path.join(folder, "conftest.py")
    if os.path.exists(path):
        return None
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_CONFTEST)
    return path


def task_config(cwd, task_id):
    path = os.path.join(cwd, "inputs_private", "config", "tasks", task_id + ".yaml")
    try:
        return yaml.safe_load(_read(path)) or {}
    except yaml.YAMLError:
        return {}


def _project_root(cwd, path):
    from qikly.start import project_root
    return project_root(path, cwd)


def own_import(cwd, task, test_dir):
    """
    (qikly's import path, the user's dotted import), (None, None) for a package
    seed that is already imported by its own name, or None when the task tests
    no code of the user's.

    The user's import is read from their own tests, outside every folder that
    is qikly's, and never accepted if it names outputs/: walking into
    outputs/ adopted qikly's own import and the copy kept testing qikly's
    copy. Failing that, it is the module's own dotted name.
    """
    from qikly import start_probe

    module = str((task.get("interface") or {}).get("module") or "")
    implementation = str((task.get("seed") or {}).get("implementation") or "")
    if not module or not implementation:
        return None
    prefix = "outputs.agent_src.code.%s." % task.get("task_id", "")
    if not module.startswith(prefix):
        return None, None
    path = os.path.join(cwd, implementation)
    stem = os.path.splitext(os.path.basename(implementation))[0]
    pattern = re.compile(
        r"^\s*(?:from\s+([\w.]+)\s+import\s+(?:\(?\s*)?[^\n]*\b%s\b"
        r"|from\s+([\w.]*\b%s)\s+import|import\s+([\w.]*\b%s)\b)"
        % (re.escape(stem), re.escape(stem), re.escape(stem)), re.M)
    for here, dirs, names in os.walk(test_dir):
        dirs[:] = sorted(d for d in dirs if d not in _NOT_TESTS and not d.startswith("."))
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            for found in pattern.finditer(_read(os.path.join(here, name))):
                if found.group(1):
                    candidate = f"{found.group(1)}.{stem}"
                else:
                    candidate = found.group(2) or found.group(3)
                if candidate and not candidate.startswith("outputs.") \
                        and candidate.split(".")[-1] == stem:
                    return module, candidate
    return module, start_probe.dotted_name(path, _project_root(cwd, path))


def rewrite(text, theirs, ours, task_id):
    """
    Every reference to qikly's copy, rewritten to the user's module. Covers
    `import X as m`, `from X import f`, string targets for monkeypatch and
    mock, and `from outputs.agent_src.code.T import pricing`, which a plain
    text replace missed, so that copy silently went on testing qikly's copy.
    """
    package = "outputs.agent_src.code.%s" % task_id
    if theirs and ours:
        stem = theirs.rsplit(".", 1)[-1]

        def from_package(match):
            names = [n.strip() for n in match.group(1).strip("()").split(",") if n.strip()]
            out = []
            for n in names:
                name, _, alias = n.partition(" as ")
                name, alias = name.strip(), (alias.strip() or name.strip())
                if name == stem:
                    out.append(f"import {ours} as {alias}")
                else:
                    out.append(f"from {package} import {n}")
            return "\n".join(out)

        text = re.sub(r"^from\s+%s\s+import\s+(\(?[^\n]+\)?)\s*$" % re.escape(package),
                      from_package, text, flags=re.M)
        text = text.replace(theirs, ours)
    else:
        # A package seed: the copy holds the package under the task folder.
        text = text.replace(package + ".", "")
    return text


def _still_reaches_outputs(text):
    return "outputs.agent_src" in text or "outputs/agent_src" in text or \
        "outputs\\agent_src" in text


def _conftest_for(cwd, task, folder):
    """qikly_generated/conftest.py: makes the user's code importable from here."""
    from qikly import start_probe

    implementation = str((task.get("seed") or {}).get("implementation") or "")
    path = os.path.join(cwd, implementation)
    if os.path.isdir(path):
        # A package seed: the package's own folder sits in the base.
        base = os.path.dirname(os.path.abspath(path))
    else:
        base = start_probe.import_base(path, _project_root(cwd, path))
    rel = os.path.relpath(base, folder)
    return (f"{MARKER}.\n"
            f'"""Puts the folder your code is imported from on the path, so the\n'
            f'copied tests import your module wherever pytest is run from."""\n'
            f"import os\nimport sys\n\n"
            f"_BASE = os.path.normpath(os.path.join(os.path.dirname("
            f"os.path.abspath(__file__)), {rel!r}))\n"
            f"if _BASE not in sys.path:\n    sys.path.insert(0, _BASE)\n")


def _write(path, text, written, skipped):
    if os.path.exists(path) and not _read(path).startswith(MARKER):
        skipped.append(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    written.append(path)


def take(cwd, task_id, test_dir, say=print):
    """
    Copy a run's tests home. Returns (written test files, result), or
    (None, reason) when there is nothing to copy.
    """
    from qikly.scaffold import importable

    task = task_config(cwd, task_id)
    if not task:
        return None, f"there is no task {task_id} under inputs_private/config/tasks"
    names = own_import(cwd, task, test_dir)
    if names is None:
        return None, (f"{task_id} does not test code of yours: it has no "
                      f"`seed: implementation`")
    theirs, ours = names
    implementation = str((task.get("seed") or {}).get("implementation") or "")
    stem = os.path.splitext(os.path.basename(implementation))[0]
    if theirs and importable(stem) != stem:
        return None, (f"{os.path.basename(implementation)} cannot be imported by "
                      f"that name, so copied tests could not import it either. "
                      f"Rename it to {importable(stem)}.py and run again")
    source_root = os.path.join(cwd, "outputs", "tests", task_id)
    if not os.path.isdir(source_root):
        return None, (f"{task_id} has no generated tests yet: run it first, "
                      f"with  qikly --tasks {task_id}")
    home = os.path.join(test_dir, FOLDER)
    dest_root = os.path.join(home, task_id.lower())
    written, skipped, refused, extras = [], [], [], []
    for stage in STAGES:
        folder = os.path.join(source_root, stage)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            text = rewrite(_read(os.path.join(folder, name)), theirs, ours, task_id)
            if _still_reaches_outputs(text):
                refused.append(f"{stage}/{name}")
                continue
            header = (f"{MARKER}, task {task_id}, {stage} stage.\n"
                      f"# Copied from outputs/tests/{task_id}/{stage}/{name}"
                      + (f", importing `{ours}` instead of qikly's copy" if theirs else "")
                      + ".\n# Run qikly --take-tests again to refresh it; edits "
                        "here are overwritten.\n\n")
            target = os.path.join(dest_root, stage, name)
            bucket = written if name.startswith("test_") or name.endswith("_test.py") \
                else extras
            _write(target, header + text, bucket, skipped)
    if not written:
        for path in skipped:
            say(f"  left alone, because qikly did not write it: {path}")
        return (written, None) if not refused else (None, "every generated test "
                                                    "still refers to qikly's copy")
    _write(os.path.join(home, "conftest.py"), _conftest_for(cwd, task, home), extras, skipped)
    # Packages all the way down, written by qikly: the same file names
    # (test_integration.py) repeat across stages and tasks, which pytest
    # refuses to collect side by side unless each folder is a package.
    init = f"{MARKER}: makes this folder a package, so names may repeat.\n"
    folders = {os.path.dirname(p) for p in written + extras}
    folders |= {home, dest_root}
    for folder in sorted(folders):
        if folder.startswith(home):
            _write(os.path.join(folder, "__init__.py"), init, extras, skipped)
    _remove_stale(dest_root, set(written) | set(extras))
    # And the flat names an earlier version wrote, test_<task>_<stage>.py.
    for name in os.listdir(home):
        path = os.path.join(home, name)
        if (name.startswith(f"test_{task_id.lower()}_") and name.endswith(".py")
                and _read(path).startswith(MARKER)):
            os.remove(path)
    for path in skipped:
        say(f"  left alone, because qikly did not write it: {path}")
    for path in refused:
        say(f"  not copied, because it still refers to qikly's copy: {path}")
    keep_outputs_out_of_pytest(cwd)
    _remember(cwd, task_id, test_dir)
    # Counted as test generation saw them, the TODOs a run skips left out:
    # a test tagged with a number past that was not written from any criterion.
    from qikly.score_questions import drop_question_lines
    path = os.path.join(cwd, "inputs_private", "config", "tasks", task_id + ".yaml")
    try:
        seen = (yaml.safe_load(drop_question_lines(_read(path))) or {}).get(
            "acceptance_criteria") or []
    except yaml.YAMLError:
        seen = task.get("acceptance_criteria") or []
    return written + extras, _run(cwd, written, len(seen))


def _remove_stale(dest_root, keep):
    """Copies from an earlier take of this task that this one did not write."""
    keep = {os.path.normcase(os.path.abspath(p)) for p in keep}
    for here, _, names in os.walk(dest_root):
        for name in names:
            path = os.path.join(here, name)
            if os.path.normcase(os.path.abspath(path)) in keep:
                continue
            if name.endswith(".py") and _read(path).startswith(MARKER):
                os.remove(path)


def _choice_path(cwd):
    return os.path.join(cwd, "inputs_private", "questions", "take_tests.json")


def _remember(cwd, task_id, test_dir):
    try:
        with open(_choice_path(cwd), encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        found = {}
    found[task_id] = os.path.relpath(test_dir, cwd)
    os.makedirs(os.path.dirname(_choice_path(cwd)), exist_ok=True)
    with open(_choice_path(cwd), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(found, handle, indent=1)


def remembered_folder(cwd, task_id):
    try:
        with open(_choice_path(cwd), encoding="utf-8") as handle:
            rel = json.load(handle).get(task_id)
    except (OSError, ValueError, AttributeError):
        return None
    return os.path.join(cwd, rel) if rel else None


# ---------------------------------------------------------------- running --

_MISSING = re.compile(r"cannot import name|module '[\w.]+' has no attribute")


def _tagged_tests(paths, criteria_count):
    """
    The (file stem, test name) pairs the writer tagged with one of the
    answers, read the way the rest of qikly reads tags (traceability), and
    only for numbers that are answers. Only those can disagree with an
    answer: an untagged test is the writer's own reading of the code or the
    requirements, and on semantic_version two such tests misused its API.
    Keyed by file too: a tagged test_sum in one file made an untagged
    test_sum in another read as tagged.
    """
    from qikly import traceability
    pairs = {}
    for path in paths:
        if not path.endswith(".py"):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                traced = traceability.trace_source(handle.read())
        except (OSError, ValueError):
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        for name, indices in traced.items():
            if isinstance(indices, list) and any(
                    0 < i <= criteria_count for i in indices):
                pairs[(stem, name)] = [i for i in indices if 0 < i <= criteria_count]
    return pairs


def criteria_with_origin(cwd, task_id):
    """
    The criteria in the order test generation numbers them, each with who
    wrote it: "docs" for the spec agent quoting the documentation, "check"
    for the spec agent judging from the module's purpose, "you" otherwise.
    """
    from qikly.score_questions import _ITEM, _scalar, expand_answers, is_todo
    path = os.path.join(cwd, "inputs_private", "config", "tasks", task_id + ".yaml")
    text = expand_answers(_read(path))[0]
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("acceptance_criteria:")), None)
    out, origin = [], "you"
    if start is None:
        return out
    for line in lines[start + 1:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        if "#? CHECK:" in line:
            origin = "check"
        elif "#? Drafted from your documentation" in line:
            origin = "docs"
        item = _ITEM.match(line)
        if item and not line.lstrip().startswith("#"):
            value, _ = _scalar(item.group(3))
            if value is not None and not is_todo(value):
                out.append((value, origin))
            origin = "you"
    return out


def _run(cwd, paths, criteria_count=0):
    """
    The copied tests on the user's own code, each failure classified from
    pytest's JUnit XML: (summary, disagree, missing, no_import, broken,
    unanswered), unanswered being failures of tests no answer is behind.
    """
    from qikly.scaffold import importable  # noqa: F401  (keeps imports local)

    xml_path = os.path.join(tempfile.mkdtemp(), "result.xml")
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
             "-p", "no:cacheprovider", "--continue-on-collection-errors",
             "--junitxml", xml_path] + paths,
            cwd=cwd, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return "the copied tests could not be run"
    lines = [l for l in done.stdout.splitlines() if l.strip()]
    summary = next((l for l in reversed(lines)
                    if re.search(r"\b(passed|failed|error)", l)), "").strip("= ").strip()
    disagree, missing, no_import, broken, unanswered = [], [], [], [], []
    tagged = _tagged_tests(paths, criteria_count)
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return summary, disagree, missing, no_import, broken, unanswered
    for case in tree.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        label = (case.get("classname", "").replace(".", "/") + "::" + case.get("name", "")
                 ).strip(":")
        text = (problem.get("message") or "") + "\n" + (problem.text or "")
        # A file pytest could not collect is reported as a nameless case; it
        # says nothing about the user's code, whatever exception it carries.
        collection = problem.tag == "error" and (
            problem.get("message") == "collection failure" or not case.get("name"))
        if _MISSING.search(text):
            missing.append(label)
        elif re.search(r"ModuleNotFoundError|ImportError", text):
            no_import.append(label)
        elif collection or "SyntaxError" in text or \
                ("fixture '" in text and "not found" in text):
            broken.append(label)
        elif problem.tag == "error" and not case.get("name"):
            broken.append(label)
        elif (_stem_of(case.get("classname", "")),
              case.get("name", "").split("[")[0]) in tagged:
            disagree.append(label)
        else:
            unanswered.append(label)
    shutil.rmtree(os.path.dirname(xml_path), ignore_errors=True)
    return summary, disagree, missing, no_import, broken, unanswered


def _stem_of(classname):
    """The test file's stem from a JUnit classname, `a.b.test_system[.Class]`."""
    parts = classname.split(".")
    files = [p for p in parts if p.startswith("test")]
    return files[-1] if files else (parts[-1] if parts else "")


def report(say, cwd, written, result, task_id):
    tests = [p for p in written if os.path.basename(p).startswith("test_")]
    say(f"Copied {len(tests)} test file{'' if len(tests) == 1 else 's'} into "
        f"your tests, importing your own code:")
    for path in tests:
        say(f"  {os.path.relpath(path, cwd)}")
    others = len(written) - len(tests)
    if others:
        home = os.path.relpath(os.path.dirname(os.path.dirname(os.path.dirname(tests[0])))
                               if tests else cwd, cwd)
        say(f"  and {others} supporting file{'' if others == 1 else 's'} under "
            f"{home}{os.sep}: a conftest.py that makes your code importable, and "
            f"__init__.py files")
    if not result:
        return
    if isinstance(result, str):
        say(f"Run on your own code: {result}.")
        return
    summary, disagree, missing, no_import, broken, unanswered = result
    say(f"Run on your own code: {summary or 'no result'}.")
    if unanswered:
        say("These fail on your code but were not written from any of your "
            "criteria: they are the test writer's own reading of your code or "
            "your requirements, which can be wrong. Check each one before "
            "changing anything; if the test is wrong, delete it:")
        for name in unanswered:
            say(f"  {name}")
    if disagree:
        # Never "apply the same fix": on python-dotenv the test asserted more
        # than the answer said, and the copy's change to pass it altered a
        # documented default. Which side is wrong is for a person to judge.
        say("These fail on your code and were written from your criteria. Either "
            "your code disagrees with the criterion, or the test asserts more than "
            "the criterion said. Compare each with its criterion before changing "
            "anything. qikly's change to its own copy, which makes them pass, is "
            "in " + os.path.join("outputs", "logs", "patches", task_id) + os.sep
            + "; read it before taking any of it:")
        tagged = _tagged_tests(tests, 10 ** 6)
        criteria = criteria_with_origin(cwd, task_id)
        drafted = False
        for name in disagree:
            say(f"  {name}")
            key = (_stem_of(name.split("::")[0].replace("/", ".")),
                   name.split("::")[-1].split("[")[0])
            for i in tagged.get(key, [])[:2]:
                if 0 < i <= len(criteria):
                    text, origin = criteria[i - 1]
                    note = {"docs": "  (drafted from your documentation)",
                            "check": "  (drafted from the module's purpose: check it)"
                            }.get(origin, "")
                    drafted = drafted or origin != "you"
                    say(f"      criterion {i}: {text}{note}")
        if drafted:
            say("  A drafted criterion was written without your code. Where it and "
                "your code disagree, which one is right is yours to decide: change "
                "the criterion in the task file, or the code.")
    if missing:
        say("These call something your code does not have, usually a helper "
            "qikly's coding agent added to its copy while fixing it. Take the "
            "helper from the same patch, or delete these tests:")
        for name in missing:
            say(f"  {name}")
    if no_import:
        say("These could not import your module from where pytest ran. Run "
            "pytest from this folder, or set PYTHONPATH to the folder your "
            "code is imported from:")
        for name in no_import:
            say(f"  {name}")
    if broken:
        say("These could not be collected at all, which says nothing about your "
            "code; the step-by-step report shows why:")
        for name in broken:
            say(f"  {name}")
    say("Some read the example data by a path relative to this folder, so run "
        "pytest from here.")


def main(task_ids, cwd, test_dir=None):
    """`qikly --take-tests TASK[,TASK...]`."""
    status = 0
    for task_id in [t.strip() for t in task_ids.split(",") if t.strip()]:
        folder = test_dir or remembered_folder(cwd, task_id) or os.path.join(cwd, "tests")
        if not task_config(cwd, task_id):
            print(f"Nothing copied: there is no task {task_id} under "
                  f"inputs_private/config/tasks.")
            status = 2
            continue
        os.makedirs(folder, exist_ok=True)
        written, result = take(cwd, task_id, folder)
        if written is None:
            print(f"Nothing copied for {task_id}: {result}.")
            status = 2
        elif not written:
            print(f"Nothing copied for {task_id}: every target file is one qikly "
                  f"did not write.")
            status = 2
        else:
            report(print, cwd, written, result, task_id)
    return status
