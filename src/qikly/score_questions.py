"""
Turn the faults a suite missed into questions a person can answer.

`--score-code` ends with a list of changes your tests did not notice. That is
useful and it is also where people stopped: the next step, writing a task file
with acceptance criteria, is a blank page. This module fills the page with the
questions the score has already raised, one per missed fault, in words rather
than in AST notation:

    Your tests pass whether this is `>=` or `>`. What should happen when the
    value is exactly on the boundary?

## Why a question and not a test

A test written from the code can only check what the code already does, which
is the failure this whole project exists to prevent. The answer has to come
from a person who knows what the code is for. So nothing here guesses the
answer, and nothing here calls a model: the question is built from the planted
change alone, and the reply goes into `acceptance_criteria`, which the coding
agent never sees.

## The file is also the input to the next command

It ends with an empty `## Acceptance Criteria` section. Answers written there,
one per line, are read by `qikly --criteria-from FILE --task-id TASK` unchanged:
the questions above that heading are outside the section and are never taken
for criteria, and an unanswered `-` line is skipped.
"""
import ast
import os
import re

QUESTIONS_SUFFIX = "_questions.md"

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
                    "edge": edge, "number": number})
    asked_edges = {(q["path"], q["line"], q["edge"]) for q in out if q["edge"]}
    out = [q for q in out
           if not (q["number"] and (q["path"], q["line"], q["number"]) in asked_edges)]
    out.sort(key=lambda q: (q["file"] or "", q["line"] or 0))
    return out


def task_for(path):
    """The task id `qikly --scaffold PATH` writes for this file: the one to fill."""
    from qikly.scaffold import VERIFY_SUFFIX

    stem = os.path.splitext(os.path.basename(path))[0]
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


def next_steps(questions, questions_path, invoked_from=None):
    """
    (commands, note): what turns the answers into a task, from where they are.

    The commands are exact or absent, never a template to edit, because a
    template pasted as it stands fails. When they cannot be exact the note
    says why and what to do instead:

    - questions over several files, since `--scaffold` takes one module and
      `--criteria-from` fills one task;
    - a module `--scaffold` refuses, one with no public top-level function,
      which is any module made only of classes;
    - a task that already exists from an earlier round, which `--scaffold`
      will not overwrite.
    """
    here = invoked_from or os.getcwd()

    def shown(p):
        try:
            rel = os.path.relpath(p, here)
        except ValueError:
            return _pasteable(p)
        return _pasteable(p if rel.startswith("..") else rel)

    paths = sorted({q["path"] for q in questions if q.get("path")})
    answers = shown(questions_path)
    if len(paths) != 1:
        return [], (
            f"These questions are about {len(paths)} files, and a task covers "
            f"one module. Pick the module your answers are about, run "
            f"`qikly --scaffold` on it, then `qikly --criteria-from {answers} "
            f"--task-id` with the task id it prints.")
    module, task = paths[0], task_for(paths[0])
    if not _scaffoldable(module):
        return [], (
            f"`qikly --scaffold` needs a public top-level function to call, "
            f"and {os.path.basename(module)} has none, which is usual for a "
            f"module made of classes. Start a task with `qikly --init` "
            f"instead and copy your answers under its acceptance_criteria.")
    existing = os.path.join(here, "inputs_private", "config", "tasks",
                            f"{task}.yaml")
    if os.path.isfile(existing):
        return [f"qikly --criteria-from {answers} --task-id {task}",
                f"qikly --validate --tasks {task}"], (
            f"{task} already exists, so there is nothing to scaffold. If it "
            f"already has acceptance criteria, --criteria-from will not "
            f"overwrite them: add your answers to them by hand instead.")
    return [f"qikly --scaffold {shown(module)}",
            f"qikly --criteria-from {answers} --task-id {task}",
            f"qikly --validate --tasks {task}"], None


def _inline(code):
    """
    A line of code as inline code, never as a fenced block.

    The file is read by `--criteria-from`, which looks for Gherkin first and
    matches `Example:` or `Scenario:` at the start of any line. A dataclass
    field `example: int = 3` shown in a fenced block became the criterion
    `int = 3:`, and the user's real answers were dropped. Inside a code span
    the line starts with a backtick and cannot match.
    """
    fence = "``" if "`" in code else "`"
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{fence}{pad}{code}{pad}{fence}"


def render(label, questions, steps, note=None, misses=None):
    """The questions file: questions first, then the empty section to answer in."""
    count = len(questions)
    misses = count if misses is None else misses
    plural = "" if misses == 1 else "s"
    lines = [f"# Questions your tests leave open: {label}", "",
             f"Your tests passed {misses} deliberate change{plural} to your "
             f"code, which come down to {count} question"
             f"{'' if count == 1 else 's'} below. Each is a behaviour nothing "
             f"checks yet, so each is a question only you can answer: qikly "
             f"will not guess, because tests written from the code can only "
             f"agree with it.", "",
             "Answer from what the code is meant to do, not from what the "
             "line shown does now: that line is the thing in question. Some "
             "changes make no difference a test could ever see, so if a "
             "question has no sensible answer, skip it.", "",
             "## How to use this file", "",
             "1. Answer each question as one line under **Acceptance "
             "Criteria** at the end, naming a value someone could check: \"a "
             "rate of exactly 100 is rejected\", not \"rates are validated\". "
             "Write the answer alone, without the question's number."]
    if steps:
        lines += ["2. Then run these, in order:", "", "   ```"]
        lines += [f"   {step}" for step in steps]
        lines += ["   ```", ""]
        if note:
            lines += [note, ""]
        lines += ["They copy your answers into a task file as its acceptance "
                  "criteria and check it for free. The check lists what is "
                  "still yours to fill in before a run: the TODO lines, such "
                  "as the requirements, and a sample of your input data.", ""]
    else:
        lines += [f"2. {note}", ""]
    lines += ["## Questions", ""]
    # Grouped by line, because a line such as `if rate < 0 or rate > 100:`
    # can raise several questions, and repeating the code for each reads as
    # the tool repeating itself. The numbers are for reading; the answers
    # below are written without them, because a number copied into an answer
    # would reach test generation as part of the criterion.
    number, last = 0, None
    for q in questions:
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
        number += 1
        lines += [f"**Q{number}.** {q['question']}", ""]
    lines += ["## Acceptance Criteria", "",
              "<!-- One answer per line. Lines left as a bare dash are "
              "skipped. -->", ""]
    lines += ["- " for _ in questions]
    return "\n".join(lines) + "\n"
