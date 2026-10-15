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
import re

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


def signature(source, function):
    """
    (positional names, keyword-only names) of a top-level function, or None.
    Test calls often leave out an argument that has a default, or pass one by
    keyword, so both kinds are needed to rebuild a call.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            a = node.args
            return [x.arg for x in a.posonlyargs + a.args], [x.arg for x in a.kwonlyargs]
    return None


def parameters(source, function):
    """The positional parameter names of a top-level function, or None."""
    found = signature(source, function)
    return found[0] if found else None


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


def constant_value(source, name):
    """A module-level `NAME = <number>`, so `FREE_SHIPPING_THRESHOLD` has a value."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    found = ast.literal_eval(node.value)
                except (ValueError, SyntaxError, TypeError):
                    found = None
    return found


def _neighbours(edge, source=None):
    try:
        value = ast.literal_eval(edge)
    except (ValueError, SyntaxError):
        value = (constant_value(source, edge)
                 if source and edge.isidentifier() else None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    step = 1 if isinstance(value, int) else 0.01
    return value, round(value - step, 10), round(value + step, 10)


def _with(base, positional, keyword_only, name, value):
    """A test call's (args, kwargs) with one argument set, wherever it goes."""
    args, kwargs = list(base[0]), dict(base[1])
    if name in kwargs or name in keyword_only:
        kwargs[name] = value
    elif name in positional and positional.index(name) < len(args):
        args[positional.index(name)] = value
    elif name in positional:
        kwargs[name] = value
    else:
        return None
    return args, kwargs


def literal_defaults(source, function):
    """{name: default} for the arguments of a function whose default is a literal."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            a = node.args
            named = a.posonlyargs + a.args
            pairs = list(zip(named[len(named) - len(a.defaults):], a.defaults))
            pairs += [(x, d) for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            out = {}
            for arg, default in pairs:
                try:
                    out[arg.arg] = ast.literal_eval(default)
                except (ValueError, SyntaxError, TypeError):
                    pass
            return out
    return {}


def _usable_calls(test_sources, function, positional, keyword_only):
    known = set(positional) | set(keyword_only)
    return [(a, k) for a, k in literal_calls(test_sources, function)
            if len(a) <= len(positional) and set(k) <= known]


def boundary_options(question, source, test_sources, root):
    """
    Two behaviours for a boundary, from the code run on either side of it,
    or None when they cannot be built honestly.
    """
    function, edge = question.get("function"), question.get("edge")
    if not (function and edge and source):
        return None
    variable = _boundary_variable(source, question.get("line"), edge)
    found = signature(source, function)
    near = _neighbours(edge, source)
    if not (variable and found and near):
        return None
    positional, keyword_only = found
    if variable not in positional and variable not in keyword_only:
        return None
    bases = _usable_calls(test_sources, function, positional, keyword_only)
    if not bases:
        return None
    at, below, above = near
    built = [_with(bases[0], positional, keyword_only, variable, v)
             for v in (at, below, above)]
    if None in built:
        return None
    outcomes = start_probe.run_calls(question["path"], root,
                                     [(function, built[1][0], built[1][1]),
                                      (function, built[2][0], built[2][1])])
    if not outcomes or outcomes[0] == outcomes[1]:
        return None
    call = call_text(function, built[0][0], built[0][1])
    shown_edge = edge if edge == repr(at) else f"{edge} ({at!r})"
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
                           "pins": pins, "args": built[0][0],
                           "kwargs": built[0][1], "function": function})
    prompt = (f"Your tests never try {variable} at exactly {shown_edge}. "
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
    found = signature(source, function)
    if not found:
        return None
    positional, keyword_only = found
    bases = _usable_calls(test_sources, function, positional, keyword_only)
    if not bases:
        return None
    candidates = []
    for base in bases[:3]:
        first = (list(base[0]), dict(base[1]))
        if first not in candidates:
            candidates.append(first)
        names = positional[:len(base[0])] + list(base[1])
        # And the arguments the call left at their default: a branch behind
        # `express=False` is only reached by trying `express=True`.
        defaults = literal_defaults(source, function)
        names += [n for n in defaults if n not in names]
        for name in names:
            if name in base[1]:
                current = base[1][name]
            elif name in positional and positional.index(name) < len(base[0]):
                current = base[0][positional.index(name)]
            else:
                current = defaults[name]
            for variant in _variants(current):
                changed = _with(base, positional, keyword_only, name, variant)
                if changed and changed not in candidates:
                    candidates.append(changed)
        # Then a changed default with each other single change, for a branch
        # that needs both, such as express=True with a foreign country.
        for name in [n for n in defaults if n not in base[1]]:
            for variant in _variants(defaults[name]):
                flipped = _with(base, positional, keyword_only, name, variant)
                if not flipped:
                    continue
                for other in names:
                    if other == name or other in defaults and other not in base[1]:
                        continue
                    if other in base[1]:
                        value = base[1][other]
                    else:
                        value = base[0][positional.index(other)]
                    for v in _variants(value):
                        both = _with(flipped, positional, keyword_only, other, v)
                        if both and both not in candidates:
                            candidates.append(both)
    candidates = candidates[:60]
    calls = [(function, a, k) for a, k in candidates]
    result = start_probe.run_calls(question["path"], root, calls, mutant=mutant)
    if not result:
        return None
    now, changed_outcomes = result
    for (args, kwargs), a, b in zip(candidates, now, changed_outcomes):
        if a != b:
            call = call_text(function, args, kwargs)
            behaviours = [
                {"kind": BEHAVIOUR, "call": call, "args": args, "kwargs": kwargs,
                 "function": function, "pins": a,
                 "label": f"{_verb(a)}, as your code does now"},
                {"kind": BEHAVIOUR, "call": call, "args": args, "kwargs": kwargs,
                 "function": function, "pins": b,
                 "label": _verb(b)},
            ]
            prompt = f"What should {call} do?"
            return prompt, _shuffled(behaviours, question["question"])
    return None


_COMPARISON = re.compile(r"^(<=|<|>=|>|==|!=|is not|is|not in|in) became ")


def _on_a_comparison(question, source):
    """
    Whether a planted change sits in a comparison whose edge was not
    recorded: a chained `0 <= rate <= 100`, the same operator twice on one
    line, or a constant nudged inside a comparison. A search for the input
    where the two versions differ would then find the edge itself, and
    offering "what your code does now" there reads the answer off the code.
    """
    kind = question.get("kind") or ""
    if _COMPARISON.match(kind):
        return True
    if kind.startswith("int ") and source and question.get("line"):
        lines = source.splitlines()
        line = question["line"]
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        return bool(re.search(r"[<>]=?|==|!=", text))
    return False


def menu(question, source, test_sources, root, mutant=None):
    """
    (prompt line, options) for one question. The options always end with the
    decisions and free text, in a fixed order after the shuffled behaviours.
    """
    built = None
    kind = question.get("kind") or ""
    if question.get("edge"):
        built = boundary_options(question, source, test_sources, root)
    elif kind in ("guard disabled", "raise swallowed") or _on_a_comparison(question, source):
        built = None
    else:
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
