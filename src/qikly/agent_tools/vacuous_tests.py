"""
Generated tests that can never fail.

On jambo, qikly's test agent wrote a test that called
`clear_ref_cache(namespace=None)` and then `assert True`. It passed whether the
call cleared anything or not, so a planted fault that broke the documented
behaviour went unnoticed. A test like that is worse than none: it looks like
coverage.

The check is narrow on purpose. A test is flagged only when it has at least
one assert and every assert in it is a constant that is always true. A test
with no assert at all is left alone: it still fails if the call raises, which
is what a "runs without error" criterion asks. Weak criteria are a separate
check (see qikly.spec_draft).
"""
import ast

_CHECK_CALLS = ("raises", "warns", "fail", "approx")


def _always_true(test):
    return isinstance(test, ast.Constant) and bool(test.value)


def _has_other_check(node):
    """A pytest.raises / warns / fail, a unittest self.assert*, a mock's
    assert_called*, or a raise: any of these lets the test fail."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise):
            return True
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _CHECK_CALLS or name.startswith("assert"):
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


def describe(source):
    """
    A sentence naming the first test that can never fail, or None. Source that
    does not parse is left to the syntax check.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for test in _tests(tree):
        asserts = [n for n in ast.walk(test) if isinstance(n, ast.Assert)]
        if not asserts or not all(_always_true(a.test) for a in asserts):
            continue
        if _has_other_check(test):
            continue
        shown = ast.unparse(asserts[0])
        return (f"{test.name} can never fail: its only check is `{shown}`. "
                f"Check the result against the expected value the criterion "
                f"states, or use pytest.raises for an error")
    return None
