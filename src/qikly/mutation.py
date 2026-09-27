"""
Deliberate faults, planted one at a time, so a suite can be scored.

Mutation testing is the oldest honest answer to "is this suite any good":
break the implementation in one known place, re-run the suite, and see whether
it notices. A suite that still passes has a gap at that exact point, and a
suite that fails has just proved it was testing something.

The operators live here, in the shipped package, because two callers need
them and they must not drift apart: `qikly --score-suite`, which gives a user
this measurement for their own task, and the research harness in
`research/mutation_test.py`, whose published results were produced by these
same swaps.

## The honest caveat, which belongs to the method and not to this code

Some mutants are semantically equivalent to the original and no test can catch
them. There is no general way to identify which, so a share of every "missed"
count is undetectable by construction, and a measured miss rate is an upper
bound rather than an estimate.
"""
import ast


# Swaps chosen to stay syntactically valid and to mirror the bug classes the
# findings taxonomy actually records: boundary conditions that are off by one
# inclusive/exclusive step (insufficient_strictness), inverted predicates, and
# constants that shift a threshold.
_CMP_SWAP = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
_BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


_NORMALISERS = {"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "title"}

# Two fault families, because they answer different questions.
#
# "arithmetic" perturbs existing computation: a comparison operator, a boolean
# connective, a constant. It is the classic mutation-testing set and it probes
# whether a suite pins down the logic it already covers.
#
# "validation" perturbs the code's strictness: it disables a guard, strips the
# anchors off a regex, drops a normalisation call, or swallows a raise. Those
# four map onto the finding categories the criteria-refinement loop actually
# produces (insufficient_strictness, parsing_looseness, domain_normalization,
# silent_failure), which the arithmetic family does not touch. Comparing
# refined criteria against arithmetic faults asks a question refinement was
# never about; this family is the one that matches the hypothesis.
FAMILIES = ("arithmetic", "validation")


def _is_guard(node):
    """An `if` that rejects, raises, skips or records a problem."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Raise, ast.Continue)):
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr == "append":
                return True
    return False


def _looks_like_regex(v):
    return isinstance(v, str) and ("^" in v or "$" in v) and any(
        t in v for t in ("\\d", "\\w", "\\s", "[", "+", "*", "(", "{"))


class _Mutator(ast.NodeTransformer):
    """Applies exactly the nth candidate mutation of one family, nothing else."""

    def __init__(self, target, family="arithmetic"):
        self.target = target
        self.family = family
        self.seen = -1
        self.applied = None

    def _hit(self, kind):
        self.seen += 1
        if self.seen == self.target:
            self.applied = kind
            return True
        return False

    # ------------------------------------------------------- arithmetic ----
    def visit_Compare(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_SWAP:
            old = type(node.ops[0])
            if self._hit(f"{old.__name__} -> {_CMP_SWAP[old].__name__}"):
                node.ops = [_CMP_SWAP[old]()]
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if type(node.op) in _BOOL_SWAP:
            old = type(node.op)
            if self._hit(f"{old.__name__} -> {_BOOL_SWAP[old].__name__}"):
                node.op = _BOOL_SWAP[old]()
        return node

    # ------------------------------------------------------- both ----------
    def visit_Constant(self, node):
        if self.family == "arithmetic":
            if isinstance(node.value, bool):
                if self._hit(f"bool {node.value} -> {not node.value}"):
                    return ast.copy_location(ast.Constant(value=not node.value), node)
            elif isinstance(node.value, int):
                if self._hit(f"int {node.value} -> {node.value + 1}"):
                    return ast.copy_location(ast.Constant(value=node.value + 1), node)
            return node

        # validation: a regex that no longer anchors matches substrings, so a
        # malformed value with a valid fragment inside it starts passing.
        if _looks_like_regex(node.value):
            loosened = node.value.lstrip("^").rstrip("$")
            if loosened != node.value and self._hit("regex anchors stripped"):
                return ast.copy_location(ast.Constant(value=loosened), node)
        return node

    # ------------------------------------------------------- validation ----
    def visit_If(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        if _is_guard(node):
            if self._hit("guard disabled"):
                node.test = ast.copy_location(ast.Constant(value=False), node.test)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        # x.strip() -> x, so one code path stops normalising while others do.
        if (isinstance(node.func, ast.Attribute) and node.func.attr in _NORMALISERS
                and not node.args and not node.keywords):
            if self._hit(f".{node.func.attr}() dropped"):
                return node.func.value
        return node

    def visit_Raise(self, node):
        if self.family != "validation":
            return node
        if self._hit("raise swallowed"):
            return ast.copy_location(ast.Pass(), node)
        return node


def count_sites(source, family="arithmetic"):
    tree = ast.parse(source)
    m = _Mutator(-1, family)
    m.visit(tree)
    return m.seen + 1


def make_mutant(source, index, family="arithmetic"):
    """Returns (mutated_source, description) or (None, None) if index is out of range."""
    tree = ast.parse(source)
    m = _Mutator(index, family)
    tree = m.visit(tree)
    if m.applied is None:
        return None, None
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree), m.applied
    except Exception:
        return None, None
