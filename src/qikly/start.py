"""
`qikly --start [PATH]`: from the tests you have to a suite written from your
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


def free_text(console, what, example=None, value=False):
    """
    A line of text, never empty. `what` says what kind of text is wanted.
    `value` marks a prompt whose answer may well be a bare number, such as
    "what should it return", where checking for a mistyped menu choice would
    only get in the way.
    """
    prompt = what + (f", such as {example}" if example else "") + \
        ". Then press Enter:"
    while True:
        raw = console.ask(prompt)
        if raw.lower() in _QUIT:
            raise Stop()
        if not value and raw and raw.rstrip(".)").isdigit() and len(raw) <= 3:
            # A bare small number where words were asked for is almost always
            # a menu choice typed one prompt too late.
            console.say(f"You typed only \"{raw}\", which looks like a menu "
                        f"number, but this prompt wants words.")
            for number, label in enumerate([f"keep \"{raw}\" as it is",
                                            "type it again"], 1):
                console.say(f"  {number}. {label}")
            again = console.ask("Type a number from 1 to 2, then press Enter:")
            while again.rstrip(".)") not in ("1", "2"):
                if again.lower() in _QUIT:
                    raise Stop()
                console.say("Please type 1 or 2.")
                again = console.ask("Type a number from 1 to 2, then press Enter:")
            if again.rstrip(".)") == "1":
                return raw
            continue
        if raw:
            return raw
        console.say("Nothing was typed. Please type it, or press Ctrl+C to "
                    "stop; your answers so far are saved.")


def _names_a_value(text):
    return bool(re.search(r"\d|'[^']+'|\"[^\"]+\"|\bTrue\b|\bFalse\b|\bNone\b",
                          text))


def own_answer(console, example):
    """
    A typed criterion. One that names no value gets a follow-up, because a
    test needs a value to check, and "rates must be sensible" becomes a test
    at whatever rate the generator happens to pick.
    """
    text = free_text(console, "Type your answer in plain words, naming a value",
                     f'"{example}"')
    # A criterion of one word is never a rule, and a bare "1" kept as one
    # made the run refuse the task: it appears elsewhere in the file, so it
    # cannot be withheld.
    while len(text.split()) < 3:
        console.say("A criterion needs a few words: the input, and what should "
                    "happen to it.")
        text = free_text(console, "Type your answer in plain words, naming a value",
                         f'"{example}"')
    while not _names_a_value(text):
        picked = choose(console, [
            "add a value to it",
            "keep it as it is",
            "type it again",
        ], lead=["That answer names no value, and a test needs one to check."])
        if picked == 1:
            text = text + " " + free_text(console, "Type the value to add",
                                          '"at exactly 100"')
        elif picked == 2:
            break
        else:
            text = free_text(console, "Type your answer again, naming a value",
                             f'"{example}"')
    return text


def ask_rows(console, columns, example=None):
    """Rows typed as comma-separated values, one per line, until an empty line."""
    rows = []
    console.say(f"Type one row at a time, as values for {', '.join(columns)} "
                f"separated by commas.")
    shown_example = ", ".join(example) if example else \
        ", ".join(f"<{c}>" for c in columns)
    while True:
        prompt = ("Type a row, such as  " + shown_example
                  + "  then press Enter" + ("; an empty line when you are done:"
                                            if rows else ":"))
        raw = console.ask(prompt)
        if raw.lower() in _QUIT:
            raise Stop()
        if not raw:
            if rows:
                return rows
            console.say("At least one row is needed. Please type a row.")
            continue
        values = next(csv.reader([raw], skipinitialspace=True))
        if len(values) != len(columns):
            console.say(f"That row has {len(values)} value"
                        f"{'' if len(values) == 1 else 's'}, and "
                        f"{', '.join(columns)} needs {len(columns)}. Please "
                        f"type it again.")
            continue
        rows.append(values)
        console.say(f"  row {len(rows)} kept.")


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
    return (name.endswith(".py") and name not in ("__init__.py", "conftest.py",
                                                  "setup.py")
            and not name.startswith("test_") and not name.endswith("_test.py"))


def _is_test(name):
    return name.endswith(".py") and (name.startswith("test_")
                                     or name.endswith("_test.py"))


def modules_in(folder):
    """The modules under a folder, tests and tooling left out, sorted."""
    out = []
    for here, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS
                         and not d.startswith("."))
        out += [os.path.join(here, n) for n in sorted(names) if _is_module(n)]
    return out


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


def _imports(source, stem):
    return re.search(r"^\s*(?:from\s+[\w.]*\b%s\b|import\s+[\w.]*\b%s\b)"
                     % (re.escape(stem), re.escape(stem)), source, re.M)


def _count_tests(paths):
    return sum(len(re.findall(r"^\s*(?:async\s+)?def test_", _read(p), re.M))
               for p in paths)


def shown(path, base):
    """A path relative to `base` when it is inside it, else in full."""
    try:
        rel = os.path.relpath(path, base)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def pick_code(console, arg, cwd):
    """The first question: what to test, a module or a folder of them."""
    if arg:
        path = os.path.abspath(os.path.join(cwd, arg))
        if os.path.isfile(path):
            return path
        if not os.path.isdir(path):
            console.say(f"There is no file or folder at {path}.")
            return _typed_path(console, cwd, "the module or folder to test",
                               want_code=True)
        modules = modules_in(path)
        if not modules:
            console.say(f"{shown(path, cwd)} holds no Python modules to test.")
            return _typed_path(console, cwd, "the module or folder to test",
                               want_code=True)
        if len(modules) == 1:
            return modules[0]
        options = [f"the whole folder {shown(path, cwd)}: {len(modules)} "
                   f"modules, one task each"]
        listed = modules[:8]
        options += [f"only {shown(m, cwd)}" for m in listed]
        options.append("type a path to another module or folder")
        picked = choose(console, options, lead=["What do you want to test?"])
        if picked == 1:
            return path
        if picked <= 1 + len(listed):
            return listed[picked - 2]
        return _typed_path(console, cwd, "the module or folder to test",
                           want_code=True)
    here = [p for p in sorted(os.listdir(cwd)) if _is_module(p)
            and os.path.isfile(os.path.join(cwd, p))]
    folders = [d for d in sorted(os.listdir(cwd))
               if os.path.isdir(os.path.join(cwd, d)) and d not in _SKIP_DIRS
               and not d.startswith(".") and modules_in(os.path.join(cwd, d))]
    options, targets = [], []
    for name in here[:6]:
        options.append(f"{name}")
        targets.append(os.path.join(cwd, name))
    for name in folders[:4]:
        count = len(modules_in(os.path.join(cwd, name)))
        options.append(f"the folder {name}{os.sep}: {count} module"
                       f"{'' if count == 1 else 's'}, one task each")
        targets.append(os.path.join(cwd, name))
    options.append("type a path to a module or folder")
    picked = choose(console, options, lead=[
        "What do you want to test? A single module, or a folder of them."])
    if picked <= len(targets):
        return targets[picked - 1]
    return _typed_path(console, cwd, "the module or folder to test", want_code=True)


def _typed_path(console, cwd, what, want_code=False):
    example = ("pricing.py or src" + os.sep + "shop" if want_code
               else "tests or tests" + os.sep + "test_pricing.py")
    while True:
        raw = free_text(console, f"Type the path to {what}", example)
        path = os.path.abspath(os.path.join(cwd, raw.strip('"').strip("'")))
        if os.path.isfile(path) or (os.path.isdir(path) and
                                    (not want_code or modules_in(path))):
            return path
        if os.path.isdir(path):
            console.say(f"{path} holds no Python modules. Please type another path.")
        else:
            console.say(f"There is no file or folder at {path}. Please type the "
                        f"path again.")


def auto_tests(code, cwd=None):
    """The tests to use without asking: the files that import the code."""
    root = project_root(code, cwd)
    stems = ([os.path.splitext(os.path.basename(code))[0]] if os.path.isfile(code)
             else [os.path.splitext(os.path.basename(m))[0] for m in modules_in(code)])
    found = [f for f in _test_files(root) if any(_imports(_read(f), s) for s in stems)]
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    folders = set(os.path.dirname(f) for f in found)
    return folders.pop() if len(folders) == 1 else os.path.commonpath(found)


def pick_tests(console, code, cwd):
    """The second question: which tests to score it against."""
    root = project_root(code, cwd)
    stems = ([os.path.splitext(os.path.basename(code))[0]] if os.path.isfile(code)
             else [os.path.splitext(os.path.basename(m))[0]
                   for m in modules_in(code)])
    files = _test_files(root)
    importing = [f for f in files if any(_imports(_read(f), s) for s in stems)]
    options, targets = [], []
    for f in importing[:5]:
        options.append(f"{shown(f, cwd)}  imports "
                       f"{'it' if len(stems) == 1 else 'some of them'}, "
                       f"{_count_tests([f])} tests")
        targets.append(f)
    folders = sorted(set(os.path.dirname(f) for f in importing or files))
    for d in folders[:3]:
        inside = [f for f in files if f.startswith(d + os.sep)
                  or os.path.dirname(f) == d]
        options.append(f"{shown(d, cwd) or '.'}{os.sep}  every test file in it, "
                       f"{_count_tests(inside)} tests")
        targets.append(d)
    options.append("type a path to a test file or folder")
    what = (os.path.basename(code) if os.path.isfile(code)
            else shown(code, cwd) + os.sep)
    lead = [f"Which tests should {what} be scored against?"]
    if not targets:
        # One option is no choice: say what was searched and ask for the path.
        console.say(lead[0])
        console.say(f"No test files (test_*.py or *_test.py) were found under "
                    f"{root}.")
        return _typed_path(console, cwd, "a test file or folder")
    picked = choose(console, options, lead=lead)
    if picked <= len(targets):
        return targets[picked - 1]
    return _typed_path(console, cwd, "a test file or folder")


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
                    advice=[f"Next: `qikly --start {again}` asks these one at "
                            f"a time and saves your answers."])
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


def score_questions_pasteable(path, cwd=None):
    """A path to print in a command: relative, forward slashes, quoted if spaced."""
    from qikly import score_questions
    return score_questions._pasteable(shown(path, cwd or os.getcwd()))


def _pytest_tail(tests, cwd, lines=12):
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q",
                               "-p", "no:cacheprovider", tests],
                              cwd=cwd, capture_output=True, text=True, timeout=300)
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


# -------------------------------------------------------------- one module --

def _context(source, line):
    lines = (source or "").splitlines()
    out = []
    for n in range(max(1, (line or 0) - 1), min(len(lines), (line or 0) + 1) + 1):
        out.append(f"  {'>' if n == line else ' '} {n:4d} {lines[n - 1]}")
    return out


def _example(question, test_sources):
    function = question.get("function") or "your_function"
    calls = so.literal_calls(test_sources, function)
    shown_call = so.call_text(function, calls[0][0], calls[0][1]) if calls else \
        f"{function}(...)"
    return f"{shown_call} returns ..."


def ask_requirements(console, paths, source, state):
    import ast
    try:
        doc = ast.get_docstring(ast.parse(source))
    except SyntaxError:
        doc = None
    name = os.path.basename(paths.module)
    lead = [f"What should {name} do? The coding agent is told this, so describe "
            f"its purpose, not its boundary values."]
    if not doc:
        # One option is no choice: ask for the text straight away.
        for line in lead:
            console.say(line)
        state["requirements"] = free_text(
            console, "Type what it does, in a sentence or two",
            "\"applies a percentage discount to a price\"")
        return
    first = " ".join(doc.split())[:120]
    picked = choose(console, [f"use its docstring: \"{first}\"",
                              "type a sentence or two"], lead=lead)
    if picked == 1:
        state["requirements"] = " ".join(doc.split())
    else:
        state["requirements"] = free_text(
            console, "Type what it does, in a sentence or two",
            "\"applies a percentage discount to a price\"")


def where(q):
    """
    "apply_discount, line 3", or "shipping.py, top level, line 6" for a line
    outside any function, which used to read "None, line 6".
    """
    if q.get("function"):
        return f"{q['function']}, line {q.get('line')}"
    name = os.path.basename(q.get("path") or q.get("file") or "the module")
    return f"{name}, top level, line {q.get('line')}"


def ask_question(console, number, total, q, source, test_sources, root,
                 same_line=False):
    """One question. Returns the record saved for it."""
    where_ = where(q)
    console.say("")
    console.say(f"Question {number} of {total}: {where_}"
                + ("  (another question about the same line)" if same_line else ""))
    for line in _context(source, q.get("line")):
        console.say(line)
    prompt, options = so.menu(q, source, test_sources, root, q.get("mutant"))
    if prompt:
        # The concrete question replaces the general one's last sentence,
        # which asked the same thing in the abstract.
        found = re.match(r"^(.*?[.])\s+[^.]*\?$", q["question"])
        console.say(found.group(1) if found else q["question"])
    else:
        console.say(q["question"])
    lead = [prompt] if prompt else []
    picked = options[choose(console, [o["label"] for o in options], lead=lead) - 1]
    record = {"question": q["question"], "where": where_, "status": picked["kind"],
              "key": _key(q)}
    if picked["kind"] == so.BEHAVIOUR:
        value = None
        if picked["pins"].get("returns", "") is None:
            value = free_text(console, f"Type what {picked['call']} should "
                                       f"return, as Python would show it",
                              picked["pins"].get("like"), value=True)
        record.update(status="answered", criterion=so.criterion(picked, value),
                      function=picked["function"], args=picked["args"],
                      kwargs=picked.get("kwargs") or {})
    elif picked["kind"] == so.OWN:
        record.update(status="answered",
                      criterion=own_answer(console, _example(q, test_sources)))
    return record


def summary(console, paths, state, questions_by_key, example="f(1) returns 2"):
    """The answers, with a chance to change one or add another rule."""
    while True:
        console.say("")
        console.say(f"Your answers, saved in {paths.rel(paths.task)}:")
        rows = []
        for key, rec in state["answers"].items():
            rows.append((key, rec))
            n = len(rows)
            # "answer N", not "N.": the menu below is numbered too, and two
            # lists both starting at 1 read as one.
            if rec["status"] == "answered":
                console.say(f"    answer {n}: {rec['criterion']}")
            elif rec["status"] == so.EITHER:
                console.say(f"    answer {n}: either is fine ({rec['where']})")
            elif rec["status"] == so.ASK:
                console.say(f"    answer {n}: saved for later ({rec['where']})")
            else:
                console.say(f"    answer {n}: skipped for now ({rec['where']})")
        for extra in state.get("extra", []):
            rows.append((None, extra))
            console.say(f"    answer {len(rows)}: {extra}")
        console.say("What next?")
        picked = choose(console, [
            "these are right, continue",
            "change one of them",
            "add something else that must be true, which my tests could not "
            "have asked about",
        ])
        if picked == 1:
            return
        if picked == 2:
            if not rows:
                console.say("There are no answers to change yet.")
                continue
            which = _number(console, len(rows), "the answer to change "
                                                 "(the N in \"answer N\")")
            key, rec = rows[which - 1]
            if key is None:
                state["extra"].remove(rec)
                state["extra"].append(own_answer(console, rec))
            else:
                yield key
        else:
            # The example comes from this module's own calls: a fixed one
            # named a function the user's module does not have.
            state.setdefault("extra", []).append(own_answer(console, example))
            yield None


def _number(console, count, what):
    while True:
        raw = console.ask(f"Type the number of {what}, from 1 to {count}, then "
                          f"press Enter:")
        if raw.lower() in _QUIT:
            raise Stop()
        if raw.rstrip(".)").isdigit() and 1 <= int(raw.rstrip(".)")) <= count:
            return int(raw.rstrip(".)"))
        console.say(f"Please type a number from 1 to {count}.")


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


def ask_data(console, paths, state, source, test_sources):
    from qikly.scaffold import starter_columns

    columns = starter_columns(source)
    if columns == []:
        # Functions that take no arguments need no example inputs; a run
        # still needs a data file to exist, so a one-row placeholder is
        # written and said to be one.
        console.say("")
        console.say(f"{os.path.basename(paths.module)}'s functions take no "
                    f"arguments, so no example inputs are needed.")
        state["rows"], state["columns"], state["rows_typed"] = [["none"]], ["input"], False
        return
    if columns is None:
        console.say("")
        console.say(f"{os.path.basename(paths.module)} works on files rather "
                    f"than values, so the example data is a real file of that "
                    f"kind.")
        while True:
            raw = free_text(console, "Type the path of a small real sample "
                            "file. It is copied, not moved", "data/sample.csv")
            sample = os.path.abspath(os.path.join(paths.cwd, raw.strip('"')))
            if os.path.isfile(sample):
                state["sample"] = sample
                state["rows"] = None
                return
            console.say(f"There is no file at {sample}. Please type the path again.")
    built = build_rows(state, columns, source, test_sources)
    console.say("")
    # Why a value-taking module needs a data file at all, and what a row is:
    # the first-time user asked both, and whether to write True or true.
    lead = [f"{os.path.basename(paths.module)}'s functions take "
            f"{', '.join(columns)}. The run tries the code on a few example "
            f"inputs, one row each, with a value for every one of those, "
            f"written as Python would write it (True, not true)."]
    if built:
        lead.append("Built from your answers and your tests:")
        lead += ["    " + ", ".join(r) for r in built]
        picked = choose(console, ["use these rows", "type rows of my own instead"],
                        lead=lead)
        if picked == 1:
            state["rows"], state["columns"] = built, columns
            state["rows_typed"] = False
            return
    else:
        for line in lead:
            console.say(line)
    state["rows"], state["columns"] = ask_rows(
        console, columns, built[0] if built else None), columns
    state["rows_typed"] = True


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
                   ", written from its owner's answers by qikly --start."))
    text = re.sub(r'^description: ".*"$', lambda m: description, text, count=1,
                  flags=re.M)
    text = re.sub(r"  # TODO: what it does, e\.g\. reads one CSV and returns its rows",
                  "", text)
    text = text.replace("  # guessed, check this", "")
    text = _as_package_seed(text, paths)
    # The template's section headings address someone filling it in by
    # hand; here every section is already filled.
    text = text.replace("# Generated by `qikly scaffold`. Two sections need you.",
                        "# Written by `qikly --start` from your answers. Run it "
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
    if "." not in dotted:
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
        shutil.copy2(state["sample"], data)
    elif state.get("rows"):
        os.makedirs(os.path.dirname(data), exist_ok=True)
        with open(data, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(state["columns"])
            writer.writerows(state["rows"])
    write_open_questions(paths, state)
    return data


def write_open_questions(paths, state):
    open_recs = [r for r in state["answers"].values()
                 if r["status"] in (so.ASK, so.SKIP)]
    if not open_recs:
        if os.path.exists(paths.open):
            os.remove(paths.open)
        return None
    os.makedirs(os.path.dirname(paths.open), exist_ok=True)
    name = os.path.basename(paths.module)
    lines = [f"# Questions about {name} that are still open.",
             "# Write an answer after each Q number, in plain words naming a",
             "# value, then give the file back with",
             f"#   qikly --start {score_questions_pasteable(paths.module, paths.cwd)} "
             f"--answers {score_questions_pasteable(paths.open, paths.cwd)}",
             "",
             f"module: {shown(paths.module, paths.cwd)}",
             ""]
    # Each keeps its question's own number and its id, which is what
    # --answers matches on, so an answer lands on its own question even if a
    # later score asks them in a different order.
    for n, rec in enumerate(open_recs, 1):
        lines += [f"# {rec['where']}: {rec['question']}",
                  f"# id {rec.get('key', '')}",
                  f"Q{rec.get('number', n)}: ", ""]
    with open(paths.open, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return paths.open


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
    lines = []
    process = subprocess.Popen([sys.executable, "-m", "qikly", "--tasks"] + task_ids,
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


_STAGE = re.compile(r"^\[(\w+)\].*\[stage ([12])/\d\] \[iteration 1\] (\d+)/(\d+) passed"
                    r"(?: \| FAILED: (.+))?$")


def _bare(name):
    """`test_x` from `test_x[100]` or `TestLabel::test_x`, as pytest names them."""
    return name.strip().split("::")[-1].split("[")[0]


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
                                   if r["status"] == "answered"] + state.get("extra", [])
        found = _STAGE.match(line)
        if not found or found.group(1) != paths.task_id:
            continue
        names = [_bare(n) for n in (found.group(5) or "").split(",") if n.strip()]
        if found.group(2) == "1":
            stage_one_clean = not names
            failed.update(names)
        elif stage_one_clean:
            failed.update(names)
    criteria = [r["criterion"] for r in state["answers"].values()
                if r["status"] == "answered"] + state.get("extra", [])
    tests_for = {}
    if _batched():
        # Each batch numbers its criteria from 1, so a test's "Criteria: 2"
        # cannot be traced to one answer. Say nothing rather than misattribute.
        return None, {}, criteria
    for stage in ("integration", "system"):
        folder = os.path.join(paths.tests, stage)
        for name in (sorted(os.listdir(folder)) if os.path.isdir(folder) else []):
            if not name.endswith(".py"):
                continue
            for test, doc in _test_docstrings(_read(os.path.join(folder, name))):
                numbers = re.search(r"#\s*Criteria:\s*([\d,\s]+)", doc)
                for n in re.findall(r"\d+", numbers.group(1) if numbers else ""):
                    tests_for.setdefault(int(n), []).append(test)
    disagreed = [criteria[n - 1] for n, names in sorted(tests_for.items())
                 if 0 < n <= len(criteria) and set(names) & failed]
    return disagreed, tests_for, criteria


def _test_docstrings(source):
    """
    (test name, docstring) for each test function, read with ast. A pattern
    missed every test with a return annotation, `-> None`, which is how the
    generator often writes them, and reported a real disagreement as none.
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [(node.name, ast.get_docstring(node) or "")
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")]


def _newest(folder, prefix=""):
    try:
        names = [n for n in os.listdir(folder) if n.startswith(prefix)]
    except OSError:
        return None
    if not names:
        return None
    return max((os.path.join(folder, n) for n in names), key=os.path.getmtime)


def report_result(console, paths, state, lines, converged):
    disagreed, tests_for, criteria = disagreements(paths, state, lines)
    console.say("")
    name = os.path.basename(paths.module)
    if not converged:
        console.say(f"The run for {name} did not finish green: some tests "
                    f"written from your answers still fail. That can be a "
                    f"disagreement qikly could not fix in its copy, or an "
                    f"answer that contradicts another. The step-by-step report "
                    f"says which.")
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
    elif disagreed:
        console.say("Your code disagrees with your only answer:" if len(criteria) == 1
                    else f"Your code disagrees with {len(disagreed)} of your "
                         f"{len(criteria)} answers:")
        for c in disagreed:
            console.say(f"  - {c}")
        patches = _newest(os.path.join(paths.cwd, "outputs", "logs", "patches",
                                       paths.task_id))
        # A run's patches sit in a folder per run; name the diff itself.
        if patches and os.path.isdir(patches):
            patches = _newest(patches) or patches
        console.say(f"qikly fixed this in a copy, not in your file {name}.")
        if patches:
            console.say(f"  The fix: {paths.rel(patches)}")
    else:
        console.say(("Your code agrees with your answer. " if len(criteria) == 1 else
                     f"Your code agrees with all {len(criteria)} of your answers. ")
                    + "The new tests now pin that behaviour, so a later change "
                      "that breaks one of them will fail.")
    if tests_for:
        console.say("Each answer and the test written from it:")
        for n, names in sorted(tests_for.items()):
            if 0 < n <= len(criteria):
                console.say(f"  {criteria[n - 1]}  ->  {', '.join(names)}")


# --------------------------------------------------------------- the block --

def inputs_outputs(console, cwd, code, tests, report, results, ran):
    console.say("")
    console.say("  INPUTS (read, not changed)")
    console.say(f"    Your code      {shown(code, cwd)}")
    console.say(f"    Your tests     {shown(tests, cwd)}")
    console.say("  SAVED BY THIS COMMAND")
    if report:
        console.say(f"    Score report   {shown(report, cwd)}")
    for paths, state, data in results:
        # Criteria, counted as the task file holds them: answers plus the
        # rules added at the summary, which the old count left out.
        answered = sum(1 for r in state["answers"].values() if r["status"] == "answered")
        answered += len(state.get("extra", []))
        open_n = sum(1 for r in state["answers"].values() if r["status"] in (so.ASK, so.SKIP))
        console.say(f"    Your answers   {paths.rel(paths.task)}   {answered} "
                    f"criteri{'on' if answered == 1 else 'a'}"
                    + (f", {open_n} open question{'' if open_n == 1 else 's'}"
                       if open_n else ""))
        if os.path.exists(paths.open):
            console.say(f"    Open questions {paths.rel(paths.open)}")
        if data and os.path.exists(data):
            rows = state.get("rows")
            console.say(f"    Example data   {paths.rel(data)}"
                        + (f"   {len(rows)} rows" if rows else ""))
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
        ids = " ".join(p.task_id for p, _, _ in results)
        console.say(f"    Their score    free:  qikly --score-suite --tasks {ids}")
    console.say("")
    console.say(f"  Everything above is under {cwd}.")


# -------------------------------------------------------------------- flow --

def announce(console, cwd, code):
    what = os.path.basename(code) if os.path.isfile(code) else shown(code, cwd) + os.sep
    console.say("")
    console.say(f"This scores the tests you already have, asks you a few questions "
                f"about what {what} should do, and saves your answers. Nothing "
                f"of yours is changed: your code and your tests are only read.")
    console.say("")
    console.say(f"It writes into {cwd}:")
    console.say("  qikly-suite-score" + os.sep + "     the score report")
    console.say("  inputs_private" + os.sep + "        your answers, example data and progress")
    console.say("  outputs" + os.sep + "               the new tests and reports, only if you run them")
    console.say("")
    console.say("You can stop at any time with Ctrl+C. Answers are saved as you go, "
                "and running the same command again continues where you stopped.")
    console.say("")


def start_probe_timeout():
    from qikly import start_probe
    return start_probe.TIMEOUT


def _rule_example(questions, test_sources):
    """An example rule built from this module's own functions and test calls."""
    for q in questions:
        if q.get("function"):
            calls = so.literal_calls(test_sources, q["function"])
            if calls:
                return so.call_text(q["function"], *calls[0]) + " returns ..."
            return f"{q['function']}(...) returns ..."
    return "a call to one of your functions, and what it should return"


def module_flow(console, paths, questions, test_sources, root, answers_file=None):
    """Questions, summary and data for one module. Returns its state."""
    source = _read(paths.module)
    state = load_state(paths) or {}
    state.setdefault("answers", {})
    state.setdefault("extra", [])
    keys = [_key(q) for q in questions]
    by_key = dict(zip(keys, questions))
    # Answers to questions this score no longer asks are dropped: the code or
    # the tests changed, and an answer to a question nobody asked is noise.
    state["answers"] = {k: v for k, v in state["answers"].items() if k in by_key}
    pending = [k for k in keys if k not in state["answers"]]
    if (state["answers"] or state.get("requirements")) and console.interactive:
        # Shown on every return, so it is never a surprise. Deleting answers
        # sits behind its own confirmation: a first-time user piping answers
        # a few at a time typed the next question's "2" here, which wiped
        # every answer, and the rest then landed one question off.
        done = len(state["answers"]) + (1 if state.get("requirements") else 0)
        complete = not pending and _complete(paths)
        handled = len(state["answers"])
        answered = sum(1 for r in state["answers"].values() if r.get("status") == "answered")
        lead = [f"Saved for {os.path.basename(paths.module)}: "
                + ("what it does, and " if state.get("requirements") else "")
                + f"{handled} of {len(keys)} questions ({answered} answered, "
                  f"{handled - answered} skipped, left open or either-is-fine)"
                + ("." if not pending else
                   f". {len(pending)} still to go.")]
        if complete:
            options = ["go straight to the check and the run"]
        elif pending:
            options = [f"continue with question {keys.index(pending[0]) + 1}"]
        else:
            # Every question answered, but stopped before the rows were saved.
            options = ["continue to the summary and the example inputs"]
        options += ["review my answers first",
                    "delete my answers and start again (asks to confirm)",
                    "type the number of one question to answer again"]
        picked = choose(console, options, lead=lead)
        if picked == 1 and complete:
            return state, write_files(console, paths, state)
        if picked == 2:
            pending = []
        elif picked == 3:
            sure = choose(console, [
                f"no, keep my {done} answers",
                f"yes, delete all {done} answers and start again",
                "type the number of one question to answer again instead",
            ], lead=[f"Delete all {done} saved answers about "
                     f"{os.path.basename(paths.module)}? This cannot be undone."])
            if sure == 2:
                state["answers"], state["extra"] = {}, []
                state.pop("requirements", None)
                pending = list(keys)
                save_state(paths, state)
                console.say("  deleted. Starting again.")
            elif sure == 3:
                which = _number(console, len(keys), "the question")
                state["answers"].pop(keys[which - 1], None)
                pending = [k for k in keys if k not in state["answers"]]
        elif picked == 4:
            which = _number(console, len(keys), "the question")
            state["answers"].pop(keys[which - 1], None)
            pending = [k for k in keys if k not in state["answers"]]

    if not state.get("requirements"):
        ask_requirements(console, paths, source, state)
        save_state(paths, state)
        write_files(console, paths, state)
        console.say(f"  saved to {paths.rel(paths.task)}")

    total = len(keys)
    if pending:
        # Said once, because building the options runs the user's code and a
        # slow function otherwise looked like a hang.
        console.say("")
        console.say("For each question, qikly tries your functions on a few "
                    "nearby inputs, in a separate process and an empty folder, "
                    "to offer concrete answers. Nothing of yours is changed. If "
                    f"a function takes longer than {start_probe_timeout()} "
                    "seconds, that question offers only skip or your own answer.")
    for key in pending:
        number = keys.index(key) + 1
        previous = by_key[keys[number - 2]] if number > 1 else None
        same = bool(previous and previous.get("line") == by_key[key].get("line"))
        state["answers"][key] = ask_question(console, number, total, by_key[key],
                                             source, test_sources, root, same)
        state["answers"][key]["number"] = number
        save_state(paths, state)
        write_files(console, paths, state)
        rec = state["answers"][key]
        if rec["status"] in (so.ASK, so.SKIP):
            console.say(f"  saved, as an open question, to {paths.rel(paths.open)}")
        else:
            console.say(f"  saved to {paths.rel(paths.task)}")
    # Keep the answers in the order the questions are asked.
    state["answers"] = {k: state["answers"][k] for k in keys if k in state["answers"]}

    for changed in summary(console, paths, state, by_key,
                           _rule_example(questions, test_sources)):
        if changed is not None:
            n = keys.index(changed) + 1
            state["answers"][changed] = ask_question(console, n, total, by_key[changed],
                                                     source, test_sources, root)
            state["answers"][changed]["number"] = n
        save_state(paths, state)
        write_files(console, paths, state)
        console.say(f"  saved to {paths.rel(paths.task)}")

    ask_data(console, paths, state, source, test_sources)
    save_state(paths, state)
    data = write_files(console, paths, state)
    console.say(f"  saved to {paths.rel(data)}")
    return state, data


def _existing_task(console, paths, can_ask=True):
    """A task file this command did not write is never overwritten unasked."""
    if not os.path.exists(paths.task) or os.path.exists(paths.state):
        return True
    if not can_ask:
        # Without a terminal, or reading answers from a file, there is nobody
        # to ask; a menu here hung on an open pipe.
        console.say(f"{paths.rel(paths.task)} already exists, and qikly --start "
                    f"did not write it, so it is left alone. Move it aside, or "
                    f"run qikly --start in a terminal to choose another name.")
        return False
    picked = choose(console, [
        f"move it aside to {os.path.basename(paths.task)}.bak and start fresh",
        "leave it alone and stop here",
        "type a different name for the new task",
    ], lead=[f"{paths.rel(paths.task)} already exists, and qikly --start did "
             f"not write it."])
    if picked == 1:
        shutil.move(paths.task, paths.task + ".bak")
        console.say(f"  moved to {paths.rel(paths.task)}.bak")
        return True
    if picked == 2:
        return False
    from qikly.scaffold import VERIFY_SUFFIX
    name = free_text(console, "Type a name for the new task, in letters, digits "
                     "and underscores", "PRICING_V2")
    name = re.sub(r"[^A-Za-z0-9_]", "_", name).upper().strip("_") or "MY_TASK"
    if name.endswith(VERIFY_SUFFIX):
        name = name[:-len(VERIFY_SUFFIX)] or "MY_TASK"
    paths.name(name)
    console.say(f"  the new task is {paths.task_id}, in {paths.rel(paths.task)}")
    return _existing_task(console, paths)


def offer_run(console, cwd, task_ids, module_arg):
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
                f"not now (to run it later, run  qikly --start {module_arg}  again)",
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
            f"not now (to run it later, run  qikly --start {module_arg}  again)",
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


def main(arg, cwd, console=None, answers=None):
    console = console or Console()
    try:
        return _main(arg, cwd, console, answers)
    except (Stop, KeyboardInterrupt):
        console.say("")
        console.say("Stopped. Every answer you gave is saved, in the task file "
                    "under " + os.path.join("inputs_private", "config", "tasks")
                    + " and the progress file under "
                    + os.path.join("inputs_private", "questions")
                    + ". Run the same command again to continue where you stopped.")
        return STOPPED


def _choose_tests(console, code, cwd, session):
    """
    The tests, asked once. The choice is saved, so a rerun says which it is
    using rather than asking again, and offers a different path in one step.
    """
    previous = session.get("tests")
    if previous:
        path = os.path.join(cwd, previous)
        if os.path.exists(path):
            picked = choose(console, [
                f"the same tests as last time: {previous}",
                "type a path to different tests",
            ], lead=[f"Which tests should "
                     f"{os.path.basename(code) if os.path.isfile(code) else shown(code, cwd) + os.sep} "
                     f"be scored against?"])
            if picked == 1:
                return os.path.abspath(path)
            return _typed_path(console, cwd, "a test file or folder")
    return pick_tests(console, code, cwd)


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


def _main(arg, cwd, console, answers):
    if not console.interactive and not answers:
        return _non_interactive(arg, cwd, console)
    if answers:
        code = os.path.abspath(os.path.join(cwd, arg or "."))
        if not os.path.exists(code):
            console.say(f"There is no file or folder at {code}.")
            return 2
        session = load_session(cwd, code)
        saved = session.get("tests")
        # The tests the questions were asked against, not a fresh guess: a
        # different suite asks different questions, and answers matched by
        # number then landed on the wrong one.
        tests = (os.path.abspath(os.path.join(cwd, saved))
                 if saved and os.path.exists(os.path.join(cwd, saved))
                 else auto_tests(code, cwd))
        if not tests:
            console.say("No test files that import it were found.")
            return 2
    else:
        code = pick_code(console, arg, cwd)
        announce(console, cwd, code)
        session = load_session(cwd, code)
        tests = _choose_tests(console, code, cwd, session)
    result, report = _scored(console, code, tests, cwd, session)
    if result is None:
        return 2
    questions = enrich(list(result.get("questions") or []), result["missed"])
    _say_score(console, result, report, cwd, questions)
    if not questions:
        console.say("Your tests caught every fault qikly planted, so there is "
                    "nothing to ask. That says your tests notice changes to the "
                    "code that exists; it cannot say whether a rule is missing.")
        return 0
    test_sources = _test_sources(tests)
    root = project_root(code, cwd)
    results, blocked = [], False
    modules = _modules(questions, code, cwd, session)
    file_module = parse_answers(answers)[3] if answers else None
    for index, (module, qs, base) in enumerate(modules, 1):
        paths = Paths(cwd, module, base)
        if answers and file_module and file_module != shown(module, cwd):
            # One module's answers never land on another module's questions.
            continue
        problem = _cannot_task(paths)
        if problem:
            console.say(f"{shown(module, cwd)} is skipped: {problem}")
            continue
        if len(modules) > 1:
            console.say("")
            console.say(f"Module {index} of {len(modules)}: {shown(module, cwd)}, "
                        f"{len(qs)} question{'' if len(qs) == 1 else 's'}, task "
                        f"{paths.task_id}")
        if not _existing_task(console, paths, can_ask=not answers):
            blocked = True
            continue
        if paths.base != base:
            session.setdefault("names", {})[shown(module, cwd)] = paths.base
            save_session(cwd, code, session)
        if answers:
            state, data = _from_answers(console, paths, qs, test_sources, root,
                                        answers)
        else:
            state, data = module_flow(console, paths, qs, test_sources, root)
        results.append((paths, state, data))
    if answers and file_module and not results:
        console.say(f"{shown(answers, cwd)} is about {file_module}, which this "
                    f"score has no questions for.")
        return 2
    if not results:
        return 2 if blocked else 0
    ready, refused = [], False
    for paths, state, data in results:
        errors, warnings = validate(console, paths)
        console.say("")
        if errors:
            refused = True
            console.say(f"{paths.task_id} cannot run yet:")
            for e in errors:
                console.say(f"  - {e}")
            console.say(f"Fix it in {paths.rel(paths.task)}, or run this command "
                        f"again to change your answers.")
            continue
        if warnings:
            console.say(f"Checked {paths.task_id}, with {len(warnings)} warning"
                        f"{'' if len(warnings) == 1 else 's'}. Each is a reason a "
                        f"test may check less than you meant; none stops the run:")
            for w in warnings:
                console.say(f"  - {w}")
            if console.interactive and not answers:
                picked = choose(console, [
                    "continue anyway",
                    "stop here, to fix it in the files named above",
                    "type an extra row of example values to add, then continue",
                ])
                if picked == 2:
                    continue
                if picked == 3 and state.get("columns"):
                    state["rows"] = (state.get("rows") or []) + ask_rows(
                        console, state["columns"],
                        state["rows"][0] if state.get("rows") else None)
                    state["rows_typed"] = True
                    save_state(paths, state)
                    write_files(console, paths, state)
                    console.say(f"  saved to {paths.rel(data)}")
        else:
            console.say(f"Checked {paths.task_id}: ready to run.")
        ready.append(paths.task_id)
    ran, failed = False, False
    if ready and console.interactive and not answers:
        module_arg = score_questions_pasteable(code, cwd)
        if offer_run(console, cwd, ready, module_arg):
            converged, lines = run(console, cwd, ready)
            ran, failed = True, not converged
            for paths, state, data in results:
                if paths.task_id in ready:
                    report_result(console, paths, state, lines, converged)
    elif ready:
        console.say(f"To run it, which needs an API key:  qikly --tasks {' '.join(ready)}")
    inputs_outputs(console, cwd, code, tests, report, results, ran)
    if failed:
        return 1
    return 2 if refused and not ready else 0


def _cannot_task(paths):
    """Why no task can be written for this module, before anything is asked."""
    from qikly.scaffold import build_task
    _, problem = build_task(paths.module, paths.cwd, task_id=paths.base,
                            seed="existing")
    return problem


def _complete(paths):
    state = load_state(paths)
    return bool(state and state.get("requirements") and state.get("answers")
                and (state.get("rows") or state.get("sample")))


# --------------------------------------------------- without a terminal ----

def _non_interactive(arg, cwd, console):
    """No prompts: score, print the questions, write them where --answers reads."""
    if not arg:
        console.say("qikly --start needs a module or folder when it is not run "
                    "in a terminal, such as  qikly --start pricing.py")
        return 2
    code = os.path.abspath(os.path.join(cwd, arg))
    if not os.path.exists(code):
        console.say(f"There is no file or folder at {code}.")
        return 2
    root = project_root(code, cwd)
    session = load_session(cwd, code)
    saved = session.get("tests")
    tests = (os.path.abspath(os.path.join(cwd, saved))
             if saved and os.path.exists(os.path.join(cwd, saved))
             else auto_tests(code, cwd))
    if not tests:
        console.say("No test files that import it were found. Score it with  "
                    "qikly --score-code <code> --score-tests <tests>")
        return 2
    result, report = _scored(console, code, tests, cwd, session)
    if result is None:
        return 2
    questions = enrich(list(result.get("questions") or []), result["missed"])
    _say_score(console, result, report, cwd, questions)
    if not questions:
        console.say("Your tests caught every fault qikly planted, so there is "
                    "nothing to ask.")
        return 0
    test_sources = _test_sources(tests)
    written = []
    for module, qs, base in _modules(questions, code, cwd, session):
        paths = Paths(cwd, module, base)
        state = load_state(paths) or {"answers": {}}
        answers_cmd = (f"qikly --start {score_questions_pasteable(code, cwd)} "
                       f"--answers {score_questions_pasteable(paths.open, cwd)}")
        lines = [f"# Questions about {os.path.basename(module)} from qikly --start.",
                 "# This was not run in a terminal, so nothing was asked. Give",
                 "# each question an answer after its Q number: an option",
                 "# number from its list, or skip, either or ask, or your own",
                 "# words naming a value. For an option that asks for a value,",
                 "# write the number, a colon and the value, such as  1: 0.0",
                 "# Then run",
                 f"#   {answers_cmd}",
                 "",
                 f"module: {shown(module, cwd)}",
                 "",
                 "# What the module should do, in a sentence: the coding agent",
                 "# is told this, so describe its purpose, not its boundary values.",
                 "requirements: " + (state.get("requirements") or ""),
                 ""]
        source = _read(module)
        for n, q in enumerate(qs, 1):
            prompt, options = so.menu(q, source, test_sources, root, q.get("mutant"))
            lines.append(f"# {where(q)}: {q['question']}")
            if prompt:
                lines.append(f"# {prompt}")
            for i, o in enumerate(options, 1):
                lines.append(f"#   {i}. {o['label']}")
            lines += [f"# id {_key(q)}", f"Q{n}: ", ""]
        os.makedirs(os.path.dirname(paths.open), exist_ok=True)
        with open(paths.open, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines))
        written.append((paths.open, answers_cmd))
        console.say("")
        console.say("\n".join(lines))
    console.say("")
    console.say("Not run in a terminal, so nothing was asked. The questions are "
                "saved to:")
    for path, command in written:
        console.say(f"  {shown(path, cwd)}")
        console.say(f"    answer them there, then run:  {command}")
    console.say("If you are at a keyboard and still see this, your terminal is "
                "not one Python recognises, which is how Git Bash's window "
                "behaves. Run the same command in PowerShell or cmd, or set "
                "QIKLY_INTERACTIVE=1 first:  QIKLY_INTERACTIVE=1 qikly --start ...")
    return NEEDS_ANSWERS


def parse_answers(path):
    """
    (answers by number, requirements, rows, module, ids by number) from a
    file: `Q3: text` lines, each optionally after a `# id <key>` line,
    `requirements: text`, `row: a, b, c` and `module: path`.
    """
    found, requirements, rows, module, ids = {}, None, [], None, {}
    pending_id = None
    for line in _read(path).splitlines():
        marker = re.match(r"^\s*#\s*id\s+([0-9a-f]{6,})\s*$", line)
        if marker:
            pending_id = marker.group(1)
            continue
        if line.lstrip().startswith("#"):
            continue
        q = re.match(r"^\s*Q(\d+)\s*:\s*(.*)$", line)
        if q:
            if pending_id:
                ids[int(q.group(1))] = pending_id
            pending_id = None
            if q.group(2).strip():
                found[int(q.group(1))] = _UNSAFE.sub("", q.group(2)).strip()
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


def _from_answers(console, paths, questions, test_sources, root, answers_path):
    from qikly.scaffold import starter_columns

    given, requirements, rows, _, ids = parse_answers(answers_path)
    source = _read(paths.module)
    state = load_state(paths) or {"answers": {}, "extra": []}
    state.setdefault("extra", [])
    if requirements:
        state["requirements"] = requirements
    if not state.get("requirements"):
        console.say(f"{shown(answers_path, paths.cwd)} has no requirements: line, "
                    f"so the coding agent would not be told what the module "
                    f"does. Add one, such as  requirements: applies a discount.")
    # Matched by the question's id where the file carries one, so a file
    # answered against an earlier score cannot put an answer on another
    # question; by number only for a file without ids.
    by_id = {ids[n]: text for n, text in given.items() if n in ids}
    for n, q in enumerate(questions, 1):
        key = _key(q)
        text = by_id.get(key) if ids else given.get(n)
        rec = {"question": q["question"], "where": where(q), "number": n, "key": key}
        if not text:
            if key in state["answers"]:
                state["answers"][key]["number"] = n
                continue
            rec["status"] = so.SKIP
        elif text.lower() in ("skip", "either", "ask"):
            rec["status"] = {"skip": so.SKIP, "either": so.EITHER, "ask": so.ASK}[text.lower()]
        elif re.match(r"^\d+\s*[.):]?\s*(?::\s*(.+))?$", text) and \
                int(re.match(r"^\d+", text).group(0)) <= 9:
            # An option number, alone or as "1: 0.0" for an option that asks
            # for a value. Numbers above 9 are answers, not options.
            k = int(re.match(r"^\d+", text).group(0))
            value = re.match(r"^\d+\s*[.)]?\s*:\s*(.+)$", text)
            value = value.group(1).strip() if value else None
            _, options = so.menu(q, source, test_sources, root, q.get("mutant"))
            if not 1 <= k <= len(options):
                console.say(f"Q{n}: there is no option {k}; it is left open.")
                rec["status"] = so.SKIP
            else:
                o = options[k - 1]
                if o["kind"] == so.BEHAVIOUR and o["pins"].get("returns", "") is None \
                        and value is None:
                    console.say(f"Q{n}: option {k} needs a value; write it as "
                                f"{k}: <value>. It is left open.")
                    rec["status"] = so.SKIP
                elif o["kind"] == so.BEHAVIOUR:
                    rec.update(status="answered", criterion=so.criterion(o, value),
                               function=o["function"], args=o["args"],
                               kwargs=o.get("kwargs") or {})
                elif o["kind"] == so.OWN:
                    console.say(f"Q{n}: write your own answer in words instead "
                                f"of {k}. It is left open.")
                    rec["status"] = so.SKIP
                else:
                    rec["status"] = o["kind"]
        elif len(text.split()) < 3:
            console.say(f"Q{n}: \"{text}\" is too short to be a criterion; write "
                        f"the input and what should happen to it. It is left open.")
            rec["status"] = so.SKIP
        else:
            rec.update(status="answered", criterion=text)
        state["answers"][key] = rec
    columns = starter_columns(source)
    if columns == []:
        state["rows"], state["columns"], state["rows_typed"] = [["none"]], ["input"], False
    elif rows and columns:
        state["rows"], state["columns"] = [r for r in rows if len(r) == len(columns)], columns
        state["rows_typed"] = True
    elif columns and not state.get("rows_typed"):
        # Rebuilt each time, so an answer added since adds its row.
        state["rows"] = build_rows(state, columns, source, test_sources)
        state["columns"] = columns
    elif columns is None and not state.get("sample"):
        console.say(f"{os.path.basename(paths.module)} reads files, so it needs a "
                    f"real sample file: run qikly --start in a terminal to give "
                    f"its path, or copy one to {paths.rel(paths.data)}.")
    save_state(paths, state)
    data = write_files(console, paths, state)
    console.say(f"saved to {paths.rel(paths.task)}"
                + (f" and {paths.rel(data)}" if os.path.exists(data) else ""))
    return state, data
