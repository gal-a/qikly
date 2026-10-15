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
import ast, contextlib, importlib.util, io, json, os, sys
spec_in = json.loads(sys.stdin.read())
path, root, dotted = spec_in["path"], spec_in["root"], spec_in["dotted"]
for entry in (os.path.dirname(path), root):
    if entry and entry not in sys.path:
        sys.path.insert(0, entry)

def load(source, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with contextlib.redirect_stdout(io.StringIO()):
        if source is None:
            spec.loader.exec_module(module)
        else:
            exec(compile(source, path, "exec"), module.__dict__)
    return module

def outcomes(module, calls):
    out = []
    for func, args, kwargs in calls:
        try:
            args = [ast.literal_eval(a) for a in args]
            kwargs = {k: ast.literal_eval(v) for k, v in kwargs.items()}
            with contextlib.redirect_stdout(io.StringIO()):
                value = getattr(module, func)(*args, **kwargs)
            out.append({"returns": repr(value)})
        except BaseException as exc:
            out.append({"raises": type(exc).__name__})
    return out

reply = {}
try:
    reply["now"] = outcomes(load(None, dotted), spec_in["calls"])
except BaseException as exc:
    reply["load"] = type(exc).__name__
if "load" not in reply and spec_in.get("mutant") is not None:
    try:
        sys.modules.pop(dotted, None)
        reply["changed"] = outcomes(load(spec_in["mutant"], dotted),
                                    spec_in["calls"])
    except BaseException as exc:
        reply["load"] = type(exc).__name__
print("\n" + json.dumps(reply))
'''


def dotted_name(path, root):
    """`shop.pricing` for root/shop/pricing.py when shop is a package, else `pricing`."""
    path, root = os.path.abspath(path), os.path.abspath(root)
    parts = [os.path.splitext(os.path.basename(path))[0]]
    folder = os.path.dirname(path)
    while (folder.startswith(root + os.sep)
           and os.path.isfile(os.path.join(folder, "__init__.py"))):
        parts.insert(0, os.path.basename(folder))
        folder = os.path.dirname(folder)
    return ".".join(parts)


def sendable(value):
    """Whether a value's repr reads back as an equal value of the same type."""
    try:
        back = ast.literal_eval(repr(value))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False
    return type(back) is type(value) and back == value


def run_calls(path, root, calls, mutant=None):
    """
    The outcome of each call, or None when the module could not be run at
    all. With `mutant`, a pair: (outcomes now, outcomes with the change).
    None is never an error to the user; the question just falls back to
    "type my own answer".
    """
    if not all(sendable(a) for _, args, kwargs in calls
               for a in list(args) + list(kwargs.values())):
        return None
    payload = json.dumps({
        "path": os.path.abspath(path), "root": os.path.abspath(root),
        "dotted": dotted_name(path, root), "mutant": mutant,
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
    now = reply.get("now")
    if not isinstance(now, list) or len(now) != len(calls):
        return None
    if mutant is None:
        return now
    changed = reply.get("changed")
    if not isinstance(changed, list) or len(changed) != len(calls):
        return None
    return now, changed


def describe(outcome):
    """An outcome as words: "raises ValueError" or "returns 60.0"."""
    if not outcome:
        return "does something qikly could not see"
    if "raises" in outcome:
        return f"raises {outcome['raises']}"
    return f"returns {outcome['returns']}"
