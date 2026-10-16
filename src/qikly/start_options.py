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
- **Where the line's own function has no test call**, the public functions
  and classes the tests call are tried, and only a call that ran the line
  counts. A check switched off and an error never raised get the same search.
- **Where nothing works**, a comparison whose edge is not known, or no call
  that reaches the line, the menu offers only "skip this question for now"
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


def path_module(path, root):
    """
    A module named by its path from the project root, `lib.a.util`, whether
    or not its folders are packages. For matching imports only: two `util`
    modules in folders without `__init__.py` both had the dotted name `util`,
    and one's test calls were offered for the other.
    """
    import os
    rel = os.path.relpath(os.path.splitext(os.path.abspath(path))[0], os.path.abspath(root))
    return rel.replace(os.sep, ".").replace("/", ".")


def _names_for(tree, function, module):
    """
    The names a test file calls `function` by. `from lib.a.util import scale
    as a_scale` calls it `a_scale`, which matching on the bare name missed,
    and two modules' `scale` must not be mixed up: when the file imports the
    function by name, only imports from `module` (its dotted name) count.
    """
    imported, matching = False, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == function:
                    imported = True
                    source = node.module or ""
                    # Or the package above it, which re-exports it: isodate's
                    # tests import parse_date from isodate, not isodate.isodates.
                    if (module is None or source == module
                            or module.endswith("." + source)
                            or source.endswith("." + module)
                            or ("." + module).find("." + source + ".") >= 0):
                        matching.add(alias.asname or alias.name)
    if not imported:
        return {function}
    return matching


def _value(node, known):
    """A literal, or a name bound to one earlier in the same test."""
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    return ast.literal_eval(node)


def _module_literals(tree):
    """
    Module-level `NAME = <value>`, as the expression itself, such as a table
    of parametrize rows. Kept unevaluated: isodate's rows hold `date(...)`
    beside the strings, and evaluating the whole table threw out every row.
    """
    out = {}
    for node in tree.body:
        # inflection annotates its tables, `ROWS: TestParameters = (...)`.
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name):
            out[target.id] = value
    return out


_NOT_LITERAL = object()


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NOT_LITERAL


ROWS_READ = 8


def _parametrize_rows(func, module_level):
    """How many rows a test's parametrize tables give, up to ROWS_READ."""
    most = 1
    for deco in func.decorator_list:
        if (isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "parametrize"
                and len(deco.args) >= 2):
            rows_node = deco.args[1]
            if isinstance(rows_node, ast.Name):
                rows_node = module_level.get(rows_node.id)
            if isinstance(rows_node, (ast.List, ast.Tuple)):
                most = max(most, len(rows_node.elts))
    return min(most, ROWS_READ)


def _parametrized(func, module_level, row=0):
    """
    A test's parameters bound to one row of its `pytest.mark.parametrize`,
    which is how most real suites pass inputs: inflection and slugify both do,
    with the rows in a module-level list, and no call had a literal argument.
    Each value is read on its own, so a row with a `date(...)` in it still
    gives its strings and numbers; `pytest.param(...)` rows are unwrapped.
    Every row up to ROWS_READ is a call: the first alone never reached
    isodate's six-digit years, which start further down its table.
    """
    for deco in func.decorator_list:
        if not (isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "parametrize"
                and len(deco.args) >= 2):
            continue
        if any(k.arg == "indirect" for k in deco.keywords):
            # The rows go to fixtures, which may turn them into anything.
            continue
        names = _literal(deco.args[0])
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",") if n.strip()]
        if not isinstance(names, (list, tuple)) or not names:
            continue
        rows_node = deco.args[1]
        if isinstance(rows_node, ast.Name):
            rows_node = module_level.get(rows_node.id)
        if not isinstance(rows_node, (ast.List, ast.Tuple)) or not rows_node.elts:
            continue
        first = rows_node.elts[row % len(rows_node.elts)]
        if isinstance(first, ast.Call) and getattr(first.func, "attr", "") == "param":
            if len(names) > 1:
                first = ast.Tuple(elts=list(first.args), ctx=ast.Load())
            else:
                first = first.args[0] if first.args else None
        if first is None:
            continue
        if len(names) == 1:
            values = [first]
        elif isinstance(first, (ast.List, ast.Tuple)):
            values = list(first.elts)
        else:
            continue
        if len(values) != len(names):
            continue
        for name, node in zip(names, values):
            value = _literal(node)
            if value is not _NOT_LITERAL:
                yield name, value


def _bindings(func, module_level, row, call):
    """
    Names bound to a literal, once, in `func`, the test holding `call`, with
    its parametrize names bound to `row`. Real suites pass inputs through
    variables, `txt = "..."` then `slugify(txt)`, and reading only literal
    arguments found no call at all in four real libraries. A name bound more
    than once is left out: which value reached the call would be a guess.
    """
    out = dict(_parametrized(func, module_level, row))
    seen = {name: 1 for name in out}
    # Every binding counts, not only `name = value`: `txt += " b"`, a loop
    # or `with` target, or `txt, n = ...` each changes what reaches the
    # call, and reading only the plain assignment named a call no test made.
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor,
                               ast.comprehension, ast.NamedExpr)):
            targets = [node.target]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            targets = [i.optional_vars for i in node.items if i.optional_vars]
        else:
            targets = []
        for target in targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name):
                    seen[name.id] = seen.get(name.id, 0) + 1
        # A plain assignment made before the call is the value it gets.
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.lineno < getattr(call, "lineno", 0)):
            value = _literal(node.value)
            if value is not _NOT_LITERAL:
                out[node.targets[0].id] = value
    return {k: v for k, v in out.items() if seen.get(k) == 1}


def _owners(tree):
    """{id of each call: the outermost test function holding it}, built once."""
    owner = {}
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(func):
                if isinstance(node, ast.Call):
                    owner.setdefault(id(node), func)
    return owner


def _literals_around(tree, call, row=0):
    """The literal bindings around `call` in `tree`, for one parametrize row."""
    func = _owners(tree).get(id(call))
    return _bindings(func, _module_literals(tree), row, call) if func else {}


def _rows_for(tree, call):
    """How many parametrize rows the test holding `call` runs, up to ROWS_READ."""
    func = _owners(tree).get(id(call))
    return _parametrize_rows(func, _module_literals(tree)) if func else 1


_CALLS = {}


def literal_calls(test_sources, function, module=None):
    """
    The calls of `function` in the tests whose arguments are all literals, as
    (args, kwargs), in the order they appear. These are the inputs the user
    already chose, so building on them never invents a scenario. `module`,
    the function's dotted module name, keeps same-named functions apart.
    Kept per sources, function and module: one menu asked for the same
    calls dozens of times, and a large suite took over half a minute.
    """
    key = (tuple(test_sources), function, module)
    if key not in _CALLS:
        if len(_CALLS) > 256:
            _CALLS.clear()
        _CALLS[key] = _literal_calls(test_sources, function, module)
    return [(list(a), dict(k)) for a, k in _CALLS[key]]


def _literal_calls(test_sources, function, module):
    found = []
    for source in test_sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        names = _names_for(tree, function, module)
        module_level = _module_literals(tree)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name):
                ok = callee.id in names
            elif isinstance(callee, ast.Attribute):
                ok = callee.attr == function
            else:
                ok = False
            if not ok:
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            func = owner.get(id(node))
            rows = _parametrize_rows(func, module_level) if func else 1
            for row in range(rows):
                known = _bindings(func, module_level, row, node) if func else {}
                try:
                    args = [_value(a, known) for a in node.args]
                    kwargs = {k.arg: _value(k.value, known)
                              for k in node.keywords if k.arg}
                except (ValueError, TypeError, SyntaxError):
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
    node = _callable(source, function)
    if node is None:
        return None
    a = node.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    if getattr(node, "_is_init", False):
        positional = positional[1:]
    return positional, [x.arg for x in a.kwonlyargs]


def _callable(source, name):
    """
    The top-level function called `name`, or the `__init__` of the top-level
    class called `name`, marked so its `self` is left out. A class is called
    to build one: semantic_version's tests build `Version('1.0.0')`, and every
    question about its parsing was text-only without it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    # A class's own __init__, or the first one up its bases in this module:
    # semantic_version's SimpleSpec takes BaseSpec's.
    seen, todo = set(), [name]
    while todo:
        current = todo.pop(0)
        if current in seen or current not in classes:
            continue
        seen.add(current)
        for item in classes[current].body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                item._is_init = True
                return item
        todo += [b.id for b in classes[current].bases if isinstance(b, ast.Name)]
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
    node = _callable(source, function)
    if node is None:
        return {}
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


def _usable_calls(test_sources, function, positional, keyword_only, module=None):
    known = set(positional) | set(keyword_only)
    return [(a, k) for a, k in literal_calls(test_sources, function, module)
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
    bases = _usable_calls(test_sources, function, positional, keyword_only,
                          path_module(question["path"], root))
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
    if all("raises" not in o for o in outcomes) and all(
            _is_category(o["returns"]) for o in outcomes):
        # A category on each side, such as 'B' at 89 and 'A' at 91: which one
        # the edge belongs to is the whole decision, so both are offered as
        # they are, the current neighbour's value labelled.
        behaviours = [
            {"kind": BEHAVIOUR, "call": call, "args": built[0][0],
             "kwargs": built[0][1], "function": function,
             "pins": {"returns": o["returns"]},
             "label": f"return {o['returns']}, as {variable} {v!r} does now"}
            for v, o in ((below, outcomes[0]), (above, outcomes[1]))]
        return prompt, _shuffled(behaviours, question["question"])
    if all("raises" not in o for o in outcomes):
        # Both sides return a number, so "return a value, as 9 does" and
        # "return a value, as 11 does" were two options that both led to the
        # same question, and the right number may be neither. One option,
        # with both neighbours shown, is clearer.
        context = (f"{variable} {below!r} returns {outcomes[0]['returns']} now, "
                   f"and {variable} {above!r} returns {outcomes[1]['returns']}")
        return prompt, [{"kind": BEHAVIOUR, "call": call, "args": built[0][0],
                         "kwargs": built[0][1], "function": function,
                         "pins": {"returns": None, "like": outcomes[0]["returns"]},
                         "label": f"type the value it should return ({context})"}]
    return prompt, _shuffled(behaviours, question["question"])


def _is_category(text):
    """
    A value that names a category, a string, True, False or None, so pinning
    the neighbour's is a real choice. Anything else, numbers and also values
    whose repr is not a literal such as Decimal('9.9'), goes to "type the
    value": pinning a neighbour's Decimal saved the wrong amount as an answer.
    """
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        return False
    return isinstance(value, (str, bool)) or value is None


def _is_number(text):
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        return False
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
        if re.search(r"[/\\]", value) or re.fullmatch(r"[\w.-]+\.[A-Za-z]\w{0,4}", value):
            # A path is left as the tests gave it: `out.txt` + "x" made a
            # function write a new file beside the user's own.
            return []
        out = [value.upper(), f" {value} ", value.capitalize(), value + "x"]
        return [v for v in out if v != value]
    return []


def _verb(outcome):
    """An outcome as an instruction: "raise ValueError" or "return 6.69"."""
    if "raises" in outcome:
        return f"raise {outcome['raises']}"
    return f"return {outcome['returns']}"


def _public_functions(source):
    """
    The module's top-level public functions, and its public classes that
    take arguments to build, in the order they appear.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [n.name for n in tree.body
            if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                or isinstance(n, ast.ClassDef) and _callable(source, n.name) is not None)
            and not n.name.startswith("_")]


def _readable(a, b):
    """
    The two outcomes in words that can be compared, or (None, None). A repr
    holding a memory address, `<Spec object at 0x...>`, differs on every run,
    so two of them say nothing; one beside a raise is still a real
    difference, and reads as "a Spec object".
    """
    def plain(o):
        if "returns" in o and _ADDRESS.search(o["returns"]):
            return dict(o, returns=_ADDRESS.sub(lambda m: "a %s object" % m.group(1).split(".")[-1],
                                                o["returns"]))
        return o
    held = [o for o in (a, b) if "returns" in o and _ADDRESS.search(o["returns"])]
    if not held:
        return a, b
    if len(held) == 2:
        return None, None
    return plain(a), plain(b)


_IO = re.compile(r"\bopen\(|\bos\.|\bshutil\.|\bPath\(|\.write\w*\(|\bsubprocess\.|\bsocket\.")


def _does_io(source, name):
    """Whether a top-level function's or class's own code touches files or the system."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    node = next((n for n in tree.body if isinstance(
        n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name), None)
    if node is None:
        return False
    try:
        text = ast.get_source_segment(source, node) or ""
    except Exception:
        return True
    return bool(_IO.search(text))


def difference_options(question, source, test_sources, root, mutant):
    """
    Two behaviours from an input where the code and the code with the planted
    change disagree, or None when no such input turns up.

    The function the line is in is tried first, from the calls the tests make
    of it. Where it has none, which is what a private helper looks like, the
    public functions the tests do call are tried instead: on real libraries
    most missed faults sat in helpers such as slugify's `_modern_truncate`,
    reached only through `slugify(...)`, and no question offered an answer.
    """
    if not (source and mutant):
        return None
    module = path_module(question["path"], root)
    function = question.get("function")
    rounds = []
    if function:
        rounds.append([(function, a, k) for a, k in
                       _candidates(source, test_sources, function, module, 60)])
    # Then through the public functions, sharing the 60 calls between them,
    # leaving out any that reads or writes files or the system: a question
    # about a helper ran `save(path)` and wrote next to the user's data.
    public = [f for f in _public_functions(source)
              if f != function and not _does_io(source, f)]
    share = max(5, 60 // max(len(public), 1))
    rounds.append([(name, a, k) for name in public
                   for a, k in _candidates(source, test_sources, name, module, share)][:60])
    for through, calls in enumerate(rounds, 1 if function else 2):
        found = _first_difference(question, function, calls, root, mutant,
                                  through=through == 2)
        if found:
            return found
    return None


_ADDRESS = re.compile(r"<([\w.]+) object at 0x[0-9A-Fa-f]+>")


def _first_difference(question, function, calls, root, mutant, through=False):
    """
    The menu for the first of `calls` whose outcome the change alters. Through
    another function, only a call that ran the question's line counts: any
    difference there might come from somewhere else, and the prompt says the
    call runs through the line.
    """
    if not calls:
        return None
    result = start_probe.run_calls(question["path"], root, calls, mutant=mutant,
                                   line=question.get("line") if through else None)
    if not result:
        return None
    now, changed_outcomes = result[0], result[1]
    reached = result[2] if through else [True] * len(calls)
    for (name, args, kwargs), a, b, ran in zip(calls, now, changed_outcomes, reached):
        if not ran or a == b:
            continue
        a, b = _readable(a, b)
        if a is not None:
            call = call_text(name, args, kwargs)
            behaviours = [
                {"kind": BEHAVIOUR, "call": call, "args": args, "kwargs": kwargs,
                 "function": name, "pins": a,
                 "label": f"{_verb(a)}, as your code does now"},
                {"kind": BEHAVIOUR, "call": call, "args": args, "kwargs": kwargs,
                 "function": name, "pins": b,
                 "label": _verb(b)},
            ]
            prompt = f"What should {call} do?"
            if name != function:
                # Said, so the call is not mistaken for the line's own.
                prompt += (f" (It runs through {function or 'this line'}, "
                           f"line {question.get('line')}.)")
            return prompt, _shuffled(behaviours, question["question"])
    return None


def _candidates(source, test_sources, function, module, limit):
    """
    The calls of `function` to try: the tests' own calls, then each with one
    argument changed, then a changed default with one other change.
    """
    found = signature(source, function)
    if not found:
        return []
    positional, keyword_only = found
    bases = _usable_calls(test_sources, function, positional, keyword_only, module)
    if not bases:
        return []
    candidates = []
    for base in bases[:3]:
        first = (list(base[0]), dict(base[1]))
        if first not in candidates:
            candidates.append(first)
        # And the call with an argument that has a default left out: a
        # changed default only shows on a call that does not pass it, and
        # isodate's tests pass yeardigits every time.
        defaults = literal_defaults(source, function)
        args, kwargs = first
        while args and len(args) <= len(positional) and positional[len(args) - 1] in defaults:
            args = args[:-1]
            if (list(args), dict(kwargs)) not in candidates:
                candidates.append((list(args), dict(kwargs)))
        for name in [k for k in first[1] if k in defaults]:
            dropped = (list(first[0]), {k: v for k, v in first[1].items() if k != name})
            if dropped not in candidates:
                candidates.append(dropped)
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
    return candidates[:limit]


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
    elif _on_a_comparison(question, source):
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
        {"kind": ASK, "label": "save it (no decision now, maybe later)"},
        {"kind": OWN, "label": "type my own answer"},
    ]


def criterion(option, value=None):
    """The acceptance criterion a chosen behaviour saves, in qikly's words."""
    pins = option["pins"]
    if "raises" in pins:
        return f"{option['call']} raises {pins['raises']}"
    shown = value if value is not None else pins.get("returns")
    return f"{option['call']} returns {shown}"
