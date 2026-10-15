"""
The answers `qikly --start` offers for one question, as concrete behaviours.

The rule this module exists to keep: **the answer is the person's, never read
off the code.** So:

- **A boundary is never run at the value in question.** For `rate > 100` the
  code is run at 99 and at 101, and the two options say what those do now:
  "raise ValueError, as rate 101 does now". What 100 should do is still
  unknown to qikly, which is the point.
- **Elsewhere, an input is searched for where the code and the code with the
  planted change disagree**, and both results are offered, the current one
  labelled as such. The user sees the code line anyway; the label is honest
  about which is which, and the prompt asks what it *should* do.
- **The order of the two behaviours is shuffled**, seeded by the question, so
  "option 1" never comes to mean "what my code does".
- **Where neither works**, a check switched off, an error never raised, a
  function no test calls, the menu offers only "skip this question for now"
  and "type my own answer".

Every option set ends with free text, the user's rule for every menu.
"""
import ast
import hashlib
import random

from qikly import start_probe

# What an option does when chosen. A behaviour carries the call and the
# outcome it would pin; the others record a decision about the question.
BEHAVIOUR, EITHER, ASK, SKIP, OWN = "behaviour", "either", "ask", "skip", "own"


def literal_calls(test_sources, function):
    """
    The calls of `function` in the tests whose arguments are all literals, as
    (args, kwargs), in the order they appear. These are the inputs the user
    already chose, so building on them never invents a scenario.
    """
    found = []
    for source in test_sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (callee.id if isinstance(callee, ast.Name)
                    else callee.attr if isinstance(callee, ast.Attribute) else None)
            if name != function:
                continue
            try:
                args = [ast.literal_eval(a) for a in node.args]
                kwargs = {k.arg: ast.literal_eval(k.value)
                          for k in node.keywords if k.arg}
            except (ValueError, TypeError, SyntaxError):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if (args, kwargs) not in found:
                found.append((args, kwargs))
    return found


def parameters(source, function):
    """The positional parameter names of a top-level function, or None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            return [a.arg for a in node.args.posonlyargs + node.args.args]
    return None


def call_text(function, args, kwargs=None):
    """`apply_discount(80, 100)`, as the user would type it."""
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in (kwargs or {}).items()]
    return f"{function}({', '.join(parts)})"


def _shuffled(pair, question):
    seed = int(hashlib.sha256(question.encode("utf-8")).hexdigest()[:8], 16)
    pair = list(pair)
    random.Random(seed).shuffle(pair)
    return pair


def _boundary_variable(source, line, edge):
    """The name compared against `edge` on `line`, when it is a bare name."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare) and getattr(node, "lineno", None) == line
                and len(node.ops) == 1 and ast.unparse(node.comparators[0]) == edge
                and isinstance(node.left, ast.Name)):
            return node.left.id
    return None


def _neighbours(edge):
    try:
        value = ast.literal_eval(edge)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    step = 1 if isinstance(value, int) else 0.01
    return value, value - step, value + step


def boundary_options(question, source, test_sources, root):
    """
    Two behaviours for a boundary, from the code run on either side of it,
    or None when they cannot be built honestly.
    """
    function, edge = question.get("function"), question.get("edge")
    if not (function and edge and source):
        return None
    variable = _boundary_variable(source, question.get("line"), edge)
    params = parameters(source, function)
    near = _neighbours(edge)
    if not (variable and params and near and variable in params):
        return None
    position = params.index(variable)
    base = next((a for a, k in literal_calls(test_sources, function)
                 if not k and len(a) == len(params)), None)
    if base is None:
        return None
    at, below, above = near

    def with_value(value):
        args = list(base)
        args[position] = value
        return args

    outcomes = start_probe.run_calls(question["path"], root,
                                     [(function, with_value(below), {}),
                                      (function, with_value(above), {})])
    if not outcomes or outcomes[0] == outcomes[1]:
        return None
    call = call_text(function, with_value(at))
    behaviours = []
    for value, outcome in ((below, outcomes[0]), (above, outcomes[1])):
        if "raises" in outcome:
            label = (f"raise {outcome['raises']}, as {variable} {value!r} "
                     f"does now")
            pins = {"raises": outcome["raises"]}
        else:
            label = (f"return a value, as {variable} {value!r} does now "
                     f"(it returns {outcome['returns']}); you will type which "
                     f"value")
            pins = {"returns": None, "like": outcome["returns"]}
        behaviours.append({"kind": BEHAVIOUR, "label": label, "call": call,
                           "pins": pins, "args": with_value(at),
                           "function": function})
    prompt = (f"Your tests never try {variable} at exactly {edge}. "
              f"What should {call} do?")
    return prompt, _shuffled(behaviours, question["question"])


def _variants(value):
    """Nearby inputs for one argument, built from a value the tests used."""
    if isinstance(value, bool):
        return [not value]
    # Near values first, then the far ones a range check or an and/or only
    # shows on: a negative, a zero and something much larger.
    if isinstance(value, int):
        # And one fraction: rounding, and anything else about decimals, only
        # shows on a value that has some.
        return [value + 1, value - 1, value * 3 + 7, -value - 1, 0,
                value * 20 + 1, value + 0.333]
    if isinstance(value, float):
        return [value + 0.333, round(value * 1.37, 4), value + 1,
                -value - 1.0, 0.0, value * 20 + 1.0]
    if isinstance(value, str):
        out = [value.upper(), f" {value} ", value.capitalize(), value + "x"]
        return [v for v in out if v != value]
    return []


def _verb(outcome):
    """An outcome as an instruction: "raise ValueError" or "return 6.69"."""
    if "raises" in outcome:
        return f"raise {outcome['raises']}"
    return f"return {outcome['returns']}"


def difference_options(question, source, test_sources, root, mutant):
    """
    Two behaviours from an input where the code and the code with the planted
    change disagree, or None when no such input turns up.
    """
    function = question.get("function")
    if not (function and source and mutant):
        return None
    params = parameters(source, function)
    bases = [a for a, k in literal_calls(test_sources, function)
             if not k and params and len(a) == len(params)]
    if not bases:
        return None
    candidates = []
    for base in bases[:3]:
        candidates.append(list(base))
        for i, value in enumerate(base):
            for variant in _variants(value):
                args = list(base)
                args[i] = variant
                if args not in candidates:
                    candidates.append(args)
    candidates = candidates[:40]
    calls = [(function, args, {}) for args in candidates]
    now = start_probe.run_calls(question["path"], root, calls)
    changed = start_probe.run_calls(question["path"], root, calls, mutant=mutant)
    if not now or not changed:
        return None
    for args, a, b in zip(candidates, now, changed):
        if a != b:
            call = call_text(function, args)
            behaviours = [
                {"kind": BEHAVIOUR, "call": call, "args": args,
                 "function": function, "pins": a,
                 "label": f"{_verb(a)}, as your code does now"},
                {"kind": BEHAVIOUR, "call": call, "args": args,
                 "function": function, "pins": b,
                 "label": _verb(b)},
            ]
            prompt = f"What should {call} do?"
            return prompt, _shuffled(behaviours, question["question"])
    return None


def menu(question, source, test_sources, root, mutant=None):
    """
    (prompt line, options) for one question. The options always end with the
    decisions and free text, in a fixed order after the shuffled behaviours.
    """
    built = None
    kind = question.get("kind") or ""
    if question.get("edge"):
        built = boundary_options(question, source, test_sources, root)
    elif kind not in ("guard disabled", "raise swallowed"):
        built = difference_options(question, source, test_sources, root, mutant)
    if built is None:
        return None, [
            {"kind": SKIP, "label": "skip this question for now"},
            {"kind": OWN, "label": "type my own answer"},
        ]
    prompt, behaviours = built
    return prompt, behaviours + [
        {"kind": EITHER, "label": "either is fine, I do not mind"},
        {"kind": ASK, "label": "not mine to decide: save it to ask someone"},
        {"kind": OWN, "label": "type my own answer"},
    ]


def criterion(option, value=None):
    """The acceptance criterion a chosen behaviour saves, in qikly's words."""
    pins = option["pins"]
    if "raises" in pins:
        return f"{option['call']} raises {pins['raises']}"
    shown = value if value is not None else pins.get("returns")
    return f"{option['call']} returns {shown}"
