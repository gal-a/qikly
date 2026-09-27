"""
Which criteria the input data cannot reach, without calling anything.

A criterion no input row triggers produces a test that passes whatever the
code does. In this project's own measurements roughly two thirds of
deliberately planted faults were caught by neither arm for exactly that
reason: the bar was not wrong, it was unmeasurable. That is the same problem
an operational design domain has one scale up, and it has the same shape: a
suite can only report on the part of the space the data visits.

`--propose-fixtures` already answers the richer question, which rows would
reach each criterion, by asking an agent. That costs a model call per task and
has to be asked for. This is the free half, and it answers the narrower
question a user should not have to ask twice: of the values my criteria name
for a field in my data, which ones does that field never hold.

## The rule, and why it is this narrow

A criterion is reported only when all three are true:

1. it names a field that exists in the input data, by that field's own name;
2. it names at least one value for it; and
3. none of those values appear anywhere in that field.

Every looser rule was tried against the thirteen bundled tasks first, and each
one drowned the real findings:

**Searching the whole file rather than the named field** matched 250 inside
1250, and matched a boundary value against an unrelated column that happened
to hold the same number.

**Accepting any quoted literal** flagged output structure. Criteria say things
like `listed under "accepted" exactly once`, and "accepted" is an output key
that no input row will ever contain. It also flagged format strings such as
"YYYY-MM-DD", which describe a shape rather than a value.

**Accepting single quotes** turned every apostrophe in the prose into a
literal: `Python's default round-half-to-even` became the literal
`s default round-half-to-even`.

**Accepting any number** flagged computed values. A criterion pinning that
434.99999999999994 reports as 435.00 names two numbers that are outputs, and
no input row will ever hold either.

Those are all the same mistake in different clothes: a value is only checkable
against the data when you know which column it belongs to. Tying every value
to a named field is what makes the check quiet enough to be worth reading, and
on the bundled tasks it reports nothing at all, which is the correct answer
for tasks whose fixtures were audited for exactly this.
"""
import csv
import io
import json
import os
import re

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# A number is a value for a field only when it sits in a construction that
# assigns it to one. Without this the check reads every number in the prose as
# a boundary, and criteria are full of numbers that are not: "exactly 5
# digits", "the 50 real US states", "file 1 and file 2". On the bundled tasks
# that alone was the difference between eleven findings, all false, and none.
_VALUE = re.compile(
    r"(?:\bof\b|\bis\b|\bat\b|\bto\b|\bequals?\b"
    r"|\babove\b|\bbelow\b|\bover\b|\bunder\b|\bexceeds?\b"
    r"|\bgreater than\b|\bless than\b|\bat least\b|\bat most\b"
    r"|\bexactly\b|>=|<=|==|=|>|<)"
    r"\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    # Without the first of these the engine backtracks to make the stop list
    # pass: "exactly 10 digits" matched as the value 1, because after "1" the
    # next character is "0" rather than the word "digits". The second stops
    # 250 being taken out of 250.01, and is written as "a period followed by a
    # digit" rather than "a period", so that an ordinary sentence ending, "at
    # most 250.", still names a value. Forbidding any following period at all
    # silently skipped every criterion written that way, which is most of the
    # natural ones.
    r"(?!\d)(?!\.\d)"
    r"(?!\s*(?:digits?|characters?|chars?|letters?|files?|rows?|fields?|items?"
    r"|entries|states|days?|months?|years?|hours?|minutes?|seconds?|decimals?"
    r"|places?|columns?|lists?|keys?))",
    re.IGNORECASE)

# A parenthetical opened with e.g. or the like is an illustration, and its
# numbers are worked examples rather than values any field holds.
# CALC_CALENDAR explains its inclusive counting with
# "(e.g. January 1 to January 5 is 5 billed days, not 4)", and those were
# the last false positive left on the bundled tasks.
_ILLUSTRATION = re.compile(
    r"\((?:e\.g\.|eg\.|i\.e\.|for example|such as|for instance)[^)]*\)",
    re.IGNORECASE)

# How far after a field name a value can sit and still belong to it. Long
# enough for "gap_m must be a distance the radar can measure, up to 250", and
# short enough that the next clause's numbers are somebody else's.
_WINDOW = 60

# A field name worth matching. Two characters or fewer collides with ordinary
# words, and a name that is itself an English word ("date", "status") is kept
# only because it must appear in the data's own header to get this far.
_MIN_FIELD = 3

_MAX_CELLS = 200000


def columns(path):
    """
    {field name: [values as text]} for one input file.

    CSV, TSV, JSON and JSONL are read structurally, because the whole point is
    to know which column a value came from. Anything else returns nothing
    rather than a guess: a format this cannot parse is a format whose fields
    it does not know, and a check that invents fields would report against
    data it never read.
    """
    lower = path.lower()
    try:
        with io.open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return {}

    found = {}
    try:
        return _parse(text, lower, found)
    except Exception:
        # A fixture this cannot parse is a fixture whose fields it does not
        # know, and an unknown field set is a reason to say nothing rather
        # than to fail. `validate` calls this and is recommended as a
        # pre-commit hook, so one misencoded CSV must not stop it reporting on
        # every other task. A NUL byte does exactly that: `csv.reader` raises,
        # and it raises outside the read that this used to guard.
        return {}


def _parse(text, lower, found):
    if lower.endswith(".csv") or lower.endswith(".tsv"):
        rows = list(csv.reader(io.StringIO(text),
                               delimiter="\t" if lower.endswith(".tsv") else ","))
        if not rows:
            return {}
        header = [cell.strip() for cell in rows[0]]
        for row in rows[1:_MAX_CELLS]:
            for name, cell in zip(header, row):
                found.setdefault(name, []).append(cell.strip())
    elif lower.endswith(".json") or lower.endswith(".jsonl"):
        chunks = [text] if lower.endswith(".json") else text.splitlines()
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                _collect(json.loads(chunk), found)
            except ValueError:
                return {}
    return found


def _collect(node, found):
    """Every scalar under a JSON document, filed under its own key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list, tuple)):
                _collect(value, found)
            else:
                found.setdefault(str(key), []).append(
                    "" if value is None else str(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect(value, found)


def _as_number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def fields_named(criterion, known):
    """The input fields this criterion mentions, by their own names."""
    lowered = criterion.lower()
    return [name for name in known
            if len(name) >= _MIN_FIELD
            and re.search(r"(?<![a-z0-9_])%s(?![a-z0-9_])" % re.escape(name.lower()),
                          lowered)]


def values_for(criterion, fields):
    """
    The numbers this criterion assigns to one of these fields.

    A number qualifies when it follows a relation word ("of 250", "above 100",
    "exactly 0") and sits within `_WINDOW` characters of one of the field
    names, before it or after it. Both halves are needed: the relation word
    rules out counts and ordinals, and the proximity rules out a value that
    belongs to a different field mentioned elsewhere in the same sentence.

    Proximity is not the same as belonging, and this is where the check is
    weakest. "gap_m readings use schema version of 2" puts an unrelated 2
    inside the window, and it will be reported. That is the shape of false
    positive left: a warning naming the criterion it came from, which a reader
    can dismiss in a second. Tightening it further costs the criteria written
    the ordinary way, which is the expensive direction to be wrong in.
    """
    criterion = _ILLUSTRATION.sub(" ", criterion)
    lowered = criterion.lower()
    spans = []
    for name in fields:
        for hit in re.finditer(
                r"(?<![a-z0-9_])%s(?![a-z0-9_])" % re.escape(name.lower()),
                lowered):
            # Both directions. "a gap_m of exactly 250" and "reject any
            # reading of at least 250 in the gap_m column" say the same thing,
            # and a forward-only window silently skipped the second, so a
            # criterion phrased that way was never checked at all.
            spans.append((hit.start() - _WINDOW, hit.end() + _WINDOW))

    out = []
    for hit in _VALUE.finditer(criterion):
        start = hit.start(1)
        if any(begin <= start <= end for begin, end in spans):
            out.append(hit.group(1))
    return out


def _held(value, values):
    """Whether a field holds this value, numerically or as written."""
    number = _as_number(value)
    if number is not None:
        for cell in values:
            other = _as_number(cell)
            if other is not None and abs(number - other) < 1e-9:
                return True
    # A field can hold a value inside a compound string, such as a date or an
    # identifier. Only non-numeric cells qualify: inside a number a substring
    # is not a value, and 250 would otherwise be "held" by a row of 1250.
    # Short tokens are excluded too, since "0" is a substring of almost
    # everything, and a false negative here is cheaper than a false alarm.
    if len(value) >= 3:
        return any(value in cell for cell in values if _as_number(cell) is None)
    return False


def unreachable(task, resolve=None):
    """
    Criteria naming a value that the field they name never holds.

    Returns (index, criterion, missing values, fields named), the index
    1-based to match how `validate` and the generated tests number criteria.
    The fields come back because they are the actionable half: a reader needs
    to know which column to add a row to.

    `resolve` maps a declared input path to a readable one, because a bundled
    task names `inputs_private/...` while its fixtures live inside the package
    until a run copies them out. Passing it in keeps the path rules out of
    here, and makes the whole thing testable without a project tree.
    """
    criteria = [c for c in (task.get("acceptance_criteria") or [])
                if isinstance(c, str) and c.strip()]
    inputs = [p for p in (task.get("inputs") or []) if isinstance(p, str)]
    if not criteria or not inputs:
        return []

    data = {}
    for declared in inputs:
        path = resolve(declared) if resolve else declared
        if path and os.path.isfile(path):
            for name, values in columns(path).items():
                data.setdefault(name, []).extend(values)
    if not data:
        # Unreadable or absent data is a different finding, and `validate`
        # already reports a missing input file as an error. Saying it again in
        # weaker words trains people to skim both.
        return []

    found = []
    for index, criterion in enumerate(criteria, start=1):
        named = fields_named(criterion, data)
        if not named:
            continue
        values = values_for(criterion, named)
        if not values:
            continue
        missing = [v for v in values
                   if not any(_held(v, data[name]) for name in named)]
        if len(missing) == len(values):
            found.append((index, criterion, missing, sorted(named)))
    return found


def describe(task, name, resolve=None):
    """
    Warning lines for `validate`, one per criterion the data cannot reach.

    Each one names the command that fixes it. Telling somebody a criterion is
    unmeasurable without telling them the next move leaves them to find
    `--propose-fixtures` in the reference, which most people will not do.
    """
    task_id = task.get("task_id") or os.path.splitext(name)[0]
    lines = []
    for index, criterion, missing, fields in unreachable(task, resolve):
        values = ", ".join(missing[:4])
        columns = " or ".join(fields[:3])
        holds = "holds it" if len(missing) == 1 else "holds any of them"
        lines.append(
            f"{name}: criterion {index} names {values} for {columns}, and no "
            f"row {holds}. A criterion your data never triggers produces a "
            f"test that passes whatever the code does. "
            f"`qikly --propose-fixtures --tasks {task_id}` drafts the rows it "
            f"would take; adding one by hand works too. "
            f"criterion: {criterion[:60]!r}")
    return lines
