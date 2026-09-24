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
    """
    Every name this statement binds in the scope it sits in.

    Not what it binds anywhere. A walk descends into a nested def or class, so
    using one here made `EXPECTED = 42` inside a helper class a binding of the
    test function around it, and a method reading a bare `EXPECTED` then looked
    legal even after class bodies were correctly taken out of the lookup chain.
    That is the same mistake `_module_level_names` and `_loaded_by` each had
    before it, which is three appearances of one habit in one file.

    A definition contributes its name and nothing else.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}

    names = set()
    for child in _walk_this_scope(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
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
        elif isinstance(child, ast.NamedExpr):
            # `total = (n := f()) + n` binds n while the statement is still
            # being evaluated, so the later read is legal. Loads are collected
            # for a whole statement before its bindings are added, which made
            # this look like a use before assignment.
            for target in ast.walk(child.target):
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _walk_this_scope(node):
    """
    Every node belonging to this scope, not descending into a nested one.

    A `def` or `class` inside a test opens a scope of its own. Its parameters
    are not the enclosing function's names, and its body may legally read
    something the enclosing function binds later, because a closure resolves
    when it is called rather than when it is written. Walking flat through it,
    which `ast.walk` does, reported both as errors.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in ast.iter_child_nodes(current):
            # A lambda body resolves when it is called, exactly like a nested
            # def, so `f = lambda: LATER` followed by `LATER = 5` is legal and
            # was being reported. The first of the two conditions this replaces
            # was dead: a node is never its own descendant.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            stack.append(child)


def _loaded_by(node):
    """
    Every name this statement reads, with the line it reads it on.

    Excluding the ones bound in a scope of their own inside it.
    """
    skip = _own_scope_names(node)
    found = []
    for child in _walk_this_scope(node):
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
    # A class body has no parameters. It is still a scope, so it is checked
    # like one, and asking it for arguments was an AttributeError.
    args = getattr(func, "args", None)
    if args is None:
        return set()
    names = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


# Statements whose body may run more than once, or out of order, so a name
# bound inside one can legitimately be read before the binding is reached in
# source order. Anything containing one of these is left alone entirely.
_REORDERING = tuple(
    node for node in (
        ast.For, ast.AsyncFor, ast.While, ast.Try, ast.If, ast.With,
        ast.AsyncWith,
        # `match` has the same shape as `if`: one branch runs and the others
        # bind nothing. It also binds through MatchAs.name rather than a Name
        # node, so nothing here would register the capture as a binding even
        # if the ordering were followed.
        getattr(ast, "Match", None),
        getattr(ast, "TryStar", None),
    ) if node is not None)


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

    for node in tree.body:
        # Classes too. A helper or a fake defined beside the tests used to be
        # skipped here, so nothing in it was ever checked.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _check_scope(node, set(module_names), node.name, problems)

    return problems


def _check_scope(scope, outer_bound, label, problems):
    """
    One function or class body, read in the order Python evaluates it.

    `outer_bound` is everything the enclosing scopes bind, with no ordering,
    because a nested function resolves names when it is called and may
    therefore read something its enclosing function binds further down. What it
    may not read is a name nothing binds anywhere, which is the typo this
    catches and which skipping nested definitions entirely had stopped
    catching.
    """
    # One control-flow statement anywhere in this scope and it stops looking
    # here. A body that builds a fixture and calls the code under test is
    # straight-line, which is the shape worth checking. Nested scopes are
    # still checked on their own terms.
    reordering = any(isinstance(n, _REORDERING)
                     for n in _walk_this_scope(scope))

    # Everything this scope binds, anywhere in it, for the benefit of scopes
    # nested inside it.
    everything_here = set()
    for statement in scope.body:
        everything_here |= _bound_by(statement)

    bound = set(outer_bound) | _parameters(scope)

    # What a scope nested inside this one can see. A function's locals are
    # visible to functions defined inside it, at any point, because a closure
    # resolves when it is called. A CLASS body's names are not: Python leaves
    # the class body out of the chain its own methods look through, so a method
    # reading a bare class attribute raises NameError and must say self.NAME.
    # Passing them down made exactly that error read as legal.
    if isinstance(scope, ast.ClassDef):
        inner_outer = set(outer_bound)
    else:
        inner_outer = set(outer_bound) | _parameters(scope) | everything_here

    for statement in scope.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
            # Its name is available here from this point; its body is checked
            # against the enclosing bindings without ordering.
            bound |= _bound_by(statement)
            _check_scope(statement, inner_outer,
                         "%s.%s" % (label, statement.name), problems)
            continue

        if not reordering:
            for name, line in _loaded_by(statement):
                if name not in bound:
                    problems.append((label, name, line))
        bound |= _bound_by(statement)


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
