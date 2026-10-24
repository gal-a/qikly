"""
The code and tests a person already has: where they are, how many faults to
plant in them, and what `--scaffold` fills in for a task about that code.

`--score` and `--scaffold` share these, so step 1 and step 2 on the home page
find the same tests and talk about the same module. A first user of the old
scaffold met six TODOs, a CSV with only a header, and questions with nothing
to go on; this is what fills those in: the rows the tests already call the
code with, the whole package as the seed when the module imports its
siblings, and, for each question, what the code does beside the value in
question, found by running it. The answers stay the person's: see
`start_options` for how those values are found without reading an answer off
the code.
"""
import json
import os
import re
import subprocess
import sys

from qikly import start_options as so


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
    where the null device reports itself as a terminal: `qikly --score <
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


_DEFINES_TEST = re.compile(r"^\s*(?:(?:async\s+)?def\s+test|class\s+Test)", re.M)


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
    # Only files that define a test: phart's examples/ held *_test.py demo
    # scripts that outnumbered tests/, and step 1 ran in examples/ with no
    # tests at all.
    files = [f for f in _test_files(root) if _DEFINES_TEST.search(_read(f))]
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


QUICK_ENOUGH = 300   # seconds of scoring before the user is asked first


def how_many(console, target, tests, cwd, many):
    """
    (faults it could plant, faults to plant): every one up to the cap, fewer
    when the suite is slow. With a fixed 12, `--score` said 9 of 12 missed
    where a full count of the same code said 10 of 13.
    """
    from qikly import mutation_score as ms
    sites = sum(len(ms.sites(_read(path))) for path, _ in target.files)
    planted = min(sites, SCORE_CAP_MANY if many else SCORE_CAP_ONE)
    if planted:
        planted = _fit_to_time(console, tests, cwd, planted)
    return sites, planted


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

    sources, sites = {}, {}
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
                # Found once per file: worked out again for every question,
                # tabulate's 3,000 lines took five and a half minutes here.
                if path not in sites:
                    sites[path] = ms.sites(source or "")
                for family, index, described in sites[path]:
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
    """
    Rows from any answered calls in `state` and the literal calls in the
    tests. `--scaffold` passes no answers: the rows are what the tests
    already call the code with, so the data file is never only a header.
    """
    state = state or {}
    from qikly.scaffold import read_interface

    rows, typical = [], {}
    # A class is called by its own name, with its constructor's arguments.
    functions = {f.name: [a.arg for a in f.args.posonlyargs + f.args.args]
                 for f in read_interface(source)}

    def values_of(function, args, kwargs):
        values = dict(zip(functions[function], args))
        values.update(kwargs or {})
        return values

    for rec in (state.get("answers") or {}).values():
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


def package_seed(text, module, cwd):
    """
    For a module inside a package, seed the whole top-level package and name
    the module by its dotted path, as the task file reference describes.

    A single-file seed copies only that file, so `from .util import clamp`
    failed in qikly's copy before any test ran on the user's code: the run
    was then green against code qikly had already changed, and could say
    nothing about where the code and the criteria disagree. Found on a src/
    layout.
    """
    from qikly import start_probe

    root = project_root(module, cwd)
    dotted = start_probe.dotted_name(module, root)
    is_init = os.path.basename(module) == "__init__.py"
    # A package's `__init__.py` is always seeded as its package: copied as a
    # lone file it would be a module called __init__ that nothing imports.
    if "." not in dotted and not is_init:
        return text
    # A package named like a standard-library module, `code` or `json`, is
    # refused by the run as a seed, but only after the paid test generation;
    # such a module stays a single-file seed, as it was before.
    if dotted.split(".")[0] in getattr(sys, "stdlib_module_names", ()):
        return text
    top = os.path.join(start_probe.import_base(module, root), dotted.split(".")[0])
    seed = shown(top, cwd).replace(os.sep, "/")
    text = re.sub(r'^(  module: )".*"$', lambda m: m.group(1) + json.dumps(dotted),
                  text, count=1, flags=re.M)
    text = re.sub(r'^(  implementation: )".*"$', lambda m: m.group(1) + json.dumps(seed),
                  text, count=1, flags=re.M)
    return text


def run_from_inside(module, cwd):
    """
    Why a task cannot be written for a package's __init__.py run from inside
    that package, or None: it has no package name to be imported by there.
    """
    from qikly import start_probe
    if os.path.basename(module) != "__init__.py":
        return None
    if start_probe.dotted_name(module, project_root(module, cwd)) != "__init__":
        return None
    pkg = os.path.basename(os.path.dirname(os.path.abspath(module)))
    return (f"it is the package {pkg} itself, run from inside it. Run the "
            f"command from the folder above: cd .. then qikly --scaffold {pkg}")


def rows_from_tests(module, cwd, columns):
    """The data file's rows: the values the tests already call the code with."""
    tests = auto_tests(module, cwd)
    if not tests or not columns:
        return []
    source = _read(module)
    rows = build_rows(None, columns, source, _test_sources(tests))
    # A value with a line break cannot sit on one line of a CSV row.
    return [r for r in rows if not any("\n" in v or "\r" in v for v in r)]


def _numbered(option):
    """
    One option as the task file numbers it: the criterion it becomes, with
    VALUE where the person writes the value, and a note on what the code does
    beside the value in question, from the option's own label.
    """
    from qikly.score_questions import VALUE
    pins, call = option.get("pins") or {}, option.get("call") or ""
    if "raises" in pins:
        criterion = f"{call} raises {pins['raises']}"
    elif pins.get("returns") is None:
        criterion = f"{call} returns {VALUE}"
    else:
        criterion = f"{call} returns {pins['returns']}"
    label = option.get("label") or ""
    note = ("as " + label.split(", as ", 1)[1]) if ", as " in label else ""
    note = note.split("; you will type")[0]
    return {"criterion": criterion, "note": note,
            "now": label.endswith("as your code does now")}


# Seconds --scaffold spends running the code beside its questions. On
# tabulate, ten questions took fifteen minutes with nothing on screen, for one
# set of options; past this, the rest are written as the score asked them.
HINT_BUDGET = 60


def hinted(questions, module, cwd, budget=HINT_BUDGET):
    """
    The saved questions about `module`, merged where they ask about the same
    call, each with what the code does beside the value in question where
    running it finds that: `hint_prompt`, such as "What should
    apply_discount(100, 100) do?", and `hint_options`, such as "raise
    ValueError, as rate 101 does now". Never what it does at the value
    itself: that is the question.

    Anything that fails leaves the question as the score report asked it,
    and so does every question still waiting once `budget` seconds have
    gone: those are marked `unhinted`, so the caller can say so. The time is
    checked between questions, so one slow question can run past it.
    """
    import time
    started = time.monotonic()
    try:
        tests = auto_tests(module, cwd)
        test_sources = _test_sources(tests) if tests else []
        root = project_root(module, cwd)
        source = _read(module)
        missed = [{"path": q.get("path"), "change": q.get("change")}
                  for q in questions if q.get("change")]
        qs = enrich(group([dict(q) for q in questions]), missed)
    except Exception:
        return list(questions)
    out, by_mark = [], {}
    for q in qs:
        if time.monotonic() - started > budget:
            q.pop("mutant", None)
            q["unhinted"] = True
            out.append(q)
            continue
        try:
            prompt, options = so.menu(q, source, test_sources, root, q.get("mutant"))
        except Exception:
            prompt, options = None, []
        q.pop("mutant", None)
        if prompt:
            behaviours = [o for o in options if o["kind"] == so.BEHAVIOUR]
            pins = sorted(json.dumps(o.get("pins"), sort_keys=True) for o in behaviours)
            mark = json.dumps([re.sub(r"\bline \d+", "line", prompt), pins])
            if mark in by_mark:
                by_mark[mark]["covers"] = by_mark[mark].get("covers", 0) + 1
                continue
            # In an order fixed by the values, not "as your code does now"
            # first, which reads as the answer. Each with the criterion its
            # number becomes, so a person can answer with the number.
            q.update(hint_prompt=prompt,
                     hint_options=[_numbered(o) for o in sorted(
                         behaviours, key=lambda o: json.dumps(o.get("pins"), sort_keys=True))])
            by_mark[mark] = q
        out.append(q)
    return out


def _test_sources(tests):
    return [_read(p) for p in ([tests] if os.path.isfile(tests) else _test_files(tests))]
