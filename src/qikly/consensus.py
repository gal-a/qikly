# -*- coding: utf-8 -*-
"""
Generate a stage's suite more than once, and keep the draft the others agree
with.

The failure this exists for is measured rather than imagined. On a bundled
following-distance task whose criterion says a headway of exactly 2.00 seconds
raises no warning, seven runs in ten wrote a test that warns at 2.00 anyway.
The coding agent then cannot win: it sees only failure output, so it cannot
tell a wrong test from a right one, and it flips the comparison back and forth
until the run stops. The whole budget goes on a fault that was in the tests.

`check_suites` attacks that after the fact, with a model call that reads the
suite against the criteria. This attacks it from the other end and without an
extra kind of call: draw k samples of the same stage, and where they disagree
about what a criterion requires, prefer the reading most of them took. A model
that writes the wrong boundary seven times in ten writes the right one three
times in ten, and three samples make that visible.

**What is compared, and why it is the whole test body.** Two drafts differ in
test names, ordering, variable names and comments, none of which change what
is being tested. So each test is reduced to the normalised form of every
statement in it, with local variable names replaced but callees, attributes
and literals kept, and grouped by the criterion the test says it came from,
which is the label `qikly.traceability` reads.

The first version compared only the `assert` statements and was blind to the
ordinary arrange-act-assert shape, where the value the test is about sits in
the call rather than the assertion: `r = check(2.00)` and `r = check(1.50)`
followed by the same assert compared as agreement.

**What it still gets wrong, and it is worth knowing before trusting a count.**
Comparison is structural, so drafts that mean the same thing in different
shapes read as disagreement: `x == 2.0` against `2.0 == x`, a loop against the
same cases unrolled, `assert not flagged` against `assert flagged is False`,
a tuple against a list. These inflate the contested list with noise. They do
not cause false agreement, which is the direction that would matter.

**The honest limit, and it is not small.** Agreement is not correctness. Three
samples of one model at one temperature agree for the same reason a single
model's code and tests agree, which is the failure this project exists to
name. Sampling across providers would be real independence; sampling one
provider three times is a weaker thing that is cheap. Read a k-of-k agreement
as less than the arithmetic suggests, and read a disagreement as the useful
signal: it is a criterion the model does not reliably understand, which is
worth knowing whichever draft you keep.
"""
import ast
from collections import Counter

from qikly import traceability

UNLABELLED = "unlabelled"


class _Generalise(ast.NodeTransformer):
    """
    Replace local names, so two drafts that differ only in naming compare
    equal, while keeping everything that changes meaning.

    What survives, and each because erasing it hid a real disagreement:
    the name of the function being called, since two drafts calling different
    functions are not the same test; attribute names, since those are the
    fields a criterion is about; and every literal, since those are the
    boundary values.
    """

    def visit_Call(self, node):  # noqa: N802  ast's own casing
        # The callee is deliberately not visited. Generalising it made
        # check_headway(2.0) and compute_alert(2.0) compare equal, so a draft
        # testing the wrong function passed consensus.
        node.args = [self.visit(a) for a in node.args]
        node.keywords = [self.visit(k) for k in node.keywords]
        if isinstance(node.func, ast.Attribute):
            node.func.value = self.visit(node.func.value)
        return node

    def visit_Name(self, node):  # noqa: N802
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)


def _normalise(node):
    try:
        return ast.unparse(_Generalise().visit(ast.parse(ast.unparse(node))))
    except (AttributeError, SyntaxError, ValueError):
        return None


def _is_docstring(statement):
    return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str))


def assertions_by_criterion(source):
    """
    {criterion index: frozenset of normalised statements} for one draft.

    The whole test body, not only its assertions. Comparing assertions alone
    was the first version and it was blind to the ordinary arrange-act-assert
    shape: `r = check(2.00)` then `assert r.warning is False` compared equal
    to `r = check(1.50)` then the same assertion, because the input the test
    is actually about never appears inside the assert. The literal that
    matters is usually in the call, so the call has to be compared too.

    A set, so two drafts that order the same statements differently agree.
    Tests naming no criterion are collected under UNLABELLED rather than
    dropped, so a draft that labels nothing is visibly different from a draft
    that asserts nothing.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    labels = traceability.trace_source(source)
    out = {}
    for node in tree.body:
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test")):
            continue
        indices = labels.get(node.name)
        if (indices is traceability.UNTRACED
                or indices is traceability.AMBIGUOUS or not indices):
            keys = [UNLABELLED]
        else:
            keys = list(indices)
        body = set()
        for statement in node.body:
            if _is_docstring(statement):
                continue
            text = _normalise(statement)
            if text:
                body.add(text)
        for key in keys:
            out.setdefault(key, set()).update(body)
    return {key: frozenset(value) for key, value in out.items()}


def compare(samples):
    """
    Where the drafts agree, where they do not, and which to keep.

    `samples` is a list of source strings. Returns a report; `chosen` is the
    index of the draft that matched the plurality on the most criteria, and
    `contested` names the criteria the drafts read differently.

    The winner is the draft most like the others rather than the one with the
    most tests. A draft can agree with nobody and still be right, which is
    exactly why `contested` is reported rather than silently resolved.
    """
    signatures = [assertions_by_criterion(s) for s in samples]
    keys = sorted({k for sig in signatures for k in sig}, key=str)

    contested, agreed, majority, tied = [], [], {}, []
    for key in keys:
        # Only drafts that wrote something about this criterion get a vote.
        # Counting silence let "nobody tested it" outvote "somebody did", so
        # a draft that uniquely covered a criterion scored zero for the one
        # piece of extra work it had done.
        spoken = [sig[key] for sig in signatures if sig.get(key)]
        if not spoken:
            continue
        votes = Counter(spoken)
        ranked = votes.most_common()
        majority[key] = ranked[0][0]
        if len(votes) == 1:
            agreed.append(key)
            continue
        contested.append(key)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            # No plurality. Counter breaks that tie by insertion order, which
            # would silently mean "keep whichever draft came first".
            tied.append(key)

    scores = [sum(1 for key in majority if sig.get(key) == majority[key])
              for sig in signatures]
    # Ties broken by how many criteria the draft actually labelled and tested.
    # Without it, a draft that labelled nothing agreed with everyone by having
    # nothing to disagree about, and could be kept over one that did the work.
    covered = [sum(1 for key in sig if key != UNLABELLED and sig[key])
               for sig in signatures]
    best = (max(range(len(samples)), key=lambda i: (scores[i], covered[i]))
            if samples else None)

    return {
        "samples": len(samples),
        "chosen": best,
        "scores": scores,
        "covered": covered,
        "agreed": agreed,
        "contested": contested,
        # Criteria where the drafts split evenly, so the vote decided nothing
        # and the kept draft is the first of the tied readings, not a winner.
        "tied": tied,
        "unanimous": not contested,
    }


def describe(report):
    """One line for the console, and the contested criteria are the point."""
    if report["samples"] < 2:
        return ""
    if report["unanimous"]:
        return ("%d samples agreed on every criterion, keeping sample %d"
                % (report["samples"], report["chosen"] + 1))
    named = ", ".join(str(k) for k in report["contested"])
    line = ("%d samples disagreed on criteri%s %s, keeping sample %d"
            % (report["samples"], "on" if len(report["contested"]) == 1 else "a",
               named, report["chosen"] + 1))
    if report["tied"]:
        # Saying "the one the others agree with" when nothing outvoted
        # anything would be a claim the vote did not make.
        return line + (", though the split was even on criteri%s %s, so nothing "
                       "was outvoted there"
                       % ("on" if len(report["tied"]) == 1 else "a",
                          ", ".join(str(k) for k in report["tied"])))
    return line + ", the one the others most agree with"
