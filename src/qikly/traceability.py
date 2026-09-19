"""
Which acceptance criterion did each generated test come from?

Six refinement experiments have asked whether a grown bar catches more, and
every one of them answered through an aggregate: two suites, the same planted
faults, a count each. An aggregate cannot say *which* criterion earned its
place, so a null result never distinguished "refinement adds nothing" from
"refinement adds criteria the generator then ignores". The measured fact that
54% more criteria produced a 6% smaller suite says the second is live.

Traceability makes that per-criterion question answerable without a model
call. Test generation is asked to name, in each test's docstring, the criteria
the test was written from. This module reads those markers back out of the
suite source with `ast`, so it works on suites already on disk and costs
nothing to run.

It is also a product improvement independent of the research: a reviewer
reading a generated suite can see which line of the specification each test is
meant to enforce, and a criterion no test names is visible before the run
rather than after it.

The marker is advisory and self-reported. A test naming criterion 3 is
evidence that the generator *intended* to cover criterion 3, not proof that it
did. Read `uncovered` as a lower bound on the problem and never as a coverage
guarantee.
"""
import ast
import re

# Tolerant on purpose. The line is written by a model, and the useful failure
# mode is a marker in a slightly different shape, not a missing measurement:
# "Criterion: 3", "Criteria: 3, 7", "criteria: none" all have to parse, while
# prose that merely mentions the word must not.
#
# Two namespaces, because one was not enough. Asked only for criteria, the
# first two real runs numbered into the *requirements* list and wrote the
# result on the Criteria line: "Criteria: 1, 9" on a task with five criteria
# and nine requirements, where requirement 9 was the output-format rule the
# test actually checked. An out-of-range index makes that visible, but a
# requirement index that happens to fall inside the criteria range would not
# be, and would silently credit a criterion nothing tested. Giving
# requirements their own line is what stops that, and it is what the model
# was trying to say in the first place.
_CRITERIA = re.compile(r"^[\s\-*#]*criteri(?:on|a)\s*[:\-]\s*(.+?)\s*$",
                       re.IGNORECASE | re.MULTILINE)
_REQUIREMENTS = re.compile(r"^[\s\-*#]*requirements?\s*[:\-]\s*(.+?)\s*$",
                           re.IGNORECASE | re.MULTILINE)
_INDEX = re.compile(r"\d+")
# "requirements only" stays here as well as having its own namespace: a
# model that writes it on the Criteria line has still said there is no
# criterion, and that is a deliberate statement rather than a missing one.
_NONE = re.compile(r"^\s*(none|n/?a|-{1,2}|requirements?(\s+only)?)\s*\.?\s*$",
                   re.IGNORECASE)

UNTRACED = None  # no marker at all, as distinct from a marker saying "none"
AMBIGUOUS = "ambiguous"  # a marker that parsed but could mean two things
_RANGE = re.compile(r"\d+\s*(?:-|\u2013|to)\s*\d+", re.IGNORECASE)


def _indices(text, pattern):
    """The indices one marker claims, or UNTRACED when it makes no claim."""
    if not text:
        return UNTRACED
    # The last match, not the first: the prompt calls the final line
    # authoritative, and search() would quietly prefer an earlier one.
    matches = pattern.findall(text)
    if not matches:
        return UNTRACED
    body = matches[-1]
    if _NONE.match(body):
        return []
    # "3-5" is either a range or two indices and nothing can tell which, so
    # it is reported rather than guessed. Expanding it invents coverage and
    # taking the endpoints drops criterion 4 silently; both are worse than
    # saying the label could not be read.
    if _RANGE.search(body):
        return AMBIGUOUS
    indices = [int(n) for n in _INDEX.findall(body)]
    # A marker whose body carries no number at all is prose that happened to
    # start with the word, not a claim. Treat it as untraced rather than as a
    # deliberate "none", which would quietly overstate how much was labelled.
    return sorted(set(indices)) if indices else UNTRACED


def criteria_in_docstring(docstring):
    """
    The criterion indices a docstring claims, as 1-based ints.

    Returns UNTRACED when there is no marker, an empty list when the marker
    says the test comes from the requirements rather than any criterion, and
    the indices otherwise. The three are different findings: no marker is a
    generator that ignored the instruction, an empty list is a deliberate
    statement, and both are worth separating from a test that names criteria.
    """
    return _indices(docstring, _CRITERIA)


def requirements_in_docstring(docstring):
    """The requirement indices a docstring claims, on its own Requirements line."""
    return _indices(docstring, _REQUIREMENTS)


# The body fallback reads the syntax tree rather than the text. A regex sweep
# over the function's source was the first attempt and it was wrong: the
# marker's shape is also the shape of an ordinary annotated variable, so
# `criteria: int = 5` in a test was credited as covering criterion 5. That is
# the silent-wrong-number failure this module exists to avoid, found in review
# before it reached a measurement.
#
# As a statement, `Criteria: 3` is an annotated name with no value, and
# `criteria: int = 5` has a value, which separates them exactly.
#
# The statement form is also why the prompt now requires a leading `#`.
# `Criteria: 3, 7` written as a bare statement is a SyntaxError, so on a task
# with enough criteria for the model to name two at once, a stray marker in a
# function body stopped the whole generated file from importing and failed
# the run at test generation. Found on CALC_TAX, eleven criteria, 2026-09-20.
# A comment is legal anywhere, so the same mistake is now harmless.
_MARKER_NAMES = ("criteria", "criterion")


def _marker_statement(node):
    """
    A marker written as a bare statement in a test body, or UNTRACED.

    Only an annotated name with no assigned value counts, which is what the
    marker is and what a real variable is not.
    """
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or statement.value is not None:
            continue
        target = statement.target
        if not isinstance(target, ast.Name) or target.id.lower() not in _MARKER_NAMES:
            continue
        annotation = statement.annotation
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, int)                 and not isinstance(annotation.value, bool):
            return [annotation.value]
        # `Criteria: none` is a bare name, `Criteria: None` a constant. Both
        # say the same thing: written from the requirements, not a criterion.
        if isinstance(annotation, ast.Name) and annotation.id.lower() == "none":
            return []
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return []
    return UNTRACED


def trace_source(source):
    """
    Every top-level test function in one suite file, mapped to its criteria.

    Nested and class-based tests are out of scope because the generator is
    told to write neither, and a silent partial reading would be worse than
    an obviously incomplete one.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    # A function's end_lineno is its last statement, so a trailing comment
    # sits outside it. The marker is usually exactly that, a comment after the
    # final assert, so each function's text runs to the next top-level node.
    lines = source.splitlines()
    starts = [n.lineno for n in tree.body]
    out = {}
    for position, node in enumerate(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            stop = starts[position + 1] - 1 if position + 1 < len(starts) else len(lines)
            docstring = ast.get_docstring(node)
            indices = criteria_in_docstring(docstring)
            if indices is UNTRACED and requirements_in_docstring(docstring) is not UNTRACED:
                # Labelled, just not with a criterion. A test that names only
                # a requirement is the same finding as one that says
                # "Criteria: none", and must not be counted as unlabelled:
                # unlabelled is meant to mean the generator ignored the
                # instruction, which is a different problem with a different
                # fix.
                indices = []
            elif indices is UNTRACED:
                # Nothing in the docstring. Fall back to the function body,
                # because a model that wrote the line one line too low has
                # still said which criterion it meant, and dropping that
                # reports an unlabelled suite while the labels sit right there.
                indices = _marker_statement(node)
            if indices is UNTRACED:
                # And a comment line in the body, which is what the marker
                # looks like once the `#` is required. Safe to read as text
                # because a comment cannot be confused with real code, unlike
                # the bare-statement form above.
                body = [l for l in lines[node.lineno - 1:stop]
                        if l.lstrip().startswith("#")]
                indices = criteria_in_docstring(chr(10).join(body))
            out[node.name] = indices
    return out


def _count_markers(text):
    """Marker lines of either namespace."""
    return len(_CRITERIA.findall(text)) + len(_REQUIREMENTS.findall(text))


def markers_outside_docstrings(source):
    """
    Marker lines the parser will not read, because they are not in a docstring.

    Seen on the first real run, 2026-09-17: asked for a line at the end of
    each test, gemini-3.5-flash-lite put one in the docstring and a second
    one at the end of the function body. `Criteria: none` in a body is a bare
    annotated name, which is legal Python that evaluates nothing, so it does
    not fail and nothing reports it.

    That is harmless while the docstring line is also present. It stops being
    harmless the day a model writes only the body one, because every test in
    the suite then reads as unlabelled and the reason is invisible. Counting
    them makes the failure say what it is.
    """
    in_docstrings = 0
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module, ast.ClassDef)):
            text = ast.get_docstring(node)
            if text:
                in_docstrings += _count_markers(text)
    return max(0, _count_markers(source) - in_docstrings)


def unreachable_tests(source):
    """
    Test functions `trace_source` cannot see, named so they are not silent.

    The tracer reads top-level functions only, because the generator is told
    to write no test classes and no nested tests. That instruction is not a
    guarantee, and the failure was invisible from both ends: such a test was
    absent from `tests_total`, and its docstring marker counted as "in a
    docstring" so no stray fired either. A suite written the disobedient way
    would have reported as a suite that did not exist, and an empty coverage
    table reads like a generator that ignored the instruction rather than a
    reader that could not see the tests.

    Counting them turns that into a discrepancy a person can act on. Found in
    review, 2026-09-17.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    top_level = {id(node) for node in tree.body}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))                 and node.name.startswith("test") and id(node) not in top_level:
            found.append(node.name)
    return sorted(found)


def coverage(sources, criteria_count):
    """
    Per-criterion coverage across a stage's files.

    `sources` maps a label, normally a file path, to that file's source text.
    `criteria_count` is how many criteria the task declares, which bounds what
    a valid index can be.

    The returned `per_criterion` is the measurement experiment 4 exists to
    produce: delete a criterion, regenerate, and the change in its entry
    prices that criterion directly, with no fault model in between.
    """
    per_criterion = {index: [] for index in range(1, criteria_count + 1)}
    traced, untraced, requirements_only, out_of_range = [], [], [], {}
    ambiguous, unreachable = [], []
    stray = 0

    for label, source in sorted(sources.items()):
        stray += markers_outside_docstrings(source)
        unreachable.extend("%s::%s" % (label, name) for name in unreachable_tests(source))
        for name, indices in sorted(trace_source(source).items()):
            where = "%s::%s" % (label, name)
            if indices is UNTRACED:
                untraced.append(where)
                continue
            if indices is AMBIGUOUS:
                # Counted nowhere on purpose. A label that could mean two
                # things must not quietly become one of them.
                ambiguous.append(where)
                continue
            if not indices:
                requirements_only.append(where)
                continue
            traced.append(where)
            for index in indices:
                if 1 <= index <= criteria_count:
                    per_criterion[index].append(where)
                else:
                    out_of_range.setdefault(where, []).append(index)

    total = len(traced) + len(untraced) + len(requirements_only) + len(ambiguous)
    return {
        "criteria_count": criteria_count,
        "tests_total": total,
        "tests_traced": len(traced),
        "tests_untraced": untraced,
        "tests_requirements_only": requirements_only,
        "per_criterion": {index: len(names) for index, names in per_criterion.items()},
        "tests_by_criterion": per_criterion,
        "uncovered": [index for index, names in per_criterion.items() if not names],
        "out_of_range": out_of_range,
        "tests_ambiguous": ambiguous,
        # Not added to tests_total: these were never read, so counting them
        # among the tests would imply the rest of this table describes them.
        "tests_outside_supported_shape": unreachable,
        "markers_outside_docstrings": stray,
    }
