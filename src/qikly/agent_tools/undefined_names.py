"""
A generated test that reads a name before it exists, found before it is run.

The defect this catches, verbatim from a run that exhausted its whole budget:

    rows = [
        {"station_id": "S1", "temp_c": "-1.0", ...},
        {"station_id": "S1", "temp_c": "3.8", ...},
    ]
    records = transform(records)

`rows` is built and never used; `transform` is handed `records`, which does not
exist yet. Every call raises NameError, so the test fails identically on every
iteration, and the coding agent spends eleven repair attempts on a file whose
problem is not in its code at all. `_validate_generated_tests` already exists
to stop exactly that, and already says so in its docstring. It caught syntax
errors and empty files and not this.

## Why a deliberately narrow check

It reads the statements of a test function in order, in the order Python
evaluates them, and reports a name that is loaded before anything has bound it.
Inside a loop, a branch or a `try`, it reports nothing: a name bound at the end
of a loop body is legitimately available on the next pass, and a checker that
does not know that produces false positives on correct tests. A false positive
here throws away a usable suite and spends another generation call, so the
check only fires where the answer is not in doubt.

It is also not a type checker and not pyflakes. It looks for one mistake, the
one seen in real output, and leaves everything else to pytest.
"""
import ast
import builtins


def _bound_by(node):
    """Every name this statement binds, once it has finished executing."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            names.update(child.names)
    return names


def _own_scope_names(node):
    """
    Names bound inside a scope of their own within this statement.

    A comprehension's targets and a lambda's parameters exist only inside the
    comprehension or lambda, so they are read and bound in the same expression
    and an enclosing statement never sees either. Reading the statement flat
    makes every one of them look like a use before assignment: the first
    version of this check flagged 86 of 509 real generated files, and nearly
    all of them were `for r in ...` inside an `all(...)`.
    """
    names = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in child.generators:
                for target in ast.walk(generator.target):
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        elif isinstance(child, ast.Lambda):
            names |= _parameters(child)
    return names


def _loaded_by(node):
    """
    Every name this statement reads, with the line it reads it on.

    Excluding the ones bound in a scope of their own inside it.
    """
    skip = _own_scope_names(node)
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            if child.id in skip:
                continue
            found.append((child.id, getattr(child, "lineno", None)))
    return found


def _module_level_names(tree):
    """
    Names the module binds, not counting anything local to a function.

    `_bound_by` walks, and a walk descends into function bodies, so using it
    here made every local variable of every test a module-level name. The
    checker then found nothing, anywhere, and scanned 503 real files clean.
    A guard that reports success while checking nothing is worse than no guard,
    so this binds a function or class by its name only and never looks inside.
    """
    names = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            # Decorators and default arguments are evaluated at module level,
            # but they bind nothing, so there is nothing further to collect.
            continue
        names |= _bound_by(node)
    return names


def _parameters(func):
    args = func.args
    names = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


# Statements whose body may run more than once, or out of order, so a name
# bound inside one can legitimately be read before the binding is reached in
# source order. Anything containing one of these is left alone entirely.
_REORDERING = (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.If,
               ast.With, ast.AsyncWith)


def undefined_uses(source):
    """
    Names read before anything binds them, as (function, name, line) triples.

    Empty when the source is fine, or when it is too tangled to judge without
    guessing. Raises nothing: a file that will not parse is the other check's
    business.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    module_names = _module_level_names(tree)
    problems = []

    for func in tree.body:
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # One control-flow statement anywhere in the function and this stops
        # looking. Test functions that build a fixture and call the code under
        # test are straight-line, which is the shape worth checking.
        if any(isinstance(n, _REORDERING) for n in ast.walk(func)):
            continue

        bound = set(module_names) | _parameters(func)
        for statement in func.body:
            for name, line in _loaded_by(statement):
                if name not in bound:
                    problems.append((func.name, name, line))
            bound |= _bound_by(statement)

    return problems


def describe(source):
    """
    One sentence naming what to fix, or None.

    Written for a retry prompt and for a log line, so it names the function and
    the variable rather than pointing at a line number the model cannot see.
    """
    problems = undefined_uses(source)
    if not problems:
        return None
    first = problems[0]
    detail = "%s() reads %r before anything assigns it" % (first[0], first[1])
    if len(problems) > 1:
        detail += ", and %d other name%s like it" % (
            len(problems) - 1, "" if len(problems) == 2 else "s")
    return detail
