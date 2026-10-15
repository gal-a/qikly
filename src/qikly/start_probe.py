"""
Run a few calls against a module, in a separate process, and say what each did.

`qikly --start` offers each question's answers as concrete behaviours, "raise
ValueError, as rate 101 does now", which means calling the user's functions.
That happens here, in a child process with a timeout, so a function that hangs,
exits or prints cannot take the guided flow down with it, and nothing it
imports stays loaded in the process that is asking the questions.

The parent sends JSON on stdin:

    {"path": "...pricing.py", "root": "...", "mutant": null or source text,
     "calls": [["apply_discount", [80, 99], {}], ...]}

and reads JSON on stdout: one outcome per call, `{"returns": "60.0"}` (the
repr) or `{"raises": "ValueError"}`, in order. `mutant`, when given, is run in
place of the file's own source, so the same calls can be compared against the
code with one planted change.
"""
import json
import os
import subprocess
import sys

TIMEOUT = 20

_CHILD = r'''
import importlib.util, io, json, os, sys, types, contextlib
spec_in = json.loads(sys.stdin.read())
path, root = spec_in["path"], spec_in["root"]
for entry in (os.path.dirname(path), root):
    if entry and entry not in sys.path:
        sys.path.insert(0, entry)
os.chdir(root)
name = os.path.splitext(os.path.basename(path))[0]
module = types.ModuleType(name)
module.__file__ = path
source = spec_in.get("mutant")
if source is None:
    with open(path, encoding="utf-8-sig") as handle:
        source = handle.read()
out = []
try:
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(source, path, "exec"), module.__dict__)
except BaseException as exc:
    print(json.dumps({"load": type(exc).__name__}))
    sys.exit(0)
for func, args, kwargs in spec_in["calls"]:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            value = getattr(module, func)(*args, **kwargs)
        out.append({"returns": repr(value)})
    except BaseException as exc:
        out.append({"raises": type(exc).__name__})
print(json.dumps({"outcomes": out}))
'''


def run_calls(path, root, calls, mutant=None):
    """
    The outcome of each call, or None when the module could not be run at
    all: it failed to import, hung past the timeout, or the child crashed.
    None is never an error to the user; the question just falls back to
    "type my own answer".
    """
    payload = json.dumps({"path": os.path.abspath(path),
                          "root": os.path.abspath(root),
                          "mutant": mutant,
                          "calls": [[f, list(a), dict(k)] for f, a, k in calls]})
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _CHILD],
                              input=payload, capture_output=True, text=True,
                              timeout=TIMEOUT, cwd=os.path.abspath(root))
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        reply = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    outcomes = reply.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != len(calls):
        return None
    return outcomes


def describe(outcome):
    """An outcome as words: "raises ValueError" or "returns 60.0"."""
    if not outcome:
        return "does something qikly could not see"
    if "raises" in outcome:
        return f"raises {outcome['raises']}"
    return f"returns {outcome['returns']}"
