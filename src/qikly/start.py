"""
`qikly --questions PATH` and `qikly --answers PATH`: from the tests you have to a suite written from your
own answers, in one guided command.

A new-user walkthrough of the three separate steps (`--score-code`,
`--scaffold`, `--tasks`) on 2026-10-15 found a YAML file to edit in six places,
a CSV with only a header, a task id ending in an unexplained `_VERIFY`, and
five other entry flags. Only a few things in that flow need a person: what the
module does, an answer to each question, anything else that must be true, and
a few rows of example values. This asks for exactly those, and fills in or
leaves out everything else.

Two rules hold for every prompt, because a confused first run is a lost user:

- **What to type is always said, on the prompt's last line.** Menus say "Type
  a number from 1 to N"; free text says what kind of text, with an example.
  Wrong input gets one line saying why and the same prompt again. Nothing is
  ever chosen by default.
- **Where everything is saved is said up front, as it is saved, and at the
  end.**

Every menu is numbered and its last option is free text, which is the user's
rule. The answers stay the person's: see `start_options` for how the options
are built without reading the answer off the code.

The separate commands remain, for scripts and CI. When input is not a
terminal this never waits: it prints the questions, writes them to a file in
the format `--answers` reads, and exits with code 3.
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

from qikly import start_options as so

# Exit codes beyond 0 (done) and 2 (could not start).
NEEDS_ANSWERS = 3
STOPPED = 130

SCORE_CAP_ONE, SCORE_CAP_MANY = 60, 150
_SKIP_DIRS = {"tests", "test", "venv", ".venv", "env", "outputs",
              "inputs_private", "inputs_public", "qikly-suite-score",
              "node_modules", "__pycache__", "build", "dist", "site-packages",
              "demo"}
_ROOT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", ".git")


class Stop(Exception):
    """The user asked to stop, or input ran out. Never an error."""


def is_terminal():
    """
    Whether someone can answer. `isatty()` alone is not enough on Windows,
    where the null device reports itself as a terminal: `qikly --start <
    NUL` would then wait on a prompt nobody can see. There the console API
    is asked instead.
    """
    # Forced on for a terminal Python cannot recognise, such as Git Bash's
    # window, where input() still works: answers typed there are read as
    # typed. Never forced off silently; an empty value means "not set".
    if os.environ.get("QIKLY_INTERACTIVE", "").strip() == "1":
        return True
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle,
                                                          ctypes.byref(mode)))
    except Exception:
        return True


class Console(object):
    """Input and output, so a test can script both."""

    def __init__(self, ask=input, say=print, interactive=None):
        self._ask, self._say = ask, say
        self.interactive = (is_terminal() if interactive is None
                            else interactive)
        if ask is input and self.interactive:
            _utf8_stdin()

    def say(self, text=""):
        self._say(text)

    def ask(self, prompt):
        try:
            raw = self._ask(prompt + " ")
        except EOFError:
            raise Stop()
        if raw is None:
            raise Stop()
        # A pasted line can carry a carriage return, a control character or a
        # line separator; none is ever meant, and several make the task file
        # invalid YAML or change on reading it back.
        return _UNSAFE.sub("", raw.replace("\t", " ")).strip()


# C0 controls, DEL, C1 controls (NEL included), the Unicode line and paragraph
# separators, lone surrogates and the two non-characters YAML refuses.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f  \ud800-\udfff￾￿]")


def _utf8_stdin():
    """
    Read piped answers as UTF-8. With QIKLY_INTERACTIVE=1 in Git Bash, stdin
    is a pipe in the locale's code page, and "café" was saved as mojibake. A
    real console is left alone: Python reads it as Unicode already.
    """
    try:
        if not _is_console():
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def _is_console():
    if os.name != "nt":
        return sys.stdin.isatty()
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_uint()
        return bool(ctypes.windll.kernel32.GetConsoleMode(
            msvcrt.get_osfhandle(sys.stdin.fileno()), ctypes.byref(mode)))
    except Exception:
        return False


# ----------------------------------------------------------------- prompts --

_QUIT = {"q", "quit", "exit", "stop"}


def choose(console, options, lead=None):
    """
    Show a numbered menu and return the 1-based number picked.

    Accepts "3", " 3 ", "3." and "3)". Anything else, empty input included,
    gets one line saying why and the menu's prompt again: there is no
    default, so Enter never picks anything.
    """
    for line in (lead or []):
        console.say(line)
    for number, label in enumerate(options, 1):
        console.say(f"  {number}. {label}")
    count = len(options)
    prompt = f"Type a number from 1 to {count}, then press Enter:"
    while True:
        raw = console.ask(prompt)
        if raw.lower() in _QUIT:
            raise Stop()
        cleaned = raw.rstrip(".)").strip()
        if cleaned.isdigit() and 1 <= int(cleaned) <= count:
            return int(cleaned)
        if not raw:
            console.say(f"Nothing was chosen. Please type a number from 1 to "
                        f"{count}.")
        elif cleaned.isdigit():
            console.say(f"There is no option {cleaned}. Please type a number "
                        f"from 1 to {count}.")
        else:
            typed = raw if len(raw) <= 40 else raw[:37] + "..."
            console.say(f"\"{typed}\" is not one of the numbers. Please "
                        f"type a number from 1 to {count}.")


def free_text(console, what, example=None):
    """A line of text, never empty. `what` says what kind of text is wanted."""
    prompt = what + (f", such as {example}" if example else "") + ". Then press Enter:"
    while True:
        raw = console.ask(prompt)
        if raw.lower() in _QUIT:
            raise Stop()
        if raw:
            return raw
        console.say("Nothing was typed. Please type it, or press Ctrl+C to stop.")


# ----------------------------------------------------------------- finding --

def project_root(path, cwd=None):
    """
    The nearest folder above `path` holding a project marker. Without one,
    the folder the command was run from when `path` is inside it: a package
    folder beside a `tests/` folder has no marker of its own, and searching
    only inside the package found no tests at all.
    """
    current = os.path.abspath(path if os.path.isdir(path) else os.path.dirname(path))
    probe = current
    while True:
        if any(os.path.exists(os.path.join(probe, m)) for m in _ROOT_MARKERS):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if cwd and (current == os.path.abspath(cwd)
                or current.startswith(os.path.abspath(cwd) + os.sep)):
        return os.path.abspath(cwd)
    return current


def _is_module(name):
    return (name.endswith(".py") and name not in ("__init__.py", "__main__.py",
                                                  "conftest.py", "setup.py")
            and not name.startswith("test_") and not name.endswith("_test.py"))


def _is_test(name):
    return name.endswith(".py") and (name.startswith("test_")
                                     or name.endswith("_test.py"))


def modules_in(folder):
    """
    The modules under a folder, tests and tooling left out, sorted. An
    `__init__.py` that holds code counts, because tabulate and inflection keep
    their whole library there; `__main__.py` does not, since importing it
    runs a program.
    """
    from qikly.mutation_score import has_code

    out = []
    for here, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS
                         and not d.startswith("."))
        for n in sorted(names):
            path = os.path.join(here, n)
            if _is_module(n) or (n == "__init__.py" and has_code(path)):
                out.append(path)
    return out


def import_names(code):
    """
    The names a test may import this code by: each module's own name, the
    package name for an `__init__.py`, and the name of every package the
    code sits in. humanize's tests say `import humanize`, never the module
    file names, and matching only those found no tests at all.
    """
    paths = [code] if os.path.isfile(code) else modules_in(code)
    names = set()
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        folder = os.path.dirname(os.path.abspath(p))
        if stem != "__init__":
            names.add(stem)
        while os.path.isfile(os.path.join(folder, "__init__.py")):
            names.add(os.path.basename(folder))
            folder = os.path.dirname(folder)
    if os.path.isdir(code) and os.path.isfile(os.path.join(code, "__init__.py")):
        names.add(os.path.basename(os.path.abspath(code)))
    return sorted(n for n in names if n.isidentifier())


def _test_files(root):
    out = []
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS - {"tests", "test"}
                         and not d.startswith("."))
        out += [os.path.join(here, n) for n in sorted(names) if _is_test(n)]
    return out


def _read(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _imports(source, stem, own=None):
    """
    Whether a test imports `stem`, alone or inside a dotted name that starts
    with one of `own`, the project's own names. `import os.path` is not an
    import of a project's geo/path.py, and matching any dotted name said so.
    """
    own = set(own or ()) | {stem}
    for found in re.finditer(r"^\s*(?:from\s+([\w.]+)|import\s+([\w., ]+))", source, re.M):
        dotted = [found.group(1)] if found.group(1) else \
            [n.strip().split(" ")[0] for n in found.group(2).split(",")]
        for name in dotted:
            parts = name.split(".")
            if stem in parts and parts[0] in own:
                return True
    return False


def shown(path, base):
    """A path relative to `base` when it is inside it, else in full."""
    try:
        rel = os.path.relpath(path, base)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def _specific(code):
    """
    (module names, public names) that mark a test as this code's own: the
    module imported by name, or one of its public functions or classes
    imported from its package, as in validators' `from validators import
    card_number`, which never names the module `card`.
    """
    import ast
    paths = [code] if os.path.isfile(code) else modules_in(code)
    modules, public = set(), set()
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        if stem != "__init__":
            modules.add(stem)
        else:
            modules.add(os.path.basename(os.path.dirname(os.path.abspath(p))))
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        public |= {n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   and not n.name.startswith("_")}
    return modules, public


def _imports_specifically(source, modules, public, packages):
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        # A dotted name counts only from its own top: `import os.path` is not
        # an import of a project's geo/path.py.
        own = packages | modules
        if isinstance(node, ast.Import):
            if any(set(a.name.split(".")) & modules and a.name.split(".")[0] in own
                   for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if set(parts) & modules and parts[0] in own:
                return True
            names = {a.name for a in node.names}
            if parts[-1] in packages and names & (modules | public):
                return True
            if parts[-1] in modules and parts[0] in own:
                return True
    return False


def importing_tests(code, root):
    """
    The test files that import this code, most specific first: those that
    import the module itself or one of its public names, and only if there
    are none, those that import its package at all. Matching every test that
    imported validators sent card.py's score through the whole suite,
    failing optional-dependency tests included.
    """
    files = _test_files(root)
    modules, public = _specific(code)
    packages = set(import_names(code)) - modules if os.path.isfile(code) else set()
    if os.path.isdir(code):
        packages = set()
    narrow = [f for f in files
              if _imports_specifically(_read(f), modules, public,
                                       set(import_names(code)) | packages)]
    names = import_names(code)
    broad = [f for f in files if any(_imports(_read(f), s, names) for s in names)]
    if os.path.isdir(code):
        # A whole package is tested by everything that imports it, including
        # `import humanize` followed by `humanize.naturalsize(...)`.
        return sorted(set(narrow) | set(broad))
    return narrow or broad


def auto_tests(code, cwd=None):
    """The tests to use without asking: the files that import the code."""
    root = project_root(code, cwd)
    found = importing_tests(code, root)
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    folders = [os.path.dirname(f) for f in found]
    if len(set(folders)) == 1:
        return folders[0]
    common = os.path.commonpath(found)
    code_dir = os.path.abspath(code if os.path.isdir(code) else os.path.dirname(code))
    # A common folder holding the code itself would be scored as both, which
    # scoring refuses; the folder with most of the tests is the better guess.
    if code_dir == common or code_dir.startswith(common + os.sep):
        return max(set(folders), key=folders.count)
    return common


NO_TESTS = os.path.join("qikly-suite-score", "no_tests")


def is_placeholder(tests, cwd):
    return os.path.abspath(tests).startswith(os.path.abspath(os.path.join(cwd, NO_TESTS)))


# -------------------------------------------------------------- the state --

class Paths(object):
    """Every file this writes, named once, so the messages and the files agree."""

    def __init__(self, cwd, module, base=None):
        from qikly import score_questions
        from qikly.scaffold import VERIFY_SUFFIX
        self.cwd = cwd
        self.module = module
        if base is None:
            base = score_questions.task_for(module)[:-len(VERIFY_SUFFIX)]
        self.name(base)

    def name(self, base):
        """Every path follows the task's name, so a rename moves them all."""
        from qikly.scaffold import VERIFY_SUFFIX
        cwd = self.cwd
        self.base = base
        self.task_id = base + VERIFY_SUFFIX
        self.task = os.path.join(cwd, "inputs_private", "config", "tasks",
                                 self.task_id + ".yaml")
        self.data = os.path.join(cwd, "inputs_private", "data", self.base,
                                 "input_01.csv")
        folder = os.path.join(cwd, "inputs_private", "questions")
        self.state = os.path.join(folder, self.base + "_start.json")
        self.open = os.path.join(folder, self.base + "_open_questions.txt")
        self.tests = os.path.join(cwd, "outputs", "tests", self.task_id)

    def rel(self, path):
        return shown(path, self.cwd)


def task_bases(modules, code):
    """
    A task name for each module. Two modules called util.py in different
    subfolders both became UTIL_VERIFY and overwrote each other's answers, so
    a name that repeats is built from the module's path inside the folder.
    """
    from qikly import score_questions
    from qikly.scaffold import VERIFY_SUFFIX

    plain = {m: score_questions.task_for(m)[:-len(VERIFY_SUFFIX)] for m in modules}
    counts = {}
    for b in plain.values():
        counts[b] = counts.get(b, 0) + 1
    out = {}
    folder = code if os.path.isdir(code) else os.path.dirname(code)
    for m, b in plain.items():
        if counts[b] > 1:
            rel = os.path.splitext(os.path.relpath(m, folder))[0]
            b = re.sub(r"[^A-Za-z0-9]+", "_", rel).strip("_").upper() or b
        out[m] = b
    return out


def _session_path(cwd, code):
    rel = shown(code, cwd)
    name = re.sub(r"[^A-Za-z0-9]+", "_", rel).strip("_") or "code"
    return os.path.join(cwd, "inputs_private", "questions", f"{name}_session.json")


def load_session(cwd, code):
    """What the last --start on this code chose and found, or {}."""
    try:
        with open(_session_path(cwd, code), encoding="utf-8") as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session(cwd, code, session):
    path = _session_path(cwd, code)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(session, handle, indent=1)
    os.replace(path + ".tmp", path)


def fingerprint(code, tests):
    """A hash of every code and test file, so an unchanged pair is not re-scored."""
    files = ([code] if os.path.isfile(code) else modules_in(code))
    files += ([tests] if os.path.isfile(tests) else _test_files(tests))
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        digest.update(path.encode("utf-8"))
        digest.update(_read(path).encode("utf-8", "replace"))
    return digest.hexdigest()[:16]


def _key(question):
    raw = f"{question.get('file')}|{question.get('line')}|{question.get('question')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def load_state(paths):
    try:
        with open(paths.state, encoding="utf-8") as handle:
            state = json.load(handle)
        return state if isinstance(state, dict) else None
    except (OSError, ValueError):
        return None


def save_state(paths, state):
    os.makedirs(os.path.dirname(paths.state), exist_ok=True)
    tmp = paths.state + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, indent=1)
    os.replace(tmp, paths.state)


# ------------------------------------------------------------------ scoring --

def score(console, code, tests, cwd, many):
    """Score the suite, write the report, and return (result, report path)."""
    from qikly import mutation_score as ms

    try:
        target = ms.from_paths(code, tests)
    except ValueError as exc:
        console.say(str(exc))
        return None, None
    sites = 0
    for path, _ in target.files:
        sites += len(ms.sites(_read(path)))
    cap = SCORE_CAP_MANY if many else SCORE_CAP_ONE
    planted = min(sites, cap)
    if not planted:
        console.say("There is nothing in that code qikly knows how to change, "
                    "so there is nothing to score.")
        return None, None
    planted = _fit_to_time(console, tests, cwd, planted)
    console.say(f"Scoring: planting {planted} fault{'' if planted == 1 else 's'}"
                f", one at a time, in a copy of your code"
                + (f" (a sample of the {sites} it could plant)" if sites > cap else "")
                + ". Each one runs your tests once, so this takes a little "
                  "while. No model is called.")
    try:
        result = ms.score(target, mutants=planted, seed=0)
    except ms.NeverRan as exc:
        console.say(f"Could not be scored: {exc}")
        return None, None
    if result is None:
        console.say("Nothing to score: no tests were found at that path.")
        return None, None
    again = score_questions_pasteable(code, cwd)
    path = ms.write(result, ms.unreachable_criteria(None),
                    ms.report_dir(target, cwd), cwd,
                    advice=[f"Next: `qikly --questions {again}` writes these to a "
                            f"file to answer at your own pace."])
    if not result["baseline"]:
        console.say(f"Your tests do not pass on your untouched code, so a planted "
                    f"fault would prove nothing (report: {shown(path, cwd)}). "
                    f"What pytest said:")
        for line in _pytest_tail(tests, cwd):
            console.say("    " + line)
        console.say("The usual cause is an import: run qikly from the folder "
                    "your tests import from, or set PYTHONPATH to it.")
        return None, None
    return result, path


QUICK_ENOUGH = 300   # seconds of scoring before the user is asked first


def _fit_to_time(console, tests, cwd, planted):
    """
    How many faults to plant, given how long the suite takes. Every fault
    runs the whole suite once, and tabulate's folder ran for over an hour
    with nothing on screen. So the suite is timed once, the estimate is
    said, and above five minutes a smaller sample is offered, or chosen
    when there is nobody to ask.
    """
    import time
    started = time.monotonic()
    try:
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "--color=no",
                        "-p", "no:cacheprovider", tests], cwd=cwd,
                       capture_output=True, text=True, timeout=900)
    except (subprocess.TimeoutExpired, OSError):
        return planted
    each = max(time.monotonic() - started, 0.3)
    total = each * planted

    def minutes(seconds):
        return f"{seconds / 60:.0f} minute{'' if round(seconds / 60) == 1 else 's'}" \
            if seconds >= 90 else f"{seconds:.0f} seconds"

    if total <= QUICK_ENOUGH:
        return planted
    sample = min(planted, max(12, int(QUICK_ENOUGH / each)))
    console.say(f"Your tests take about {each:.0f} seconds to run, and each "
                f"planted fault runs them once, so all {planted} would take "
                f"about {minutes(total)}.")
    if sample >= planted:
        # A sample of 12 from 10 is all of them, and offering it read as a cut.
        console.say(f"That is fewer than a useful sample, so all {planted} are planted.")
        return planted
    if not console.interactive:
        console.say(f"Planting a sample of {sample} instead, about "
                    f"{minutes(each * sample)}. More questions come from more "
                    f"faults; in a terminal you can choose.")
        return sample
    picked = choose(console, [
        f"plant a sample of {sample}, about {minutes(each * sample)}",
        f"plant all {planted}, about {minutes(total)}",
        "type how many to plant",
    ])
    if picked == 1:
        return sample
    if picked == 2:
        return planted
    while True:
        raw = free_text(console, f"Type a number from 1 to {planted}", "30")
        if raw.isdigit() and 1 <= int(raw) <= planted:
            return int(raw)
        console.say(f"Please type a number from 1 to {planted}.")


def score_questions_pasteable(path, cwd=None):
    """A path to print in a command: relative, forward slashes, quoted if spaced."""
    from qikly import score_questions
    return score_questions._pasteable(shown(path, cwd or os.getcwd()))


def _pytest_tail(tests, cwd, lines=12, env=None):
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q",
                               "--color=no", "-p", "no:cacheprovider", tests],
                              cwd=cwd, capture_output=True, text=True, timeout=300,
                              env=env)
    except (subprocess.TimeoutExpired, OSError):
        return ["(pytest could not be run)"]
    out = [l for l in (done.stdout + done.stderr).splitlines() if l.strip()]
    errors = [l for l in out if l.startswith(("E ", "ERROR", "FAILED"))]
    return (errors or out)[:lines]


def enrich(questions, missed):
    """
    Give each question its kind of change and, where one applies, the source
    with that change planted, so the options can show what differs.
    """
    from qikly import mutation_score as ms
    from qikly import score_questions as sq
    from qikly.mutation import make_mutant

    sources = {}
    for q in questions:
        path = q.get("path")
        if path and path not in sources:
            sources[path] = _read(path)
        source = sources.get(path)
        for item in missed:
            kind, line = sq.split_change(item.get("change"))
            if (item.get("path") == path and line == q.get("line")
                    and sq.ask(kind, source, line) == q.get("question")):
                q["kind"] = kind
                for family, index, described in ms.sites(source or ""):
                    if described == item["change"]:
                        q["mutant"] = make_mutant(source, index, family)[0]
                        break
                break
    return questions


def group(questions):
    """
    One question per (file, function, question): a table of 37 regexes that
    all miss the same anchor asked the same thing 37 times on a real library,
    and nobody answers that. The first line is kept, the rest are listed.
    Questions about public functions come first, then the top level, then
    private helpers, because those are the ones a person can answer.
    """
    kept, seen, lines = [], {}, {}

    def shape(q):
        # The line's code with its literal values blanked: the question text
        # alone is the same for every guard of a function, and two checks,
        # `price < 0` and `rate > 1`, became one question about the first.
        path = q.get("path") or q.get("file")
        if path not in lines:
            lines[path] = _read(path).splitlines() if path else []
        n = q.get("line") or 0
        text = lines[path][n - 1] if 0 < n <= len(lines[path]) else ""
        text = re.sub(r"(['\"]).*?\1", "S", text.strip())
        return re.sub(r"\b\d+(\.\d+)?\b", "N", text)

    for q in questions:
        mark = (q.get("path") or q.get("file"), q.get("function"), q.get("question"),
                shape(q))
        if mark in seen:
            seen[mark].setdefault("also", []).append(q.get("line"))
            continue
        seen[mark] = q
        kept.append(q)

    def rank(q):
        name = q.get("function")
        if not name:
            return 1
        return 2 if name.split(".")[-1].startswith("_") else 0
    return sorted(kept, key=rank)


# -------------------------------------------------------------- one module --

def _context(source, line):
    lines = (source or "").splitlines()
    out = []
    for n in range(max(1, (line or 0) - 1), min(len(lines), (line or 0) + 1) + 1):
        out.append(f"  {'>' if n == line else ' '} {n:4d} {lines[n - 1]}")
    return out


def where(q):
    """
    "apply_discount, line 3", or "shipping.py, top level, line 6" for a line
    outside any function, which used to read "None, line 6".
    """
    also = q.get("also") or []
    more = ""
    if also:
        shown_ = ", ".join(str(n) for n in also[:5]) + (", ..." if len(also) > 5 else "")
        more = f" (and {len(also)} more line{'' if len(also) == 1 else 's'} like it: {shown_})"
    if q.get("function"):
        return f"{q['function']}, line {q.get('line')}{more}"
    name = os.path.basename(q.get("path") or q.get("file") or "the module")
    return f"{name}, top level, line {q.get('line')}{more}"


def _call_in(text):
    """(function, args) for a typed answer that opens with a literal call,
    such as "apply_discount(100, 0) returns 100.0", else None."""
    import ast
    found = re.match(r"\s*(\w+\(.*?\))(?=\s|$)", text)
    if not found:
        return None
    try:
        node = ast.parse(found.group(1), mode="eval").body
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return None
        return (node.func.id, [ast.literal_eval(a) for a in node.args],
                {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg})
    except (SyntaxError, ValueError, TypeError):
        return None


def _is_default(source, function, name, value):
    """Whether `value` is only the signature's default, so a real call wins."""
    defaults = so.literal_defaults(source, function)
    return name in defaults and defaults[name] == value


def build_rows(state, columns, source, test_sources):
    """Rows from the answered calls and the literal calls in the tests."""
    from qikly.scaffold import read_functions

    rows, typical = [], {}
    functions = {f.name: [a.arg for a in f.args.posonlyargs + f.args.args]
                 for f in read_functions(source)}

    def values_of(function, args, kwargs):
        values = dict(zip(functions[function], args))
        values.update(kwargs or {})
        return values

    for rec in state["answers"].values():
        if rec.get("function") in functions and rec.get("args") is not None:
            rows.append(values_of(rec["function"], rec["args"], rec.get("kwargs")))
        elif rec.get("criterion"):
            call = _call_in(rec["criterion"])
            if call and call[0] in functions:
                rows.append(values_of(*call))
    for extra in state.get("extra", []):
        call = _call_in(extra)
        if call and call[0] in functions:
            rows.append(values_of(*call))
    for name, params in functions.items():
        # A column no call fills, such as express=False left at its default,
        # takes the default rather than dropping the whole row.
        for k, v in so.literal_defaults(source, name).items():
            typical.setdefault(k, v)
        for args, kwargs in so.literal_calls(test_sources, name):
            if len(args) <= len(params):
                values = dict(zip(params, args))
                values.update(kwargs)
                rows.append(values)
                for k, v in values.items():
                    typical[k] = typical.get(k) if k in typical and not \
                        _is_default(source, name, k, typical.get(k)) else v
    out = []
    for values in rows:
        row = []
        for column in columns:
            value = values.get(column, typical.get(column))
            if value is None:
                break
            row.append(str(value))
        else:
            if row not in out:
                out.append(row)
    return out[:8]


# ------------------------------------------------------------------ writing --

def _q(text):
    return json.dumps(text, ensure_ascii=False)


def task_text(paths, state):
    """The task file, from scaffold's own template with every TODO filled."""
    from qikly.scaffold import build_task, PLACEHOLDER_CRITERIA

    # The task's own name, so a renamed task's id, data path and module path
    # all follow it; without it a rename wrote a file that failed --validate.
    text, problem = build_task(paths.module, paths.cwd, task_id=paths.base,
                               seed="existing")
    if problem:
        raise ValueError(problem)
    name = os.path.basename(paths.module)
    # Every replacement goes through a function: as a replacement string, a
    # backslash in the user's text was read as an escape, which halved it and
    # broke the YAML for a docstring as ordinary as "C:\data\prices".
    task_name = f"task_name: {_q(paths.task_id + ': ' + name)}"
    text = re.sub(r'^task_name: ".*"$', lambda m: task_name, text, count=1,
                  flags=re.M)
    description = ("description: " + _q("Tests for the existing " + name +
                   ", written from its owner's answers by qikly --answers."))
    text = re.sub(r'^description: ".*"$', lambda m: description, text, count=1,
                  flags=re.M)
    text = re.sub(r"  # TODO: what it does, e\.g\. reads one CSV and returns its rows",
                  "", text)
    text = text.replace("  # guessed, check this", "")
    text = _as_package_seed(text, paths)
    # The template's section headings address someone filling it in by
    # hand; here every section is already filled.
    text = text.replace("# Generated by `qikly scaffold`. Two sections need you.",
                        "# Written by `qikly --answers` from your answers. Run it "
                        "again to change them.")
    text = text.replace("# TODO. The decisions:", "# The decisions:")
    text = text.replace("# TODO. The consequences:", "# The consequences:")
    requirements = "requirements:\n  - " + _q(state.get("requirements") or "") + "\n"
    text = re.sub(r'requirements:\n  - "TODO:.*?"\n', lambda m: requirements,
                  text, count=1, flags=re.S)
    if state.get("sample"):
        ext = os.path.splitext(state["sample"])[1] or ".csv"
        text = text.replace("/input_01.csv", "/input_01" + ext)
    criteria, open_lines = [], []
    for rec in state["answers"].values():
        if rec["status"] == "answered":
            criteria.append(rec["criterion"])
        elif rec["status"] in (so.ASK, so.SKIP):
            open_lines.append(f"  #? open, {rec['where']}: {rec['question']}")
    criteria += state.get("extra", [])
    block = "acceptance_criteria:\n"
    block += "".join(f"  - {_q(c)}\n" for c in criteria) or \
        PLACEHOLDER_CRITERIA[len("acceptance_criteria:\n"):]
    block += "\n".join(open_lines) + ("\n" if open_lines else "")
    return text.replace(PLACEHOLDER_CRITERIA, block, 1)


def _as_package_seed(text, paths):
    """
    For a module inside a package, seed the whole top-level package and name
    the module by its dotted path, as the task file reference describes.

    A single-file seed copies only that file, so `from .util import clamp`
    failed in qikly's copy before any test ran on the user's code: the run
    was then green against code qikly had already changed, and could say
    nothing about where the code and the answers disagree. Found by running
    --start on a src/ layout.
    """
    from qikly import start_probe

    root = project_root(paths.module, paths.cwd)
    dotted = start_probe.dotted_name(paths.module, root)
    is_init = os.path.basename(paths.module) == "__init__.py"
    # A package's `__init__.py` is always seeded as its package: copied as a
    # lone file it would be a module called __init__ that nothing imports.
    if "." not in dotted and not is_init:
        return text
    # A package named like a standard-library module, `code` or `json`, is
    # refused by the run as a seed, but only after the paid test generation;
    # such a module stays a single-file seed, as it was before.
    if dotted.split(".")[0] in getattr(sys, "stdlib_module_names", ()):
        return text
    top = os.path.join(start_probe.import_base(paths.module, root), dotted.split(".")[0])
    seed = shown(top, paths.cwd).replace(os.sep, "/")
    text = re.sub(r'^(  module: )".*"$', lambda m: m.group(1) + _q(dotted), text,
                  count=1, flags=re.M)
    text = re.sub(r'^(  implementation: )".*"$', lambda m: m.group(1) + _q(seed),
                  text, count=1, flags=re.M)
    return text


def write_files(console, paths, state, quiet=False):
    """Write the task file, the data file and the open questions."""
    # Built before the file is opened, so a failure cannot leave it empty.
    text = task_text(paths, state)
    os.makedirs(os.path.dirname(paths.task), exist_ok=True)
    with open(paths.task, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    data = paths.data
    if state.get("sample"):
        ext = os.path.splitext(state["sample"])[1] or ".csv"
        data = data[:-len(".csv")] + ext
        os.makedirs(os.path.dirname(data), exist_ok=True)
        # The file already in place is used where it is: copied onto itself,
        # shutil raises.
        if os.path.normcase(os.path.abspath(state["sample"])) != \
                os.path.normcase(os.path.abspath(data)):
            shutil.copy2(state["sample"], data)
    elif state.get("rows"):
        os.makedirs(os.path.dirname(data), exist_ok=True)
        with open(data, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(state["columns"])
            writer.writerows(state["rows"])
    # The answers file is the person's own, and is never written over.
    return data


# --------------------------------------------------------- check and run ----

def _child_env(cwd):
    env = dict(os.environ)
    env["QIKLY_PROJECT_ROOT"] = cwd
    # Unbuffered, so the run's own header lines print before its stages
    # rather than after them, which is how the first-time user read them.
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def validate(console, paths):
    """`--validate` on the task, as a child, so it sees what a run will see."""
    done = subprocess.run([sys.executable, "-m", "qikly", "--validate",
                           "--tasks", paths.task_id], cwd=paths.cwd,
                          env=_child_env(paths.cwd), capture_output=True,
                          text=True, timeout=300, encoding="utf-8",
                          errors="replace")
    errors, warnings = [], []
    for line in (done.stdout or "").splitlines():
        found = re.match(r"^\s+(warn|ERROR|error)\s+(.*)$", line)
        if found:
            (warnings if found.group(1) == "warn" else errors).append(found.group(2))
    if done.returncode != 0 and not errors:
        # A crash prints no ERROR line, and reading only those reported a
        # task the run would refuse as ready.
        tail = [l for l in ((done.stderr or "") + (done.stdout or "")).splitlines()
                if l.strip()][-3:]
        errors.append("qikly --validate stopped with an error: "
                      + (" ".join(tail) or f"exit code {done.returncode}"))
    return errors, warnings


def provider():
    """(provider, model, key variable) or (None, None, the variables looked for)."""
    try:
        from qikly.agent_api.providers import router
        import importlib
        name = router._resolve_provider_name()
        found = [v for v in router._KEY_VARS.get(name, ()) if os.environ.get(v)]
        if os.environ.get("API_KEY"):
            found = found or ["API_KEY"]
        if not found:
            looked = sorted(set(v for vs in router._KEY_VARS.values() for v in vs))
            return None, None, looked
        module = importlib.import_module(router._PROVIDERS[name][0])
        model = os.environ.get("LLM_MODEL") or getattr(module, "DEFAULT_MODEL", None)
        return name, model, found[0]
    except Exception:
        return None, None, ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


def estimate(task_ids, model):
    try:
        from qikly import forecast
        projection = forecast.estimate(task_ids, model)
        if projection.get("cost_usd") is not None:
            return f"about ${projection['cost_usd']:.3f}"
    except Exception:
        pass
    return "a few cents at most"


def run(console, cwd, task_ids):
    """The paid run, streamed as it happens. Returns (converged, lines)."""
    from qikly.take_tests import keep_outputs_out_of_pytest
    keep_outputs_out_of_pytest(cwd)
    lines = []
    # One comma-separated argument: `--tasks A B` is an argparse error, and a
    # whole-folder run never started, then was reported as not green.
    process = subprocess.Popen([sys.executable, "-m", "qikly", "--tasks",
                                ",".join(task_ids)],
                               cwd=cwd, env=_child_env(cwd), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1,
                               encoding="utf-8", errors="replace")
    try:
        for line in process.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            console.say(line)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        raise
    return process.returncode == 0, lines


def _failed_tasks(lines, task_ids, converged):
    """
    Which tasks did not finish green. The run exits non-zero if any one task
    fails, and reading that alone reported every module in a folder as
    failed; its "Task(s) failed:" line names the ones that did.
    """
    if converged:
        return set()
    for line in reversed(lines):
        found = re.match(r"^Task\(s\) failed: (.+)$", line.strip())
        if found:
            return {t.strip() for t in found.group(1).split(",")}
    return set(task_ids)


_STAGE = re.compile(r"^\[(\w+)\].*\[stage ([12])/\d\] \[iteration 1\] (.*)$")
_COUNTS = re.compile(r"^(\d+)/(\d+) passed(?: \| FAILED: ?(.*))?$")


# A failure the run's line did not name: never dropped, never "agreement".
UNNAMED = "a failing test the run did not name"


def _bare(name):
    """
    A test as the run names it, without its parametrize id: `test_x` from
    `test_x[100]`, `TestLow::test_edge` kept whole, so same-named methods in
    two classes stay apart.
    """
    return name.strip().split("[")[0]


def _batched():
    try:
        from qikly.orchestrator.orchestrator import criteria_per_batch
        return criteria_per_batch() > 0
    except Exception:
        return False


def disagreements(paths, state, lines):
    """
    The answers whose tests failed against the user's code on first contact:
    each is a place the code and the person disagree. Read from the run's own
    lines and the `# Criteria: N` the test generator writes in each test.

    Only failures on the user's untouched code count. Stage 1's first
    iteration always runs on it; stage 2's does only if stage 1 needed no
    fix, because otherwise the code it ran was already qikly's patched copy.
    """
    failed, stage_one_clean = set(), None
    for line in lines:
        if (line.startswith(f"[{paths.task_id}]") and "[stage 1/" in line
                and "[iteration 1]" in line and "no test ran" in line):
            # Nothing ran on the user's code as it is: qikly's copy could not
            # be imported. "No failures" here is not agreement, and saying
            # "your code agrees" was the one false thing this report printed.
            return "unknown", {}, [r["criterion"] for r in state["answers"].values()
                                   if r["status"] == "answered"] + state.get("extra", []), [], {}
        found = _STAGE.match(line)
        if not found or found.group(1) != paths.task_id:
            continue
        counts = _COUNTS.match(found.group(3).strip())
        if counts:
            names = [_bare(n) for n in (counts.group(3) or "").split(",") if n.strip()]
            failing = int(counts.group(1)) < int(counts.group(2))
        else:
            # A line in another shape, such as "0 passed, 1 failed", still
            # says whether anything failed; unparsed, it read as clean.
            names = []
            failing = not re.search(r"\b0 failed\b|^\d+ passed$", found.group(3)) \
                and bool(re.search(r"fail|error", found.group(3), re.I))
        if failing and not names:
            names = [UNNAMED]
        if found.group(2) == "1":
            stage_one_clean = not failing
            failed.update(names)
        elif stage_one_clean:
            failed.update(names)
    criteria = [r["criterion"] for r in state["answers"].values()
                if r["status"] == "answered"] + state.get("extra", [])
    tests_for = {}
    if _batched():
        # Each batch numbers its criteria from 1, so a test's "Criteria: 2"
        # cannot be traced to one answer. Say nothing rather than misattribute.
        return None, {}, criteria, [], {}
    bodies, files = {}, {}
    for stage in ("integration", "system"):
        folder = os.path.join(paths.tests, stage)
        for name in (sorted(os.listdir(folder)) if os.path.isdir(folder) else []):
            if not name.endswith(".py"):
                continue
            source = _read(os.path.join(folder, name))
            for test, doc in _test_docstrings(source):
                bodies[test] = _test_body(source, test)
                files[test] = source
                # With or without "#", in the docstring or in a comment after
                # the body: the generator writes all of these, and a test
                # tagged "Criteria: 2" in its docstring was linked to nothing,
                # which turned a real disagreement into "your code agrees".
                numbers = _CRITERIA_TAG.search(doc + "\n" + _test_text(source, test))
                for n in re.findall(r"\d+", numbers.group(1) if numbers else ""):
                    tests_for.setdefault(int(n), []).append(test)
    # The tags are the test writer's own, and it sometimes tags a test with
    # answers it does not check: a free-shipping answer was listed against
    # two express-delivery tests. Where an answer names a call, only tests
    # that make that call are kept; if none does, the tags stand, marked.
    # Only tags that point at an answer count: "Criteria: 3" with two answers
    # tags nothing, and counting it hid that test's failure from both lists.
    tests_for = {n: names for n, names in tests_for.items() if 0 < n <= len(criteria)}
    tagged = {n: list(names) for n, names in tests_for.items()}
    unconfirmed = set()
    module_source = _read(paths.module)
    # A test that imports a name the module does not have fails before it
    # checks anything. validators' card.py was reported as disagreeing with
    # an answer its code met: the test imported ValidationError from card.py,
    # which takes it from another module, and the agent added the import.
    unchecked = {}
    for test in sorted(failed):
        missing = _missing_imports(bodies.get(test, ""), paths, module_source)
        if missing:
            unchecked[test] = missing
    failed -= set(unchecked)
    for n, names in tests_for.items():
        if not 0 < n <= len(criteria):
            continue
        call = _call_in(criteria[n - 1])
        if not call:
            continue
        kept = [t for t in names if _makes_call(bodies.get(t, ""), call, module_source,
                                                files.get(t), t)]
        if kept:
            tests_for[n] = kept
        else:
            unconfirmed.add(n)
    # A disagreement is a failing test tagged with the answer, whether or not
    # it makes the answer's exact call: the exact-call check only tidies the
    # list shown, and must never hide a failure.
    disagreed = [criteria[n - 1] for n, names in sorted(tagged.items())
                 if 0 < n <= len(criteria) and set(names) & failed]
    every_tagged = set(t for names in tagged.values() for t in names)
    untagged = sorted(failed - every_tagged)
    tests_for = {n: (names, n in unconfirmed) for n, names in tests_for.items()}
    return disagreed, tests_for, criteria, untagged, unchecked


def _missing_imports(body, paths, module_source):
    """
    The names a test imports from the user's module that the module does not
    define or import, read from the test's own `from ... import` lines.
    """
    import ast
    import textwrap
    try:
        tree = ast.parse(textwrap.dedent(body))
        module_tree = ast.parse(module_source)
    except SyntaxError:
        return []
    # Every name bound at module level, including under an `if`, `try`,
    # `with` or loop: counting only top-level statements took a function
    # defined under `if sys.version_info >= ...` as missing, and hid the one
    # failure that was a real disagreement.
    own = set()

    def bind(statements):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                own.add(node.name)
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                own.update((a.asname or a.name).split(".")[0] for a in node.names)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    own.add(sub.id)
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(node, field, None)
                if isinstance(inner, list):
                    bind(inner)
            for handler in getattr(node, "handlers", None) or []:
                bind(handler.body)

    bind(module_tree.body)
    # A name the module can serve without binding it: `from x import *` or a
    # module-level __getattr__. Nothing can be said for certain, so nothing is.
    if "__getattr__" in own or any(
            isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
            for n in ast.walk(module_tree)):
        return []
    if os.path.basename(paths.module) == "__init__.py":
        # A package also has its submodules: `from validators import card`.
        folder = os.path.dirname(os.path.abspath(paths.module))
        try:
            own.update(os.path.splitext(n)[0] for n in os.listdir(folder)
                       if n.endswith(".py") or os.path.isdir(os.path.join(folder, n)))
        except OSError:
            return []
    stem = os.path.splitext(os.path.basename(paths.module))[0]
    if stem == "__init__":
        stem = os.path.basename(os.path.dirname(paths.module))
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == stem:
            missing += [a.name for a in node.names if a.name not in own and a.name != "*"]
    return missing


_CRITERIA_TAG = re.compile(r"(?:#\s*)?Criteria:\s*([\d,\s]+)")


def _test_text(source, name):
    """
    A test's own lines: from its first decorator to its last statement, plus
    comment lines indented inside it that follow. Not the comment above the
    next test, which belongs to that test: sliced by "to the next def", a tag
    written above a test was read as the one before it.
    """
    lines = source.splitlines()
    for qualified, node in _test_nodes(source):
        if qualified != name:
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        end = node.end_lineno
        indent = len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())
        while end < len(lines):
            line = lines[end]
            stripped = line.strip()
            if stripped.startswith("#") and len(line) - len(line.lstrip()) > indent:
                end += 1
            elif not stripped and end + 1 < len(lines) and \
                    lines[end + 1].strip().startswith("#") and \
                    len(lines[end + 1]) - len(lines[end + 1].lstrip()) > indent:
                end += 1
            else:
                break
        return "\n".join(lines[start:end])
    return ""


def _test_body(source, name):
    import ast
    for qualified, node in _test_nodes(source):
        if qualified == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _makes_call(body, call, source=None, test_file=None, test=None):
    """
    Whether a test body makes exactly the call the answer names: the same
    values, and the same keyword arguments. Finding the values anywhere was
    not enough: `shipping_cost(50.0, 2, express=True)` holds both values of
    the free-shipping answer and tests something else. With the module's
    `source`, calls are compared by meaning, so `express=False` passed
    explicitly matches leaving it at its default. With the whole `test_file`
    and the `test`'s name, every parametrize row counts: the body alone has
    neither the decorators nor the tables the rows are kept in.
    """
    import ast
    function, args, kwargs = call
    found_sig = so.signature(source, function) if source else None
    defaults = so.literal_defaults(source, function) if source else {}

    def meaning(a, k):
        if not found_sig:
            return list(a), dict(k)
        named = dict(zip(found_sig[0], a))
        named.update(k)
        return {n: v for n, v in named.items()
                if not (n in defaults and defaults[n] == v)}

    wanted = meaning(args, kwargs)
    scope = None
    if test_file and test:
        try:
            tree = ast.parse(test_file)
        except SyntaxError:
            tree = None
        parts = test.split("[")[0].split("::")
        scope = tree
        # Down the named classes first: TestB::test_x is not the first
        # test_x in the file, which named the wrong test's calls.
        for part in parts[:-1]:
            scope = next((n for n in ast.walk(scope) if isinstance(n, ast.ClassDef)
                          and n.name == part), None) if scope else None
        scope = next((n for n in ast.walk(scope) if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == parts[-1]), None) \
            if scope else None
    if scope is None:
        try:
            tree = ast.parse(body)
        except SyntaxError:
            return False
        scope = tree
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute) else None)
        if name != function:
            continue
        # A value passed through a name, `word = "mousetrap"` then
        # `pluralize(word)`, is the same call: read literally, all three of
        # inflection's answers were marked as made by no test.
        for row in range(so._rows_for(tree, node)):
            known = so._literals_around(tree, node, row)
            try:
                found_args = [so._value(a, known) for a in node.args]
                found_kwargs = {k.arg: so._value(k.value, known) for k in node.keywords}
            except (ValueError, SyntaxError, TypeError):
                continue
            if meaning(found_args, found_kwargs) == wanted:
                return True
    return False


def _test_nodes(source):
    """(qualified name, node) for each test, `Class::name` inside a class."""
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name.startswith("test_"):
            out.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        item.name.startswith("test_"):
                    out.append((f"{node.name}::{item.name}", item))
    return out


def _test_docstrings(source):
    """
    (test name, docstring) for each test function, read with ast. A pattern
    missed every test with a return annotation, `-> None`, which is how the
    generator often writes them, and reported a real disagreement as none.
    """
    import ast
    return [(name, ast.get_docstring(node) or "") for name, node in _test_nodes(source)]


def _newest(folder, prefix=""):
    try:
        names = [n for n in os.listdir(folder) if n.startswith(prefix)]
    except OSError:
        return None
    if not names:
        return None
    return max((os.path.join(folder, n) for n in names), key=os.path.getmtime)


def report_result(console, paths, state, lines, converged):
    disagreed, tests_for, criteria, untagged, unchecked = disagreements(paths, state, lines)
    # Answers no test checked: none tagged with them, or every one tagged
    # failed on an import before it checked anything.
    not_checked = [n for n in range(1, len(criteria) + 1)
                   if not tests_for.get(n, ([], False))[0]
                   or all(t in unchecked for t in tests_for[n][0])]
    if disagreed and disagreed not in (None, "unknown"):
        not_checked = [n for n in not_checked if criteria[n - 1] not in disagreed]
    console.say("")
    name = os.path.basename(paths.module)
    started = any(line.startswith(f"[{paths.task_id}] [stage ") for line in lines)
    if not converged and not started:
        tail = [l for l in lines if l.strip()][-3:]
        console.say(f"The run for {name} did not start, so nothing was tested. "
                    f"What it printed last: " + (" | ".join(tail) or "nothing"))
        return
    if not converged:
        # The third cause is the one cachetools hit: the test called the
        # library with the wrong arguments, and eleven patches could not help.
        console.say(f"The run for {name} did not finish green: some tests "
                    f"written from your answers still fail. That can be a "
                    f"disagreement qikly could not fix in its copy, an answer "
                    f"that contradicts another, or a test written wrongly from "
                    f"your answer, which no change to the code can fix. The "
                    f"step-by-step report shows the failing test.")
    elif disagreed == "unknown":
        console.say(f"The run for {name} finished green, but qikly could not run "
                    f"your code as it is: its copy of {name} failed to import at "
                    f"first, usually over a relative import, and was fixed before "
                    f"any test ran. So it cannot say where your code and your "
                    f"answers disagree. The step-by-step report shows each step.")
        return
    elif disagreed is None:
        console.say(f"The run for {name} finished green. Criteria were sent to "
                    f"the test writer in batches (criteria_per_batch in your "
                    f"settings), so which answer each failure came from cannot "
                    f"be told apart; the step-by-step report shows the failures.")
    elif disagreed or untagged:
        if disagreed:
            console.say("Your code disagrees with your only answer:" if len(criteria) == 1
                        else f"Your code disagrees with {len(disagreed)} of your "
                             f"{len(criteria)} answers:")
            for c in disagreed:
                console.say(f"  - {c}")
        if untagged:
            # A failure on the user's own code is never hidden because the
            # test did not say which answer it came from.
            console.say(("Also failed on your code as it is, without saying which "
                         "answer it was written from:" if disagreed else
                         "Some tests failed on your code as it is, without saying "
                         "which answer they were written from:"))
            for t in untagged:
                console.say(f"  - {t}")
            # Not a verdict on the code: on semantic_version both were the
            # test writer misreading the API, and the copy was bent to fit.
            # Said only of tests the run named: of an unnamed failure qikly
            # cannot say even that.
            if untagged == [UNNAMED]:
                console.say("  qikly could not tell which test failed; the "
                            "step-by-step report has the run's own output.")
            else:
                console.say("  These are the test writer's own reading of your code or "
                            "requirements, which can be wrong. Check each before "
                            "changing anything.")
        patches = _newest(os.path.join(paths.cwd, "outputs", "logs", "patches",
                                       paths.task_id))
        # A run's patches sit in a folder per run; name the diff itself.
        if patches and os.path.isdir(patches):
            patches = _newest(patches) or patches
        console.say(f"qikly changed its copy to make them pass, not your file "
                    f"{name}. Read the change before taking any of it: it can "
                    f"change behaviour your answers never mentioned.")
        if patches:
            console.say(f"  The change: {paths.rel(patches)}")
    else:
        # Agreement is claimed only for an answer a test checked: one whose
        # every test failed on an import, or that no test is tagged with, was
        # counted as agreeing with code nothing had compared it to.
        checked = [c for n, c in enumerate(criteria, 1) if n not in not_checked]
        if not checked:
            console.say("No test that ran on your code checked any of your answers, "
                        "so qikly cannot say whether your code agrees with them.")
        elif not not_checked:
            console.say(("Your code agrees with your answer. " if len(criteria) == 1 else
                         f"Your code agrees with all {len(criteria)} of your answers. ")
                        + "The new tests now pin that behaviour, so a later change "
                          "that breaks one of them will fail.")
        else:
            console.say(f"Your code agrees with {len(checked)} of your "
                        f"{len(criteria)} answers, the ones a test checked. The new "
                        f"tests now pin that behaviour.")
    if not_checked and disagreed not in (None, "unknown"):
        console.say("Not checked by any test that ran on your code:")
        for n in not_checked:
            console.say(f"  - {criteria[n - 1]}")
    if unchecked:
        console.say(f"Not counted either way: these failed because they import "
                    f"something {name} does not have, so they say nothing about "
                    f"your code:")
        for test, missing in unchecked.items():
            console.say(f"  - {test}  imports {', '.join(missing)}")
    if tests_for:
        console.say("Each answer and the tests written from it:")
        for n, (names, unconfirmed) in sorted(tests_for.items()):
            if 0 < n <= len(criteria):
                console.say(f"  {criteria[n - 1]}  ->  {', '.join(names)}"
                            + ("  (tagged by the test writer; none makes this "
                               "exact call)" if unconfirmed else ""))


# --------------------------------------------------------------- the block --

def inputs_outputs(console, cwd, code, tests, report, results, ran, copied=()):
    console.say("")
    console.say("  INPUTS (read, not changed)")
    console.say(f"    Your code      {shown(code, cwd)}")
    if is_placeholder(tests, cwd):
        console.say("    Your tests     none yet, so qikly scored a placeholder of its "
                    f"own: {shown(tests, cwd)}")
    else:
        console.say(f"    Your tests     {shown(tests, cwd)}")
    for paths, state, data in results:
        # The person's own file: read, never written over.
        if os.path.exists(paths.open):
            console.say(f"    Your answers   {paths.rel(paths.open)}")
    console.say("  SAVED BY THIS COMMAND")
    if report:
        console.say(f"    Score report   {shown(report, cwd)}")
    for paths, state, data in results:
        # Criteria, counted as the task file holds them: answers plus the
        # rules added at the summary, which the old count left out.
        answered = sum(1 for r in state["answers"].values() if r["status"] == "answered")
        answered += len(state.get("extra", []))
        open_n = sum(1 for r in state["answers"].values() if r["status"] in (so.ASK, so.SKIP))
        console.say(f"    Task file      {paths.rel(paths.task)}   {answered} "
                    f"criteri{'on' if answered == 1 else 'a'}"
                    + (f", {open_n} open question{'' if open_n == 1 else 's'}"
                       if open_n else ""))
        if data and os.path.exists(data):
            rows = state.get("rows")
            console.say(f"    Example data   {paths.rel(data)}"
                        + (f"   {len(rows)} row{'' if len(rows) == 1 else 's'}" if rows else ""))
        console.say(f"    Progress       {paths.rel(paths.state)}")
    if ran:
        console.say("  WRITTEN BY THE RUN")
        for paths, state, data in results:
            if os.path.isdir(paths.tests):
                console.say(f"    New tests      {paths.rel(paths.tests)}{os.sep}")
            copy = os.path.join(cwd, "outputs", "agent_src", "code", paths.task_id)
            if os.path.isdir(copy):
                console.say(f"    qikly's copy   {shown(copy, cwd)}{os.sep}   "
                            f"your code, as qikly ran and fixed it")
            iterations = _newest(os.path.join(cwd, "outputs", "reports", "iterations"),
                                 paths.task_id + "_")
            if iterations:
                console.say(f"    What happened  {shown(iterations, cwd)}")
        if os.path.isdir(os.path.join(cwd, "outputs", "logs")):
            console.say(f"    Logs, patches  {shown(os.path.join(cwd, 'outputs', 'logs'), cwd)}{os.sep}")
        if os.path.isdir(os.path.join(cwd, "outputs", "reports")):
            console.say(f"    Other reports  {shown(os.path.join(cwd, 'outputs', 'reports'), cwd)}{os.sep}   "
                        f"metrics, JUnit XML, run summaries")
        conftest = os.path.join(cwd, "outputs", "conftest.py")
        if os.path.exists(conftest):
            console.say(f"    pytest guard   {shown(conftest, cwd)}   keeps a plain pytest "
                        f"out of outputs{os.sep}")
        ids = ",".join(p.task_id for p, _, _ in results)
        console.say(f"    Their score    free:  qikly --score-suite --tasks {ids}")
    if copied:
        console.say("  COPIED INTO YOUR TESTS")
        for path in copied:
            if os.path.basename(path).startswith("test_"):
                console.say(f"    {shown(path, cwd)}")
        others = sum(1 for p in copied if not os.path.basename(p).startswith("test_"))
        if others:
            console.say(f"    and {others} supporting files beside them (conftest.py, "
                        f"__init__.py)")
    console.say("")
    console.say(f"  Everything above is under {cwd}.")


# -------------------------------------------------------------------- flow --


def offer_run(console, cwd, task_ids, again):
    while True:
        name, model, key = provider()
        lead = ["The run writes tests from your answers and checks your code "
                "against them, on a copy. It needs an API key."]
        if name:
            lead.append(f"Key found: {key}, so the model is {model}, "
                        f"{estimate(task_ids, model)} (estimated from a static "
                        f"price table, not your bill).")
            picked = choose(console, [
                "run it now",
                f"not now (to run it later:  {again})",
                "use a different provider: type gemini, openai or anthropic",
            ], lead=lead)
            if picked == 1:
                return True
            if picked == 2:
                return False
            chosen = free_text(console, "Type gemini, openai or anthropic",
                               "openai").lower()
            if chosen not in ("gemini", "openai", "anthropic"):
                console.say(f"\"{chosen}\" is not one of gemini, openai or "
                            f"anthropic.")
                continue
            os.environ["LLM_PROVIDER"] = chosen
            continue
        lead.append("No key was found. qikly looked for: " + ", ".join(key) + ".")
        picked = choose(console, [
            "show me how to get a free key",
            f"not now (to run it later:  {again})",
            "I have set one in another window: type its variable name to check",
        ], lead=lead)
        if picked == 1:
            console.say("Gemini's free tier needs no card. The steps: "
                        "https://github.com/gal-a/qikly/blob/main/docs/PROVIDER_KEY_SETUP.md")
            console.say("Set the key in this terminal, for example in PowerShell:  "
                        "$env:GEMINI_API_KEY = \"...\"   then run this command again.")
            return False
        if picked == 2:
            return False
        var = free_text(console, "Type the variable's name", "GEMINI_API_KEY")
        value = os.environ.get(var)
        if not value:
            try:
                import winreg  # noqa: F401
                value = _user_env(var)
            except ImportError:
                value = None
        if value:
            os.environ[var] = value
            console.say(f"  found {var}.")
        else:
            console.say(f"{var} is not set where qikly can see it. A variable set "
                        f"in another window reaches new windows only.")


def _user_env(var):
    """A user-level variable on Windows, set after this terminal opened."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, var)[0]
    except OSError:
        return None


def main(arg, cwd, console=None, answers=None, tests=None):
    console = console or Console()
    try:
        return _main(arg, cwd, console, answers, tests)
    except (Stop, KeyboardInterrupt):
        console.say("")
        if os.path.isdir(os.path.join(cwd, "inputs_private", "questions")):
            console.say("Stopped. Every answer you gave is saved, in the task file "
                        "under " + os.path.join("inputs_private", "config", "tasks")
                        + " and the progress file under "
                        + os.path.join("inputs_private", "questions")
                        + ". Run the same command again to continue where you stopped.")
        else:
            console.say("Stopped before any answer was given, so nothing is saved "
                        "yet. Run the same command again to start.")
        return STOPPED


def _scored(console, code, tests, cwd, session, quiet=False):
    """
    (result, report), from the saved score when neither the code nor the tests
    changed since it was taken. Re-scoring each run took twenty seconds a time
    and left a report behind on every one; the first-time user had eighteen.
    """
    stamp = fingerprint(code, tests)
    saved = session.get("score")
    if (saved and saved.get("fingerprint") == stamp
            and session.get("tests") == shown(tests, cwd)
            and os.path.exists(os.path.join(cwd, saved.get("report", "")))):
        if not quiet:
            console.say("Your code and tests have not changed since the last "
                        "score, so it is reused.")
        return saved["result"], os.path.join(cwd, saved["report"])
    result, report = score(console, code, tests, cwd, os.path.isdir(code))
    if result is None:
        return None, report
    keep = {"total": result["total"], "caught": result["caught"],
            "missed": result["missed"], "questions": result.get("questions") or []}
    session.update(tests=shown(tests, cwd),
                   score={"fingerprint": stamp, "report": shown(report, cwd),
                          "result": keep})
    save_session(cwd, code, session)
    return keep, report


def _say_score(console, result, report, cwd, questions):
    total, caught = result["total"], len(result["caught"])
    console.say("")
    console.say(f"  {caught} of {total} planted faults caught by your tests")
    console.say(f"  {total - caught} of {total} missed, which come down to "
                f"{len(questions)} question{'' if len(questions) == 1 else 's'}")
    console.say(f"  The full report: {shown(report, cwd)}")


def _modules(questions, code, cwd, session):
    """Questions by module, each module with its task name, in a stable order."""
    by_module = {}
    for q in questions:
        by_module.setdefault(q["path"], []).append(q)
    names = task_bases(sorted(by_module), code)
    renamed = session.get("names") or {}
    for module in by_module:
        rel = shown(module, cwd)
        if rel in renamed:
            names[module] = renamed[rel]
    return [(m, by_module[m], names[m]) for m in sorted(by_module)]


def _test_sources(tests):
    return [_read(p) for p in ([tests] if os.path.isfile(tests) else _test_files(tests))]


def _one_module(code):
    """
    A folder holding one module is that module, as pick_code makes it in a
    terminal. Without this, `--start inflection` scored the folder with no
    terminal and the module in one, so a file of answers given to the first
    met different questions in the second.
    """
    if os.path.isdir(code):
        modules = modules_in(code)
        if len(modules) == 1:
            return modules[0]
    return code


def _main(arg, cwd, console, answers, given_tests=None):
    """
    Without `answers`: score the code and write the questions file, the one
    place a person answers. With them: read that file, check the task, and in
    a terminal offer the run, its report and the copy home.

    The questions used to be asked one at a time in the terminal. That flow
    is shelved, on the branch shelved/interactive-questions: it was easy to
    get lost in, a mistake felt final, and on real libraries nearly every
    question needed the code read anyway.
    """
    if not answers:
        return write_questions(arg, cwd, console, given_tests)
    code = _one_module(os.path.abspath(os.path.join(cwd, arg or ".")))
    if not os.path.exists(code):
        console.say(f"There is no file or folder at {code}.")
        return 2
    if not os.path.isfile(answers if os.path.isabs(answers)
                          else os.path.join(cwd, answers)):
        console.say(f"There is no answers file at {answers}. Write it with  "
                    f"qikly --questions {score_questions_pasteable(code, cwd)}")
        return 2
    session = load_session(cwd, code)
    saved = session.get("tests")
    # The tests the questions were asked against, not a fresh guess: a
    # different suite asks different questions, and answers matched by
    # number then landed on the wrong one.
    tests = (os.path.abspath(os.path.join(cwd, given_tests)) if given_tests
             else os.path.abspath(os.path.join(cwd, saved))
             if saved and os.path.exists(os.path.join(cwd, saved))
             else auto_tests(code, cwd))
    if not tests:
        console.say("No test files that import it were found. Name them with  "
                    "--score-tests <file or folder>.")
        return 2
    result, report = _scored(console, code, tests, cwd, session, quiet=True)
    if result is None:
        return 2
    questions = group(enrich(list(result.get("questions") or []), result["missed"]))
    test_sources = _test_sources(tests)
    root = project_root(code, cwd)
    results, blocked, skipped = [], False, set()
    file_module = parse_answers(answers)[3]
    for module, qs, base in _modules(questions, code, cwd, session) or \
            [(code, [], Paths(cwd, code).base)]:
        paths = Paths(cwd, module, base)
        if file_module and file_module != shown(module, cwd):
            # One module's answers never land on another module's questions.
            continue
        problem = _cannot_task(paths)
        if problem:
            console.say(f"{shown(module, cwd)} is skipped: {problem}")
            skipped.add(shown(module, cwd))
            continue
        if not _existing_task(console, paths):
            blocked = True
            continue
        state, data = _from_answers(console, paths, qs, test_sources, root, answers)
        results.append((paths, state, data))
    if file_module and not results and file_module not in skipped:
        console.say(f"{shown(answers, cwd)} is about {file_module}, which "
                    f"{shown(code, cwd)} does not hold.")
        return 2
    if not results:
        return 2 if blocked else 0
    again = _answers_command(code, answers, cwd)
    ready, refused = [], False
    for paths, state, data in results:
        errors, warnings = validate(console, paths)
        console.say("")
        criteria = sum(1 for r in state["answers"].values()
                       if r.get("status") == "answered") + len(state.get("extra", []))
        if not criteria:
            # Every question left blank leaves the template's TODO as the
            # only criterion, which --validate only warns about, and a run
            # went ahead testing a placeholder.
            refused = True
            console.say(f"{paths.task_id} has no answers yet, so there is nothing "
                        f"to test your code against. Answer at least one question "
                        f"in {shown(answers, cwd)}, or add a rule: line, then run  "
                        f"{again}")
            continue
        if errors:
            refused = True
            console.say(f"{paths.task_id} cannot run yet:")
            for e in errors:
                console.say(f"  - {e}")
            console.say(f"Fix it in {shown(answers, cwd)}, then run  {again}")
            continue
        if warnings:
            console.say(f"Checked {paths.task_id}, with {len(warnings)} warning"
                        f"{'' if len(warnings) == 1 else 's'}. Each is a reason a "
                        f"test may check less than you meant; none stops the run:")
            for w in warnings:
                console.say(f"  - {w}")
            if any("restates a criterion" in w for w in warnings):
                # The check compares words, so a purpose sentence about the
                # same topic as a longer answer can trip it. Said plainly, so
                # a first-time user can judge it rather than fear it.
                console.say("  That check compares words, so a sentence about the "
                            "same topic can trip it. It matters only if your "
                            "requirements line says what an answer says, such as a "
                            "boundary value; if it does, reword it and run again.")
        else:
            console.say(f"Checked {paths.task_id}: ready to run.")
        ready.append(paths.task_id)
    ran, failed, copied = False, False, []
    if ready and console.interactive:
        if offer_run(console, cwd, ready, again):
            converged, lines = run(console, cwd, ready)
            ran, failed = True, not converged
            not_green = _failed_tasks(lines, ready, converged)
            for paths, state, data in results:
                if paths.task_id in ready:
                    report_result(console, paths, state, lines,
                                  paths.task_id not in not_green)
            home = [t for t in ready if t not in not_green]
            if home:
                try:
                    copied = offer_take_home(
                        console, cwd, home,
                        tests if os.path.isdir(tests) else os.path.dirname(tests))
                except Stop:
                    # The run has finished; stopping here only skips the copy,
                    # and the audit below still says what was written.
                    console.say("")
                    console.say(f"Not copied. The run itself has finished. Later:  "
                                f"qikly --take-tests {','.join(home)}")
    elif ready:
        # No terminal: an assistant or a script. The same command in a
        # terminal runs it and reports; these do the two halves by hand.
        console.say(f"Ready. To run it, which needs an API key, run  {again}  in a "
                    f"terminal; it shows where your code disagrees with your "
                    f"answers and offers to copy the new tests into yours. "
                    f"Without a terminal:  qikly --tasks {','.join(ready)}  then  "
                    f"qikly --take-tests {','.join(ready)}")
    inputs_outputs(console, cwd, code, tests, report, results, ran, copied)
    if failed:
        return 1
    return 2 if refused and not ready else 0


def _has_answers(path):
    """Whether a questions file already holds something a person wrote."""
    if not os.path.isfile(path):
        return False
    given, requirements, rows, _, _ = parse_answers(path)
    return bool(given or requirements or parse_rules(path))


def _answers_command(code, answers_file, cwd):
    """
    The step 3 command: `qikly --answers pricing.py` for one module, which
    finds its own file, and the file itself for a module of a folder.
    """
    if os.path.isfile(code):
        return f"qikly --answers {score_questions_pasteable(code, cwd)}"
    return f"qikly --answers {score_questions_pasteable(answers_file, cwd)}"


def answers_file_for(code, cwd):
    """
    The answers files --questions wrote about `code`: found by the module:
    line each file carries, so a module scored as part of a folder is found
    from its own path too. One path when there is exactly one with answers in
    it, else the list of those that hold answers.
    """
    import glob
    target = os.path.normcase(_one_module(os.path.abspath(code)))
    folder = target if os.path.isdir(target) else None
    files = []
    for f in sorted(glob.glob(os.path.join(cwd, "inputs_private", "questions",
                                           "*_open_questions.txt"))):
        module = _field(f, "module")
        if not module:
            continue
        where = os.path.normcase(os.path.abspath(os.path.join(cwd, module)))
        if where == target or (folder and where.startswith(folder + os.sep)):
            files.append(f)
    # For a folder, only the files someone has answered; one module's file is
    # found answered or not, so --answers can say what is missing from it.
    if folder:
        files = [f for f in files if _has_answers(f)]
    return files[0] if len(files) == 1 else files


def write_questions(arg, cwd, console, given_tests=None):
    """
    Score the code and write the questions file: what the module does, the
    questions qikly can offer answers for, rules of the person's own, and
    example inputs. Only questions with answers to choose from go in. On real
    libraries nearly every other question needed the code read; a person who
    knows a rule writes it as a rule: line instead.
    """
    if not arg:
        console.say("Name the code to test, such as  qikly --questions pricing.py  or  "
                    "qikly --questions my_project_folder")
        return 2
    code = _one_module(os.path.abspath(os.path.join(cwd, arg)))
    if not os.path.exists(code):
        console.say(f"There is no file or folder at {code}.")
        return 2
    root = project_root(code, cwd)
    session = load_session(cwd, code)
    saved = session.get("tests")
    tests = (os.path.abspath(os.path.join(cwd, given_tests)) if given_tests
             else os.path.abspath(os.path.join(cwd, saved))
             if saved and os.path.exists(os.path.join(cwd, saved))
             else auto_tests(code, cwd))
    if given_tests and not os.path.exists(tests):
        console.say(f"There is no test file or folder at {tests}.")
        return 2
    if not tests:
        console.say("No test files that import it were found (test_*.py or "
                    "*_test.py, searched from the project root). Name them with  "
                    f"qikly --questions {score_questions_pasteable(code, cwd)} "
                    f"--score-tests <file or folder>")
        return 2
    console.say(f"Scoring against {shown(tests, cwd)}. To use other tests, add "
                f"--score-tests <file or folder>.")
    result, report = _scored(console, code, tests, cwd, session)
    if result is None:
        return 2
    questions = group(enrich(list(result.get("questions") or []), result["missed"]))
    _say_score(console, result, report, cwd, questions)
    test_sources = _test_sources(tests)
    modules = _modules(questions, code, cwd, session)
    if not modules and os.path.isfile(code):
        # Nothing missed is no reason to stop: rules of your own still make a
        # suite, and the file is where they go.
        modules = [(code, [], None)]
    written = []
    for module, qs, base in modules:
        paths = Paths(cwd, module, base)
        again = _answers_command(code, paths.open, cwd)
        source = _read(module)
        sharp, others = sharp_questions(qs, source, test_sources, root)
        # A file already answered is refreshed, never lost: every answer
        # whose question is still asked is carried over by its id, with the
        # requirements, rules and rows, and the old file is kept beside it.
        carried, dropped, old = {}, [], None
        if _has_answers(paths.open):
            given, req, old_rows, _, old_ids = parse_answers(paths.open)
            old = {"requirements": req or "", "rules": parse_rules(paths.open),
                   "rows": old_rows}
            current = {e["id"] for e in sharp}
            for n, text in given.items():
                fid = (old_ids.get(n) or "").split(" ")[0]
                if fid in current:
                    carried[fid] = text
                else:
                    dropped.append(n)
            shutil.copy2(paths.open, paths.open + ".bak")
        name = os.path.basename(module)
        lines = [f"# Your answers for {name}, from qikly --questions.",
                 "#",
                 "# Fill in this file, save it, then run:",
                 f"#   {again}",
                 "# That checks your answers, offers the run (it needs an API key),",
                 "# shows where your code disagrees with you, and offers to copy the",
                 "# new tests into your own tests. Change anything here and run it again.",
                 "# Keep the id lines: they tie each answer to its question.",
                 "",
                 f"module: {shown(module, cwd)}",
                 f"scored: {score_questions_pasteable(code, cwd)}",
                 "",
                 f"# 1. What {name} should do, in one sentence. The coding agent is",
                 "#    told this, so give its purpose, not its rules or boundary values.",
                 "requirements: " + (old["requirements"] if old else ""),
                 ""]
        if sharp:
            lines += [f"# 2. Questions your tests leave open, {len(sharp)} of them. qikly ran",
                      "#    your code to find each choice. Answer with the option's number",
                      "#    after the Q, or leave it blank to skip it. An option that asks",
                      "#    for a value takes the number, a colon and the value:  Q1: 2: 100.0",
                      ""]
            for n, entry in enumerate(sharp, 1):
                q, group_ = entry["group"][0], entry["group"]
                lines.append(f"# Q{n}. {where(q)}")
                # The code itself: with only "line 143" to go on, an answer
                # about slugify's separator check was written about the
                # max_length check two lines above it.
                lines += ["#" + line for line in _context(source, q.get("line"))]
                lines.append(f"# {entry['prompt']}")
                for i, o in enumerate(entry["options"], 1):
                    if o["kind"] != so.OWN:
                        lines.append(f"#   {i}. {o['label']}")
                if len(group_) > 1:
                    lines.append(f"#   (This answer also covers {len(group_) - 1} more "
                                 f"place{'s' if len(group_) > 2 else ''} your tests "
                                 f"leave open on the same call.)")
                lines += [f"# id {entry['id']}", f"Q{n}: {carried.get(entry['id'], '')}", ""]
        else:
            lines += ["# 2. Questions: none with answers qikly could work out by running",
                      "#    your code. Write what you know as rules, below.", ""]
        lines += ["# 3. Rules of your own, optional, one per line, each naming a value:",
                  "#      rule: apply_discount(100, 0) returns 100.0",
                  "#      rule: label(' VIP ') returns 'gold'"]
        if others:
            lines += [f"#    {others} more place{'s' if others != 1 else ''} your tests "
                      f"leave open need{'' if others != 1 else 's'} someone who knows",
                      f"#    the code; the score report lists "
                      f"{'them' if others != 1 else 'it'}: {shown(report, cwd)}"
                      if report else "#    the score report lists them."]
        lines += ["rule: " + r for r in (old["rules"] if old else [])] or ["rule: "]
        lines.append("")
        from qikly.scaffold import starter_columns
        columns = starter_columns(source)
        if columns:
            built = build_rows({"answers": {}, "extra": []}, columns, source, test_sources)
            # A value with a line break cannot sit on one line.
            built = [r for r in built if not any("\n" in v or "\r" in v for v in r)]
            if old and old["rows"]:
                built = [list(r) for r in old["rows"]]
            lines += ["# 4. Example inputs the run tries the code on, one row per line,",
                      "#    the values in this order:  " + ", ".join(columns),
                      "#    qikly filled in the rows it could build from your tests"
                      + ("." if built else "; none could be built, so add at least one.")]
            lines += ["row: " + _csv_line(r) for r in built] or ["row: "]
            lines.append("")
        elif columns is None:
            lines += [f"# 4. {name} works on files, so the run needs a real sample one.",
                      "#    Copy a small real file of the kind it reads to",
                      f"#      {shown(paths.data, cwd)}",
                      "#    before you run the command above.", ""]
        os.makedirs(os.path.dirname(paths.open), exist_ok=True)
        with open(paths.open, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines))
        written.append((paths.open, again))
        console.say("")
        console.say(f"{shown(module, cwd)}: {len(sharp)} question"
                    f"{'' if len(sharp) == 1 else 's'} with answers to choose from"
                    + (f"; {others} more need{'s' if others == 1 else ''} someone who "
                       f"knows the code, listed in the score report" if others else "")
                    + ".")
        if old:
            console.say(f"  The file already held your answers: refreshed, with "
                        f"{len(carried)} answer{'' if len(carried) == 1 else 's'} carried "
                        f"over"
                        + (f" and {len(dropped)} about questions no longer asked left "
                           f"out" if dropped else "")
                        + f". The previous file is kept as {shown(paths.open + '.bak', cwd)}.")
    console.say("")
    if not written:
        # A folder where nothing was missed has no file to point to.
        console.say("No questions to answer. To add rules of your own for one "
                    "module, run  qikly --questions <that module>.py")
        return 0
    console.say("Next, step 2: answer in the file, then run the command under it.")
    for path, command in written:
        console.say(f"  {shown(path, cwd)}")
        console.say(f"    then:  {command}")
    return NEEDS_ANSWERS


def parse_rules(path):
    """The `rule: ...` lines of an answers file, the person's own criteria."""
    rules = []
    for line in _read(path).splitlines():
        found = re.match(r"^\s*rule\s*:\s*(.*)$", line, re.I)
        if found and found.group(1).strip():
            rules.append(_UNSAFE.sub("", found.group(1)).strip())
    return rules


def _existing_task(console, paths):
    """A task file this command did not write is never overwritten."""
    if not os.path.exists(paths.task) or os.path.exists(paths.state):
        return True
    console.say(f"{paths.rel(paths.task)} already exists, and qikly did "
                f"not write it, so it is left alone. Move it aside, then run the "
                f"command again.")
    return False


def offer_take_home(console, cwd, task_ids, test_dir):
    """After a green run: copy the new tests into the user's own tests."""
    from qikly import take_tests

    target = os.path.join(test_dir, take_tests.FOLDER)
    console.say("")
    picked = choose(console, [
        f"copy the new tests into {shown(target, cwd)}{os.sep}, importing your "
        f"own code, and run them on it",
        f"not now (later:  qikly --take-tests {','.join(task_ids)})",
        "type a different tests folder to copy them into",
    ], lead=["The new tests import qikly's copy of your code. Copied into your "
             "own tests, they import your module instead."])
    if picked == 2:
        return []
    if picked == 3:
        raw = free_text(console, "Type the folder to copy them into",
                        "tests" + os.sep + "generated")
        test_dir = os.path.abspath(os.path.join(cwd, raw.strip('"')))
        os.makedirs(test_dir, exist_ok=True)
    copied = []
    for task_id in task_ids:
        written, result = take_tests.take(cwd, task_id, test_dir, say=console.say)
        if written:
            take_tests.report(console.say, cwd, written, result, task_id)
            copied += written
        else:
            console.say(f"Nothing copied for {task_id}: {result}.")
    return copied


def _cannot_task(paths):
    """Why no task can be written for this module, before anything is asked."""
    from qikly import start_probe
    from qikly.scaffold import build_task
    if os.path.basename(paths.module) == "__init__.py":
        root = project_root(paths.module, paths.cwd)
        if start_probe.dotted_name(paths.module, root) == "__init__":
            # Run from inside the package, its __init__.py has no package name
            # to be imported by, and the task named a module "__init__".
            pkg = os.path.dirname(os.path.abspath(paths.module))
            return (f"it is the package {os.path.basename(pkg)} itself, run from "
                    f"inside it. Run the command from the folder above: cd .. "
                    f"then qikly --questions {os.path.basename(pkg)}")
    _, problem = build_task(paths.module, paths.cwd, task_id=paths.base,
                            seed="existing")
    return problem


# --------------------------------------------------- without a terminal ----


def parse_answers(path):
    """
    (answers by number, requirements, rows, module, ids by number) from a
    file: `Q3: text` lines, each optionally after a `# id <key>` line,
    `requirements: text`, `row: a, b, c` and `module: path`.
    """
    found, requirements, rows, module, ids = {}, None, [], None, {}
    pending_id, seen = None, set()
    for line in _read(path).splitlines():
        marker = re.match(r"^\s*#\s*id\s+([0-9a-f]{6,}(?:\s+[0-9a-f]{6,})*)\s*$", line)
        if marker:
            pending_id = marker.group(1)
            continue
        if line.lstrip().startswith("#"):
            continue
        q = re.match(r"^\s*Q(\d+)\s*:\s*(.*)$", line)
        if q:
            n = int(q.group(1))
            if n in seen and pending_id:
                # A number already used, which a file edited by hand can
                # have: kept apart under a number of its own, so the id it
                # carries still matches its own answer, not the first Q<n>'s.
                n = -len(seen) - 1
            seen.add(n)
            if pending_id:
                ids[n] = pending_id
            pending_id = None
            if q.group(2).strip():
                found[n] = _UNSAFE.sub("", q.group(2)).strip()
            continue
        r = re.match(r"^\s*requirements\s*:\s*(.*)$", line, re.I)
        if r and r.group(1).strip():
            requirements = _UNSAFE.sub("", r.group(1)).strip()
        m = re.match(r"^\s*module\s*:\s*(.*)$", line, re.I)
        if m and m.group(1).strip():
            module = m.group(1).strip()
        row = re.match(r"^\s*row\s*:\s*(.*)$", line, re.I)
        if row and row.group(1).strip():
            rows.append(next(csv.reader([row.group(1)], skipinitialspace=True)))
    return found, requirements, rows, module, ids


def _csv_line(values):
    """
    One row as `--answers` reads it back: quoted where a value has a comma,
    and every value quoted when one starts or ends with a space, which the
    reader would otherwise drop.
    """
    out = io.StringIO()
    spaced = any(v != v.strip() for v in values)
    csv.writer(out, lineterminator="",
               quoting=csv.QUOTE_ALL if spaced else csv.QUOTE_MINIMAL).writerow(values)
    return out.getvalue()


def sharp_questions(questions, source, test_sources, root):
    """
    (entries, others): the questions the file shows, and how many it leaves
    out for having no choice to offer. Each entry is one question as the file
    shows it, with the planted faults that led to the same call and choices
    grouped under it, and an id made from that call and those choices, not
    from a line number. An id tied to the line lost every answer when a line
    was added above it, and one tied to the scoring scope lost them all for a
    module in a subfolder. The writer and the reader both build this list, so
    a file's numbers and ids always mean the same questions.
    """
    entries, by_mark, others = [], {}, 0
    for q in questions:
        prompt, options = so.menu(q, source, test_sources, root, q.get("mutant"))
        if not prompt:
            others += 1
            continue
        mark = (re.sub(r"\bline \d+", "line", prompt),
                sorted(json.dumps(o.get("pins"), sort_keys=True)
                       for o in options if o["kind"] == so.BEHAVIOUR))
        text = json.dumps(mark)
        if text in by_mark:
            by_mark[text]["group"].append(q)
            continue
        entry = {"id": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
                 "prompt": prompt, "options": options, "group": [q]}
        by_mark[text] = entry
        entries.append(entry)
    return entries, others


def _interpret(console, n, text, options):
    """The record fields for answer `text` to file question Q`n`."""
    if not text:
        return {"status": so.SKIP, "deferred": True}
    if text.lower() in ("skip", "either", "ask"):
        return {"status": {"skip": so.SKIP, "either": so.EITHER, "ask": so.ASK}[text.lower()]}
    if re.match(r"^\d+\s*[.):]?\s*(?::\s*(.+))?$", text) and \
            int(re.match(r"^\d+", text).group(0)) <= 9:
        # An option number, alone or as "1: 0.0" for an option that asks for
        # a value. Numbers above 9 are answers, not options.
        k = int(re.match(r"^\d+", text).group(0))
        value = re.match(r"^\d+\s*[.)]?\s*:\s*(.+)$", text)
        value = value.group(1).strip() if value else None
        if not 1 <= k <= len(options) or options[k - 1]["kind"] == so.OWN:
            console.say(f"Q{n}: there is no option {k}; it is left open.")
            return {"status": so.SKIP}
        o = options[k - 1]
        if o["kind"] == so.BEHAVIOUR and o["pins"].get("returns", "") is None \
                and value is None:
            console.say(f"Q{n}: option {k} needs a value; write it as {k}: <value>. "
                        f"It is left open.")
            return {"status": so.SKIP}
        if o["kind"] == so.BEHAVIOUR:
            return {"status": "answered", "criterion": so.criterion(o, value),
                    "function": o["function"], "args": o["args"],
                    "kwargs": o.get("kwargs") or {}}
        return {"status": o["kind"]}
    if len(text.split()) < 3:
        console.say(f"Q{n}: \"{text}\" is too short to be a criterion; write the "
                    f"input and what should happen to it. It is left open.")
        return {"status": so.SKIP}
    return {"status": "answered", "criterion": text}


def _from_answers(console, paths, questions, test_sources, root, answers_path):
    """
    The task, built from the answers file alone, every time. Built on top of
    what an earlier run saved, a blanked answer stayed in the task and a
    changed one did not change.
    """
    from qikly.scaffold import starter_columns

    given, requirements, rows, _, ids = parse_answers(answers_path)
    source = _read(paths.module)
    state = {"answers": {}, "extra": parse_rules(answers_path)}
    if requirements:
        state["requirements"] = requirements
    else:
        console.say(f"{shown(answers_path, paths.cwd)} has no requirements: line, "
                    f"so the coding agent would not be told what the module "
                    f"does. Add one, such as  requirements: applies a discount.")
    entries, _ = sharp_questions(questions, source, test_sources, root)
    by_id = {e["id"]: e for e in entries}
    numbers = sorted(set(given) | set(ids))
    unmatched = []
    for n in numbers:
        if ids:
            entry = by_id.get((ids.get(n) or "").split(" ")[0])
            if entry is None:
                if given.get(n):
                    unmatched.append(n)
                continue
        else:
            # A file whose id lines were deleted: by position, in the same
            # order the file was written in.
            if not 1 <= n <= len(entries):
                continue
            entry = entries[n - 1]
        fields = _interpret(console, n, given.get(n), entry["options"])
        first, rest = entry["group"][0], entry["group"][1:]
        state["answers"][_key(first)] = dict(
            fields, question=first["question"], where=where(first), number=n,
            key=_key(first))
        for q in rest:
            # The same call and the same choices: one criterion is enough,
            # and it is not written into the task twice.
            same = {"status": "covered", "by": _key(first)} \
                if fields["status"] == "answered" else dict(fields)
            state["answers"][_key(q)] = dict(same, question=q["question"],
                                             where=where(q), key=_key(q))
    for q in questions:
        # Every question the file does not answer stays open in the task.
        state["answers"].setdefault(_key(q), {
            "question": q["question"], "where": where(q), "key": _key(q),
            "status": so.SKIP, "deferred": True})
    if unmatched:
        console.say(f"{', '.join('Q%d' % n for n in unmatched)} in "
                    f"{shown(answers_path, paths.cwd)} "
                    f"{'is' if len(unmatched) == 1 else 'are'} about questions your "
                    f"code no longer raises: it or its tests changed since the file "
                    f"was written, so {'it is' if len(unmatched) == 1 else 'they are'} "
                    f"left out. To refresh the file and keep the answers that still "
                    f"apply, run  qikly --questions {_scope_of(answers_path, paths)}")
    columns = starter_columns(source)
    if columns == []:
        state["rows"], state["columns"], state["rows_typed"] = [["none"]], ["input"], False
    elif rows and columns:
        # The file's rows, plus a row for each answer's own call: the file is
        # filled in from the tests before anything is answered, so an answer
        # such as apply_discount(7, 0.5) had no row of its own.
        given_rows = [r for r in rows if len(r) == len(columns)]
        answered = build_rows(state, columns, source, [])
        state["rows"] = given_rows + [r for r in answered if r not in given_rows]
        state["columns"] = columns
        state["rows_typed"] = True
    elif columns:
        state["rows"] = build_rows(state, columns, source, test_sources)
        state["columns"] = columns
    elif columns is None and not os.path.exists(paths.data):
        console.say(f"{os.path.basename(paths.module)} reads files, so it needs a "
                    f"real sample file: copy a small real one to "
                    f"{paths.rel(paths.data)}.")
    if columns and not state.get("rows"):
        console.say(f"{shown(answers_path, paths.cwd)} gives no example inputs. Add "
                    f"at least one line  row: <values>  with the values in this "
                    f"order: {', '.join(columns)}")
    save_state(paths, state)
    data = write_files(console, paths, state)
    console.say(f"saved to {paths.rel(paths.task)}"
                + (f" and {paths.rel(data)}" if os.path.exists(data) else ""))
    return state, data


def _field(path, name):
    """The value of a `name:` line in an answers file, or None."""
    for line in _read(path).splitlines():
        found = re.match(r"^\s*%s\s*:\s*(.*)$" % re.escape(name), line, re.I)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return None


def _scope_of(answers_path, paths):
    """What --questions was given when it wrote the file: its scored: line."""
    return _field(answers_path, "scored") or shown(paths.module, paths.cwd)
