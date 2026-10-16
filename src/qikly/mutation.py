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
# Operators print as operators. These descriptions go straight into the report
# a user reads, and `GtE -> Gt` is a Python AST class name: the one time it
# mattered most it was describing a discount tier's `>=`, on the most valuable
# line in the report, in a notation only somebody who knows the ast module can
# read. The same report already says "guard disabled" in plain English.
_SYMBOL = {
    "Eq": "==", "NotEq": "!=", "Lt": "<", "LtE": "<=", "Gt": ">", "GtE": ">=",
    "Is": "is", "IsNot": "is not", "In": "in", "NotIn": "not in",
    "And": "and", "Or": "or",
}


def _reads_as(name):
    """The operator a reader would recognise, or the node name if unmapped."""
    return _SYMBOL.get(name, name)


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


_ANCHORED_CALLS = {"match": {"^"}, "fullmatch": {"^", "$"}}


def _is_re(node, attr):
    return (isinstance(node, ast.Attribute) and node.attr == attr
            and isinstance(node.value, ast.Name) and node.value.id == "re")


def _redundant_anchors(tree):
    """
    The anchors in each pattern constant that change nothing, by id of the
    constant: `^` on a pattern only ever given to `match`, which anchors at
    the start already, and `$` too for `fullmatch`. Stripping those planted a
    fault no test can catch, and asked a question nobody could answer: all
    five of validators' card patterns were reported missed for it.

    Only usage that can be read for certain counts: `re.match(P, ...)`,
    `re.compile(P).match(s)`, and a name bound to `re.compile(P)` whose every
    use in the module is `.match(s)` or `.fullmatch(s)`. Never with a start
    position, `.match(s, 2)`, where `^` does not match at all; and never a
    public module-level name, which another module may give to `.search`.
    """
    out = {}
    compiled = {}  # name -> constants compiled into it

    def from_start(call):
        """A compiled pattern's match from the start of the string."""
        return len(call.args) <= 1 and not any(k.arg in ("pos", "endpos")
                                               for k in call.keywords)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for attr, anchors in _ANCHORED_CALLS.items():
            if (_is_re(node.func, attr) and node.args
                    and isinstance(node.args[0], ast.Constant)):
                out[id(node.args[0])] = set(anchors)
            if (isinstance(node.func, ast.Attribute) and node.func.attr == attr
                    and isinstance(node.func.value, ast.Call)
                    and _is_re(node.func.value.func, "compile")
                    and node.func.value.args
                    and isinstance(node.func.value.args[0], ast.Constant)
                    and from_start(node)):
                out[id(node.func.value.args[0])] = set(anchors)
    module_level = {id(n) for n in tree.body} if isinstance(tree, ast.Module) else set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and _is_re(node.value.func, "compile") and node.value.args
                and isinstance(node.value.args[0], ast.Constant)):
            name = node.targets[0].id
            if id(node) in module_level and not name.startswith("_"):
                continue
            compiled.setdefault(name, []).append(node.value.args[0])
    if not compiled:
        return out
    # Every load of each name, and what it is used for.
    uses = {name: [] for name in compiled}
    methods = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in uses):
            methods.add(id(node.func.value))
            uses[node.func.value.id].append(node.func.attr if from_start(node) else None)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id in uses
                and isinstance(node.ctx, ast.Load) and id(node) not in methods):
            uses[node.id].append(None)  # passed on, returned: unknown use
    for name, constants in compiled.items():
        used = uses[name]
        if not used or any(u not in _ANCHORED_CALLS for u in used):
            continue
        anchors = set.intersection(*(_ANCHORED_CALLS[u] for u in used))
        for constant in constants:
            out[id(constant)] = anchors
    return out


class _Mutator(ast.NodeTransformer):
    """Applies exactly the nth candidate mutation of one family, nothing else."""

    def __init__(self, target, family="arithmetic"):
        self.target = target
        self.family = family
        self.seen = -1
        self.applied = None
        self.redundant = {}

    def visit_Module(self, node):
        self.redundant = _redundant_anchors(node)
        self.generic_visit(node)
        return node

    def _hit(self, kind, node=None):
        """Record the nth candidate, and where it is.

        The line number matters in the report rather than here. A module with
        two 100s in it produced two rows reading "int 100 -> 101", identically,
        and a reader handed that report cannot tell which line each refers to.
        Two rows that look the same look like a bug in the tool.
        """
        self.seen += 1
        if self.seen == self.target:
            line = getattr(node, "lineno", None)
            self.applied = "%s, line %d" % (kind, line) if line else kind
            return True
        return False

    # ------------------------------------------------------- arithmetic ----
    def visit_Compare(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_SWAP:
            old = type(node.ops[0])
            if self._hit(f"{_reads_as(old.__name__)} became {_reads_as(_CMP_SWAP[old].__name__)}", node):
                node.ops = [_CMP_SWAP[old]()]
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if type(node.op) in _BOOL_SWAP:
            old = type(node.op)
            if self._hit(f"{_reads_as(old.__name__)} became {_reads_as(_BOOL_SWAP[old].__name__)}", node):
                node.op = _BOOL_SWAP[old]()
        return node

    # ------------------------------------------------------- both ----------
    def visit_Constant(self, node):
        if self.family == "arithmetic":
            if isinstance(node.value, bool):
                if self._hit(f"bool {node.value} -> {not node.value}", node):
                    return ast.copy_location(ast.Constant(value=not node.value), node)
            elif isinstance(node.value, int):
                if self._hit(f"int {node.value} -> {node.value + 1}", node):
                    return ast.copy_location(ast.Constant(value=node.value + 1), node)
            return node

        # validation: a regex that no longer anchors matches substrings, so a
        # malformed value with a valid fragment inside it starts passing.
        if _looks_like_regex(node.value):
            redundant = self.redundant.get(id(node), set())
            loosened = node.value
            if "^" not in redundant:
                loosened = loosened.lstrip("^")
            if "$" not in redundant and loosened.endswith("$"):
                # Not an escaped `\$`, a literal dollar: stripping it left a
                # pattern ending in a lone backslash, which does not compile,
                # and that broken mutant counted as a fault caught.
                body = loosened[:-1]
                if (len(body) - len(body.rstrip("\\"))) % 2 == 0:
                    loosened = body
            if loosened != node.value and self._hit("regex anchors stripped", node):
                return ast.copy_location(ast.Constant(value=loosened), node)
        return node

    # ------------------------------------------------------- validation ----
    def visit_If(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        if _is_guard(node):
            if self._hit("guard disabled", node):
                node.test = ast.copy_location(ast.Constant(value=False), node.test)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        # x.strip() -> x, so one code path stops normalising while others do.
        if (isinstance(node.func, ast.Attribute) and node.func.attr in _NORMALISERS
                and not node.args and not node.keywords):
            if self._hit(f".{node.func.attr}() dropped", node):
                return node.func.value
        return node

    def visit_Raise(self, node):
        if self.family != "validation":
            return node
        if self._hit("raise swallowed", node):
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
