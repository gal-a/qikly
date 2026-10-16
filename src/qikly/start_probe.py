"""
Run a few calls against a module, in a separate process, and say what each did.

`qikly --start` offers each question's answers as concrete behaviours, "raise
ValueError, as rate 101 does now", which means calling the user's functions.
That happens here, in a child process with a timeout, so a function that hangs,
exits or prints cannot take the guided flow down with it, and nothing it
imports stays loaded in the process that is asking the questions.

Four rules, each from an audit finding before 0.6.0:

- **The child runs in an empty temporary folder**, never the user's project.
  A function that writes `name + ".txt"` wrote into the project root, which
  contradicted "nothing of yours is changed".
- **Arguments travel as Python literals, not JSON.** JSON turned tuples into
  lists and int dict keys into strings, so a "does now" label described a call
  the user's code never received, and bytes or sets crashed the whole command.
  A value whose repr does not read back as itself is never sent.
- **The module is imported under its dotted name**, registered in
  `sys.modules`, so relative imports and dataclasses work as in the user's
  tests, and `PYTHONPATH` reaches the child as it reaches their tests.
- **The code and the code with a planted change run in one child**, so one
  question costs one start-up and one timeout, not two.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

TIMEOUT = 15

_CHILD = r'''
import ast, contextlib, importlib, importlib.util, io, json, os, re, sys
spec_in = json.loads(sys.stdin.read())
path, root, dotted = spec_in["path"], spec_in["root"], spec_in["dotted"]
line = spec_in.get("line")
span = spec_in.get("span")
top = dotted.split(".")[0]
# A memory address differs on every run and says nothing about behaviour:
# two reprs of one function, or of one object, compared as different.
ADDRESS = re.compile(r" at 0x[0-9A-Fa-f]+")
is_init = os.path.basename(path) == "__init__.py"
for entry in (os.path.dirname(path), root, spec_in.get("base")):
    if entry and entry not in sys.path:
        sys.path.insert(0, entry)

def by_file(source):
    """The module from its own file, as before: no package code runs."""
    package = [os.path.dirname(path)] if is_init else None
    spec = importlib.util.spec_from_file_location(
        dotted, path, submodule_search_locations=package)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    with contextlib.redirect_stdout(io.StringIO()):
        if source is None:
            spec.loader.exec_module(module)
        else:
            exec(compile(source, path, "exec"), module.__dict__)
    return module

class Serve(object):
    """Serves the changed source under the module's own name, inside its package."""
    def __init__(self, source):
        self.source = source
    def find_spec(self, name, target_path=None, target=None):
        if name != dotted:
            return None
        return importlib.util.spec_from_loader(name, self, origin=path, is_package=is_init)
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        module.__file__ = path
        if is_init:
            module.__path__ = [os.path.dirname(path)]
        exec(compile(self.source, path, "exec"), module.__dict__)

def forget():
    """The package and everything in it out of sys.modules, for a fresh start."""
    for name in [n for n in sys.modules if n == top or n.startswith(top + ".")]:
        del sys.modules[name]

def by_package(source):
    """
    Through its package, for a module the package imports back, which met
    itself half-built when loaded by file: isodate's isodates. The changed
    copy is served inside a freshly imported package, so the modules beside
    it see its classes, and the code is never run twice side by side, which
    reported a sibling's exception as the module's own.
    """
    forget()
    finder = Serve(source) if source is not None else None
    if finder:
        sys.meta_path.insert(0, finder)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return importlib.import_module(dotted)
    finally:
        if finder:
            sys.meta_path.remove(finder)

ours = {}
target = os.path.normcase(os.path.abspath(path))

def is_ours(code):
    if code not in ours:
        ours[code] = os.path.normcase(os.path.abspath(code.co_filename)) == target
    return ours[code]

def outcomes(module, calls, trace=False):
    out, reached = [], []
    for func, args, kwargs in calls:
        hit = [False]
        def tracer(frame, event, arg):
            if is_ours(frame.f_code):
                if event == "line" and frame.f_lineno == line:
                    hit[0] = True
                # A line in a signature, a default such as width=4, never
                # runs as a line: calling the function is what reaches it.
                if event == "call" and span and span[0] <= frame.f_code.co_firstlineno <= span[1]:
                    hit[0] = True
                return tracer
            return None
        try:
            args = [ast.literal_eval(a) for a in args]
            kwargs = {k: ast.literal_eval(v) for k, v in kwargs.items()}
            if trace and (line or span):
                sys.settrace(tracer)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    value = getattr(module, func)(*args, **kwargs)
            finally:
                sys.settrace(None)
            out.append({"returns": ADDRESS.sub(" at 0x...", repr(value))})
        except BaseException as exc:
            out.append({"raises": type(exc).__name__})
        reached.append(hit[0])
    return out, reached

reply = {}
calls = spec_in["calls"]
try:
    try:
        load, real = by_file, by_file(None)
    except Exception:
        # Any failure, not only ImportError: a circular `from . import mod`
        # then `mod.Thing()` in the package raised AttributeError by file.
        load, real = by_package, by_package(None)
    reply["now"], reply["reached"] = outcomes(real, calls, trace=True)
    # Twice: a call whose outcome changes from one run to the next, a uuid
    # or the time, would otherwise be offered as a difference.
    reply["again"] = outcomes(real, calls)[0]
except BaseException as exc:
    reply["load"] = type(exc).__name__
if "load" not in reply and spec_in.get("mutant") is not None:
    try:
        # The whole package, not only the module: a sibling left loaded kept
        # the first copy's exception class, and the changed copy then raised
        # where neither version of the code does.
        forget()
        reply["changed"] = outcomes(load(spec_in["mutant"]), calls)[0]
    except BaseException as exc:
        reply["load"] = type(exc).__name__
sys.stdout.write("\n" + json.dumps(reply) + "\n")
sys.stdout.flush()
# Not a normal exit: a package that leaves a thread running kept the child
# alive until the timeout, on every probe.
os._exit(0)
'''


def _package_walk(path, root):
    path, root = os.path.abspath(path), os.path.abspath(root)
    parts = [os.path.splitext(os.path.basename(path))[0]]
    folder = os.path.dirname(path)
    while (folder.startswith(root + os.sep)
           and os.path.isfile(os.path.join(folder, "__init__.py"))):
        parts.insert(0, os.path.basename(folder))
        folder = os.path.dirname(folder)
    return parts, folder


def dotted_name(path, root):
    """
    `shop.pricing` for root/shop/pricing.py when shop is a package, else
    `pricing`; `shop` for shop/__init__.py, which is how it is imported.
    """
    parts = _package_walk(path, root)[0]
    if len(parts) > 1 and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_base(path, root):
    """
    The folder the top-level package sits in, which has to be importable: in
    a `src/` layout that is `src/`, and without it a relative import such as
    `from .util import clamp` failed, so no question got concrete options.
    """
    return _package_walk(path, root)[1]


def sendable(value):
    """Whether a value's repr reads back as an equal value of the same type."""
    try:
        back = ast.literal_eval(repr(value))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False
    return type(back) is type(value) and back == value


def run_calls(path, root, calls, mutant=None, line=None, span=None):
    """
    The outcome of each call, or None when the module could not be run at
    all. With `mutant`, a pair: (outcomes now, outcomes with the change).
    None is never an error to the user; the question just falls back to
    "type my own answer". With `line`, a third list says which calls ran it.

    A call whose outcome is not the same twice running is never offered as
    a difference: without a change it reads as no difference at all, and
    without a mutant the whole answer is None, so nothing random is labelled.
    """
    if not all(sendable(a) for _, args, kwargs in calls
               for a in list(args) + list(kwargs.values())):
        return None
    payload = json.dumps({
        "path": os.path.abspath(path), "root": os.path.abspath(root),
        "dotted": dotted_name(path, root), "base": import_base(path, root),
        "mutant": mutant, "line": line, "span": span,
        "calls": [[f, [repr(a) for a in args],
                   {k: repr(v) for k, v in kwargs.items()}]
                  for f, args, kwargs in calls]})
    try:
        with tempfile.TemporaryDirectory() as empty:
            done = subprocess.run([sys.executable, "-c", _CHILD],
                                  input=payload, capture_output=True, text=True,
                                  timeout=TIMEOUT, cwd=empty,
                                  encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        reply = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    now, again = reply.get("now"), reply.get("again")
    if not (isinstance(now, list) and isinstance(again, list)
            and len(now) == len(again) == len(calls)):
        return None
    stable = [a == b for a, b in zip(now, again)]
    if mutant is None:
        return now if all(stable) else None
    changed = reply.get("changed")
    if not isinstance(changed, list) or len(changed) != len(calls):
        return None
    changed = [c if ok else n for c, n, ok in zip(changed, now, stable)]
    if line is not None or span is not None:
        reached = reply.get("reached") or [False] * len(calls)
        return now, changed, reached
    return now, changed


def describe(outcome):
    """An outcome as words: "raises ValueError" or "returns 60.0"."""
    if not outcome:
        return "does something qikly could not see"
    if "raises" in outcome:
        return f"raises {outcome['raises']}"
    return f"returns {outcome['returns']}"
