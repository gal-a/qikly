"""
Generated tests that can never fail.

On jambo, qikly's test agent wrote a test that called
`clear_ref_cache(namespace=None)` and then `assert True`. It passed whether the
call cleared anything or not, so a planted fault that broke the documented
behaviour went unnoticed. A test like that is worse than none: it looks like
coverage.

The check is narrow on purpose. A test is flagged only when it has at least
one assert and every assert in it is always true. A test with no assert at
all is left alone: it still fails if the call raises, which is what a "runs
without error" criterion asks. So is a test that calls a helper of the same
file holding an assert: the check is in the helper.

`strip` removes only the always-true asserts, for the last attempt of a
generation: one such test in a file of good ones should cost that one assert,
not the run.
"""
import ast

_CHECK_CALLS = ("raises", "warns", "fail", "approx")
# The validator's refusal says this, and the last attempt looks for it.
REFUSAL = "has a test that cannot fail"


def _always_true(test):
    """An assert test that holds whatever the code does."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    # A non-empty tuple, list, set or dict is true: `assert (f(), "msg")` is a
    # real model habit, and it checks nothing.
    if isinstance(test, (ast.Tuple, ast.List, ast.Set)):
        return bool(test.elts)
    if isinstance(test, ast.Dict):
        return bool(test.keys)
    if isinstance(test, (ast.Lambda, ast.JoinedStr)):
        return isinstance(test, ast.Lambda) or bool(test.values)
    # `x or True`: true whatever x is.
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(_always_true(v) for v in test.values)
    # `not False`, `not 0`.
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Constant) and not test.operand.value
    # `True == True`, `1 == 1`: two equal constants.
    if (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Eq, ast.Is))
            and isinstance(test.left, ast.Constant)
            and isinstance(test.comparators[0], ast.Constant)):
        return test.left.value == test.comparators[0].value
    return False


def _helpers_that_check(tree):
    """Names of the file's own functions, outside tests, that hold a real check."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("test"):
            asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            if any(not _always_true(a.test) for a in asserts) or any(
                    isinstance(n, ast.Raise) for n in ast.walk(node)):
                found.add(node.name)
    return found


def _has_other_check(node, helpers):
    """A pytest.raises / warns / fail, a unittest self.assert*, a mock's
    assert_called*, a raise, or a call to a helper of this file that checks."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise):
            return True
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _CHECK_CALLS or name.startswith("assert") or name in helpers:
                return True
    return False


def _tests(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            yield node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    yield item


def _vacuous(tree):
    helpers = _helpers_that_check(tree)
    for test in _tests(tree):
        asserts = [n for n in ast.walk(test) if isinstance(n, ast.Assert)]
        if not asserts or not all(_always_true(a.test) for a in asserts):
            continue
        if _has_other_check(test, helpers):
            continue
        yield test, asserts


def describe(source):
    """
    A sentence naming the first test that can never fail, or None. Source that
    does not parse is left to the syntax check.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for test, asserts in _vacuous(tree):
        shown = ast.unparse(asserts[0])
        return (f"{test.name} can never fail: its only check is `{shown}`. Check the "
                f"result against the value the criterion states, or, if the criterion "
                f"names none, delete the `{shown}`: a call with no assert still fails "
                f"if it raises")
    return None


def strip(source):
    """
    The source with each always-true assert of the flagged tests replaced, in
    place, by the calls it held (`assert (f() == 3, "msg")` becomes
    `(f() == 3, "msg")`, so f() still runs and still fails the test if it
    raises), or by `pass` when it held none. Only the assert's own span
    changes: `x = f(); assert True` keeps `x = f()`. The source unchanged if
    nothing is flagged.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    asserts = {(a.lineno, a.col_offset): a for _, found in _vacuous(tree) for a in found}
    if not asserts:
        return source
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    data = source.encode("utf-8")
    for _, node in sorted(asserts.items(), reverse=True):
        calls = any(isinstance(n, ast.Call) for n in ast.walk(node.test))
        keep = ast.get_source_segment(source, node.test) if calls else None
        # A kept expression over several lines needs brackets to stay valid.
        if keep and "\n" in keep and not keep.lstrip().startswith(("(", "[", "{")):
            keep = "(" + keep + ")"
        begin = starts[node.lineno - 1] + node.col_offset
        end = starts[node.end_lineno - 1] + node.end_col_offset
        data = data[:begin] + (keep or "pass").encode("utf-8") + data[end:]
    return data.decode("utf-8")
