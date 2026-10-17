"""
Turn the faults a suite missed into questions a person can answer.

`--score-code` ends with a list of changes your tests did not notice. That is
useful and it is also where people stopped: the next step, writing a task file
with acceptance criteria, is a blank page. This module fills the page with the
questions the score has already raised, in words rather than in AST notation:

    Your tests pass whether this is `rate > 100` or `rate >= 100`, so nothing
    checks the boundary itself. What should happen at exactly `100`?

## Why a question and not a test

A test written from the code can only check what the code already does, which
is the failure this whole project exists to prevent. The answer has to come
from a person who knows what the code is for. So nothing here guesses the
answer, and nothing here calls a model: the question is built from the planted
change alone.

## Where the answers go

Into the task file, where acceptance criteria live and where the run reads
them. `--score-code` saves the questions beside its report, and `--scaffold`
writes the newest ones about the file it is given into `acceptance_criteria`,
each as a comment above a `TODO` for the answer, and `--validate` counts the
`TODO`s left. Every question line starts with `#?` and is dropped from the text
either agent receives, wherever it is in the file: the criteria cut would
remove it for the coding agent, but the test generator reads the whole file,
comments included, and a question quotes the code it must never see.

An earlier version collected the answers in a separate markdown file and
imported them with `--criteria-from`. That put the bar in two places, and the
import's Gherkin detection read a code line such as `example: int = 3` as a
scenario, so the code became a criterion.
"""
import ast
import glob
import json
import os
import re
from datetime import datetime

QUESTIONS_SUFFIX = "_questions.json"

_LINE = re.compile(r",\s*line (\d+)\s*$")
_SWAP = re.compile(r"^(.+?) became (.+?)$")
_INT = re.compile(r"^int (-?\d+) -> (-?\d+)$")
_BOOL = re.compile(r"^bool (True|False) -> (True|False)$")
_DROPPED = re.compile(r"^\.(\w+)\(\) dropped$")

_BOUNDARY = {"<", "<=", ">", ">="}
_CONNECTIVE = {"and", "or"}
_NORMALISED = {
    "strip": "only by spaces around them", "lstrip": "only by leading spaces",
    "rstrip": "only by trailing spaces", "lower": "only by letter case",
    "upper": "only by letter case", "casefold": "only by letter case",
    "title": "only by capitalisation",
}


def split_change(change):
    """('>= became >', 12) out of '>= became >, line 12'; line is None if absent."""
    match = _LINE.search(change or "")
    if not match:
        return (change or "").strip(), None
    return change[:match.start()].strip(), int(match.group(1))


_OPS = {"<": ast.Lt, "<=": ast.LtE, ">": ast.Gt, ">=": ast.GtE,
        "==": ast.Eq, "!=": ast.NotEq, "in": ast.In, "not in": ast.NotIn,
        "is": ast.Is, "is not": ast.IsNot}


def _comparison(source, line, old, new):
    """
    The comparison a swap was planted in, as (before, after, right-hand side).

    A line such as `if rate < 0 or rate > 100:` holds two comparisons, and
    "whether this is `>` or `>=`" does not say which one, so the question names
    it. None when the line holds no single comparison using `old`, in which
    case the question falls back to the operators alone.
    """
    if source is None or not line or old not in _OPS or new not in _OPS:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.Compare) and getattr(n, "lineno", None) == line
             and len(n.ops) == 1 and type(n.ops[0]) is _OPS[old]]
    if len(found) != 1:
        return None
    node = found[0]
    before = ast.unparse(node)
    after = ast.unparse(ast.Compare(left=node.left, ops=[_OPS[new]()],
                                    comparators=node.comparators))
    return before, after, ast.unparse(node.comparators[0])


def ask(kind, source=None, line=None):
    """The question for one planted change, worded for whoever owns the code."""
    swap = _SWAP.match(kind)
    if swap:
        old, new = swap.group(1).strip(), swap.group(2).strip()
        named = _comparison(source, line, old, new)
        if old in _BOUNDARY and new in _BOUNDARY:
            if named:
                before, after, edge = named
                return (f"Your tests pass whether this is `{before}` or "
                        f"`{after}`, so nothing checks the boundary itself. "
                        f"What should happen at exactly `{edge}`?")
            return (f"Your tests pass whether a `{old}` on this line is "
                    f"`{old}` or `{new}`, so nothing checks that boundary. "
                    f"For each comparison here, what should happen exactly at "
                    f"its boundary value?")
        if old in _CONNECTIVE and new in _CONNECTIVE:
            # Not "both conditions or either one": `name or "anon"` joins
            # values, not conditions, and the question has to fit both.
            return (f"Your tests pass whether this uses `{old}` or `{new}`. "
                    f"Which is right, and which input would show the "
                    f"difference?")
        shown = f"`{named[0]}` became `{named[1]}`" if named else (
            f"`{old}` became `{new}`")
        return (f"Your tests pass even with this condition inverted ({shown}), "
                f"so neither outcome is checked. What should happen in each "
                f"case?")
    number = _INT.match(kind)
    if number:
        return (f"Your tests pass whether this number is {number.group(1)} or "
                f"{number.group(2)}. What should it be, and which input would "
                f"show the difference?")
    if _BOOL.match(kind):
        return (f"Your tests pass with this `{_BOOL.match(kind).group(1)}` "
                f"flipped. What behaviour depends on it?")
    if kind == "guard disabled":
        return ("Your tests pass with this check switched off. Which input, "
                "if any, should it catch, and what should happen to it?")
    if kind == "regex anchors stripped":
        return ("Your tests pass when this pattern matches only part of a "
                "value. Should a value with extra characters before or after "
                "a valid one be accepted?")
    dropped = _DROPPED.match(kind)
    if dropped:
        how = _NORMALISED.get(dropped.group(1), "only in that normalisation")
        return (f"Your tests pass without `.{dropped.group(1)}()` here. Should "
                f"two inputs that differ {how} be treated the same?")
    if kind == "raise swallowed":
        return ("Your tests pass when this error is never raised. Which input, "
                "if any, should raise it?")
    return (f"Your tests pass with this change: {kind}. What should this line "
            f"guarantee?")


def _enclosing(source, line):
    """The innermost function or method holding `line`, or None at module level."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end and (
                    best is None or node.lineno >= best.lineno):
                best = node
    return best.name if best else None


def _labels(paths):
    """
    How each file is named in the questions: its path below the scored root.

    The basename alone merged `pkg/x/util.py` and `pkg/y/util.py` into one
    heading, and the second file's questions vanished as duplicates.
    """
    paths = sorted(set(p for p in paths if p))
    if len(paths) < 2:
        return {p: os.path.basename(p) for p in paths}
    try:
        root = os.path.commonpath([os.path.dirname(p) for p in paths])
    except ValueError:
        return {p: p.replace("\\", "/") for p in paths}
    return {p: os.path.relpath(p, root).replace("\\", "/") for p in paths}


def build(missed):
    """
    The questions for the faults a suite missed, in file and line order.

    Each item of `missed` is what `mutation_score` records: `file`, `change`
    and, from this release, `path` (the file it was planted in). A fault
    without a readable path still gets a question, just without the line of
    code shown above it.

    Usually one question per miss, with two exceptions, both because a reader
    asked the same thing twice reads it as the tool repeating itself: two
    faults on one line asking the same question become one, and a constant
    nudged by one (`100 -> 101`) is dropped when a boundary question on the
    same line already asks about that value.
    """
    missed = list(missed or [])
    labels = _labels(item.get("path") for item in missed)
    sources, out, seen = {}, [], set()
    for item in missed:
        kind, line = split_change(item.get("change"))
        path = item.get("path")
        if path and path not in sources:
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as handle:
                    sources[path] = handle.read()
            except OSError:
                sources[path] = None
        source = sources.get(path) if path else None
        code = function = edge = number = None
        if source is not None and line:
            lines = source.splitlines()
            if 0 < line <= len(lines):
                code = lines[line - 1].strip()
            function = _enclosing(source, line)
        swap = _SWAP.match(kind)
        if swap and swap.group(1).strip() in _BOUNDARY:
            named = _comparison(source, line, swap.group(1).strip(),
                                swap.group(2).strip())
            edge = named[2] if named else None
        if _INT.match(kind):
            number = _INT.match(kind).group(1)
        question = ask(kind, source, line)
        label = labels.get(path) or item.get("file")
        key = (path or item.get("file"), line, question)
        if key in seen:
            continue
        seen.add(key)
        out.append({"file": label, "path": path, "line": line,
                    "function": function, "code": code, "question": question,
                    "edge": edge, "number": number, "change": item.get("change")})
    asked_edges = {(q["path"], q["line"], q["edge"]) for q in out if q["edge"]}
    out = [q for q in out
           if not (q["number"] and (q["path"], q["line"], q["number"]) in asked_edges)]
    out.sort(key=lambda q: (q["file"] or "", q["line"] or 0))
    return out


def task_for(path):
    """The task id `qikly --scaffold PATH` writes for this file: the one to fill."""
    from qikly.scaffold import VERIFY_SUFFIX

    stem = os.path.splitext(os.path.basename(path))[0]
    if stem == "__init__":
        # A package's own code is named for the package: INFLECTION_VERIFY,
        # not __INIT___VERIFY.
        stem = os.path.basename(os.path.dirname(os.path.abspath(path))) or stem
    return "".join(c if c.isalnum() else "_" for c in stem).upper() + VERIFY_SUFFIX


def _pasteable(path):
    """
    A path a reader can paste into PowerShell, cmd or Git Bash.

    Forward slashes, because Git Bash strips backslashes from a pasted path
    and Python on Windows takes either. Quoted when it holds a space, which
    otherwise splits into two arguments.
    """
    path = path.replace("\\", "/")
    return f'"{path}"' if " " in path else path


def _scaffoldable(path):
    """Whether `--scaffold` will accept this file: it needs a public function."""
    try:
        from qikly.scaffold import read_functions

        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            return bool(read_functions(handle.read()))
    except Exception:
        return True


def _same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# ------------------------------------------------------------ saved form --

def save(questions, path, label, scored=()):
    """
    Write the questions where `--scaffold` will look for them.

    `scored` names every file the score planted faults in, including those
    with no questions. Without it, a re-score after the tests were improved
    left nothing behind, and `--scaffold` fell back to the older score's
    questions, which were no longer true.
    """
    data = {"label": label,
            "written": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "scored": sorted({os.path.abspath(f) for f in scored}),
            # edge, number and change too: `--scaffold` runs the code
            # beside each one to say what it does there now.
            "questions": [{k: q.get(k) for k in
                           ("file", "path", "line", "function", "code", "question",
                            "edge", "number", "change")}
                          for q in questions]}
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1)
    return path


def latest_for(module, directory):
    """
    (questions, written) from the newest saved score that asked about `module`,
    or ([], None).

    Newest by file time, and only the questions about this exact file, so
    scaffolding one module of a scored package takes that module's questions
    and leaves the rest. A file that cannot be read is skipped, never fatal:
    scaffolding has to work whether or not a score was ever taken.
    """
    def age(name):
        try:
            return os.path.getmtime(name)
        except OSError:
            return 0.0

    found = sorted(glob.glob(os.path.join(directory, "*" + QUESTIONS_SUFFIX)),
                   key=age, reverse=True)
    for name in found:
        try:
            with open(name, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        def listed(key):
            value = data.get(key)
            return value if isinstance(value, list) else []

        items = [q for q in listed("questions")
                 if isinstance(q, dict) and isinstance(q.get("question"), str)
                 and isinstance(q.get("path"), str)]
        scored = [f for f in listed("scored") if isinstance(f, str)]
        mine = [q for q in items if _same_file(q["path"], module)]
        if not mine and not any(_same_file(f, module) for f in scored):
            continue
        # The newest score of this file decides, even when it asked nothing:
        # its tests may since have been improved.
        return _still_true(mine, module), data.get("written")
    return [], None


def _still_true(questions, module):
    """
    The questions whose line still reads as it did when they were asked.

    A question names a line and shows its code. Once the file is edited, the
    line number can point at something else entirely, and a question about
    code that is no longer there is worse than none.
    """
    try:
        with open(module, encoding="utf-8-sig", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    kept = []
    for q in questions:
        line, code = q.get("line"), q.get("code")
        if not isinstance(line, int) or not code:
            continue
        if 0 < line <= len(lines) and lines[line - 1].strip() == code.strip():
            kept.append(q)
    return kept


# ------------------------------------------------------- in the task file --

_ANSWER = '  - "TODO: your answer to the question above"'

# Every line qikly writes for a question starts with this, so the text either
# agent receives can drop them wherever a user moves them. Plain comments
# inside the criteria block are cut with it, but the test generator reads the
# whole file, comments included, and it must not read the code they quote.
MARK = "#?"
_MARKED = re.compile(r"(?m)^[ \t]*#\?.*(?:\r?\n|$)")
# YAML refuses a control character anywhere in a file, comments included, so
# one escape code in a string literal would void the whole block.
_UNPRINTABLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufffe\uffff]")


def drop_question_lines(text):
    """
    `text` without any line qikly wrote for a question, and without any
    criterion still left as a TODO: a question someone skipped is not a
    criterion, and sent as one it asked test generation to test "TODO: your
    answer to the question above". Idempotent.
    """
    return drop_todo_criteria(_MARKED.sub("", text or ""))


_TODO_ITEM = re.compile(r"^\s*TODO\b")


def drop_todo_criteria(text):
    """
    `text` with every acceptance_criteria item that starts with TODO removed,
    found by YAML itself so a multi-line item goes whole. A file YAML cannot
    read is returned as it is, for the run to report.
    """
    import yaml

    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return text
    if not isinstance(node, yaml.MappingNode):
        return text
    items = next((v for k, v in node.value
                  if isinstance(k, yaml.ScalarNode) and k.value == "acceptance_criteria"),
                 None)
    if not isinstance(items, yaml.SequenceNode):
        return text
    lines = text.split("\n")
    drop = set()
    for item in items.value:
        if isinstance(item, yaml.ScalarNode) and _TODO_ITEM.match(item.value or ""):
            # The item's lines, from its dash to its last character.
            end = item.end_mark.line - (1 if item.end_mark.column == 0 else 0)
            drop.update(range(item.start_mark.line, end + 1))
    if not drop:
        return text
    return "\n".join(l for n, l in enumerate(lines) if n not in drop)


def _printable(text):
    return _UNPRINTABLE.sub("?", " ".join(str(text).split()))


def _comment(text, width=78):
    """Marked comment lines, wrapped, whatever the code or the question holds."""
    import textwrap

    return ["  %s " % MARK + part for part in
            textwrap.wrap(_printable(text), width - 5, break_long_words=False,
                          break_on_hyphens=False)] or ["  " + MARK]


def yaml_block(questions, written=None):
    """
    The `acceptance_criteria` block `--scaffold` writes when there are questions.

    Every question and every line of code is a comment, so nothing taken from
    the code can become a criterion, and each answer slot is a TODO, which
    `--validate` reports until it is replaced. The block is parsed back before
    it is used, in `scaffold`, so a question can never leave the file invalid.
    """
    when = f" on {written}" if written else ""
    count = len(questions)
    lines = ["acceptance_criteria:"]
    lines += _comment(
        f"{count} question{'' if count == 1 else 's'} from qikly --score"
        f"{when}: what your tests do not check. Write your answer in place of "
        f"each TODO, naming a value someone could check, from what the code is "
        f"meant to do. A TODO you leave is skipped. Lines starting {MARK} are "
        f"notes for you: neither agent reads them.")
    lines.append("")
    for q in questions:
        where = q.get("file") or "your code"
        if q.get("function"):
            where += f", {q['function']}"
        if q.get("line"):
            where += f", line {q['line']}"
        lines += _comment(where + ":")
        if q.get("code"):
            # The code on a line of its own, never wrapped, so it reads as
            # code. Still a comment: nothing taken from it can be a criterion.
            lines.append("  %s     " % MARK + _printable(q["code"]))
        prompt = q.get("hint_prompt")
        if prompt:
            # What qikly saw by running the code beside the value in
            # question, so the answer can be a value, not a guess at one.
            # The call on a line of its own, never wrapped mid-call.
            lead, found, ask = prompt.rpartition("What should ")
            if lead.strip():
                lines += _comment(lead.strip())
            if found:
                lines.append("  %s " % MARK + _printable(found + ask))
            else:
                lines += _comment(prompt)
            lines += _comment("Found by running your code:")
            for label in q.get("hint_options") or []:
                label = label.split("; you will type")[0]
                lines += _comment("  - " + label)
            if q.get("covers"):
                lines += _comment(f"(This also answers {q['covers']} more "
                                  f"place{'s' if q['covers'] > 1 else ''} your "
                                  f"tests leave open on the same call.)")
            call = re.search(r"What should (.+) do\?", prompt)
            lines.append(f'  - "TODO: what {_yaml_safe(call.group(1))} should do"'
                         if call else _ANSWER)
        else:
            lines += _comment(q["question"])
            lines.append(_ANSWER)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _yaml_safe(text):
    """Text for inside a double-quoted YAML string on one line."""
    return _printable(text).replace("\\", "\\\\").replace('"', '\\"')


# ------------------------------------------------------- in the report ----

def _inline(code):
    """A line of code as an inline code span, whatever backticks it holds."""
    fence = "``" if "`" in code else "`"
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{fence}{pad}{code}{pad}{fence}"


def report_lines(questions, misses, advice_lines):
    """The questions section of the `--score-code` report, grouped by line."""
    count = len(questions)
    lines = ["## Questions your tests leave open", "",
             f"The {misses} miss{'' if misses == 1 else 'es'} above come down "
             f"to {count} question{'' if count == 1 else 's'}. Each is a "
             f"behaviour nothing checks yet, so each is yours to answer: qikly "
             f"will not guess, because tests written from the code can only "
             f"agree with it. Some changes make no difference a test could ever "
             f"see; skip a question with no sensible answer.", ""]
    lines += [line for line in advice_lines] + [""]
    last = None
    # Numbered across the groups, so "question 3" names one question.
    for number, q in enumerate(questions, 1):
        place = (q["file"], q["line"])
        if place != last:
            last = place
            where = q["file"] or "your code"
            if q["function"]:
                where += f", `{q['function']}`"
            if q["line"]:
                where += f", line {q['line']}"
            lines += [f"### {where}", ""]
            if q["code"]:
                lines += [_inline(q["code"]), ""]
        lines += [f"{number}. {q['question']}", ""]
    return lines


def advice(questions, invoked_from=None):
    """
    What to run next, as lines, exact for where the questions are.

    Commands are given only when they will work as pasted: `--scaffold` takes
    one module and refuses one with no public function, and will not rewrite a
    task that already exists.
    """
    here = invoked_from or os.getcwd()

    def shown(p):
        try:
            rel = os.path.relpath(p, here)
        except ValueError:
            return _pasteable(p)
        return _pasteable(p if rel.startswith("..") else rel)

    paths = sorted({q["path"] for q in questions if q.get("path")})
    if not paths:
        return []
    if len(paths) > 1:
        folder = os.path.commonpath([os.path.dirname(p) for p in paths])
        return ["Next: `qikly --scaffold %s` writes a task file for each of the "
                "%d modules these are about, with its questions in it to answer: "
                "%s." % (shown(folder), len(paths),
                         ", ".join(shown(p) for p in paths))]
    module, task = paths[0], task_for(paths[0])
    if not _scaffoldable(module):
        return ["`qikly --scaffold` needs a public top-level function to call, "
                "and %s has none, which is usual for a module made of classes. "
                "Start a task with `qikly --init` instead and copy these "
                "questions under its acceptance_criteria as comments starting "
                "%s, each above your answer." % (os.path.basename(module), MARK)]
    existing = os.path.join(here, "inputs_private", "config", "tasks", f"{task}.yaml")
    if os.path.isfile(existing):
        return ["Its task file already exists, so `--scaffold` will not rewrite "
                "it: %s. Add any new questions to its acceptance_criteria, or "
                "move it aside and run `qikly --scaffold %s` again." % (
                    shown(existing), shown(module))]
    return ["Next: `qikly --scaffold %s` writes the task file, with these "
            "questions in it to answer." % shown(module)]
