"""
The first draft of a task's answers, written by a spec agent that never sees
the code.

Answering the questions `--score` raised was the step people stalled on: on
real libraries almost none of them had options to pick from, so every answer
was a sentence to write. This writes a complete first draft instead, the
`requirements` line and one acceptance criterion per question, for a person
to accept as it is or change where it is marked.

What makes the draft worth having is what the agent is not given. It reads
the module's README, its docstrings and the names and signatures of its
functions, and each question with the code it quotes taken out. It never
reads a function body, so it cannot describe what the code does; it says
what the code should do, from what the code is for. Where that differs from
the code, a test written from the draft fails on it, and that failure is the
finding. A draft read off the code would agree with it by construction and
find nothing, which is the failure this project exists to prevent.

Each criterion says where it came from. A quote from the documentation is
checked word for word against the documentation, and a criterion whose quote
is not there is dropped rather than trusted. A criterion judged from the
module's purpose, because nothing written decides it, is marked for a person
to check: those are the key parts of the draft.
"""
import ast
import json
import os
import re

# Enough for a README and a module's docstrings, without paying for a whole
# documentation site on every scaffold.
DOC_LIMIT = 24000
README_NAMES = ("README.md", "README.rst", "README.txt", "README")
# Set to 1 to keep --scaffold from calling a model, as the test suite does.
NO_DRAFT = "QIKLY_NO_DRAFT"
CHECK = "CHECK"


# ------------------------------------------------------- what it may read --

def readme_text(module, cwd):
    """The README nearest the module and the project's own, as one text."""
    from qikly.start import project_root

    root = os.path.abspath(project_root(module, cwd))
    here = os.path.dirname(os.path.abspath(module))
    found, seen = [], set()
    while True:
        for name in README_NAMES:
            path = os.path.join(here, name)
            if os.path.isfile(path) and os.path.normcase(path) not in seen:
                seen.add(os.path.normcase(path))
                try:
                    with open(path, encoding="utf-8-sig", errors="replace") as handle:
                        found.append(handle.read())
                except OSError:
                    pass
                break
        if os.path.normcase(here) == os.path.normcase(root) or os.path.dirname(here) == here:
            break
        here = os.path.dirname(here)
    return "\n\n".join(found)[:DOC_LIMIT]


def interface_text(source):
    """
    The module's docstring, and each public function and class as its
    signature and docstring alone. No body is ever included: a body says what
    the code does, which is exactly what the draft must not be told.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    lines = []
    doc = ast.get_docstring(tree)
    if doc:
        lines += ['"""' + doc.strip() + '"""', ""]

    def signature(node, indent=""):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        lines.append(f"{indent}{prefix} {node.name}({ast.unparse(node.args)}):")
        doc = ast.get_docstring(node)
        lines.append(f'{indent}    """{doc.strip()}"""' if doc else f"{indent}    ...")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                signature(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            lines.append(f"class {node.name}:")
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'    """{doc.strip()}"""')
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and (not item.name.startswith("_") or item.name == "__init__")):
                    signature(item, "    ")
    return "\n".join(lines)


_LITERAL = re.compile(r"""^(-?\d+(\.\d+)?|'[^']*'|"[^"]*"|True|False|None)$""")


def public_callers(source):
    """
    {private function: the public functions that reach it}, by name only, so
    a question about a helper can say which part of the module it is about
    without showing a line of it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    calls = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls[node.name] = {c.func.id for c in ast.walk(node)
                                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    reach = {}
    for name in calls:
        if name.startswith("_"):
            continue
        seen, todo = set(), list(calls[name])
        while todo:
            callee = todo.pop()
            if callee in seen or callee not in calls:
                continue
            seen.add(callee)
            todo += calls[callee]
        for callee in seen:
            if callee.startswith("_"):
                reach.setdefault(callee, []).append(name)
    return {k: sorted(v) for k, v in reach.items()}


def neutral_question(q, callers=None):
    """
    The question as the spec agent may see it: the call it is about where
    qikly found one; otherwise every sentence of it with no code in it, the
    literal values kept, and the last sentence always, its code replaced by
    "it". `rate > 100` would tell the agent what the code does at 100; "what
    should happen at exactly 100?" does not. A private helper is named with
    the public functions that use it.
    """
    prompt = q.get("hint_prompt") or ""
    if "What should " in prompt:
        return "What should " + prompt.rpartition("What should ")[2].strip()
    text = (q.get("question") or "").strip()
    sentences = [x for x in re.split(r"(?<=[.?])\s+", text) if x]
    kept = []
    for n, sentence in enumerate(sentences):
        spans = re.findall(r"`([^`]*)`", sentence)
        code = [x for x in spans if not _LITERAL.match(x.strip())]
        if code and n < len(sentences) - 1:
            continue
        kept.append(re.sub(r"`([^`]*)`", lambda m: m.group(1)
                           if _LITERAL.match(m.group(1).strip()) else "it", sentence))
    where = q.get("function") or ""
    users = (callers or {}).get(where)
    if where and users:
        where += f" (used by {', '.join(users[:4])})"
    return (f"In {where}: " if where else "") + " ".join(kept)


# -------------------------------------------------------------- the agent --

def build_prompt(name, readme, interface, questions, callers=None):
    numbered = "\n".join(f"{n}. {neutral_question(q, callers)}"
                         for n, q in enumerate(questions, 1))
    return f"""You are writing the acceptance criteria for an existing Python module,
{name}, as its owner would: from what the module is for, never from what its
code happens to do. You are not shown the code, only its documentation.

Answer each numbered question with one acceptance criterion: one sentence
that names a concrete call and its expected result, such as
"apply_discount(100, 0) returns 100.0" or "label('VIP') returns 'gold'" or
"parse('') raises ValueError". Use the module's real function names and
arguments, as the documentation shows them.

Answer every question you can. A question about a private helper is about
the public functions that use it: answer it as a call to one of those. For
each answer, say where it comes from:
- "docs" when a sentence of the documentation below decides it. Then give that
  sentence, copied exactly, as "quote".
- "purpose" when nothing written decides it and you judged it from what the
  module is for, as a careful owner would. Then set "check" to true: a person
  will read those first.
Give "criterion": null only when no call to the module's public functions
could express the question at all.

Also write "requirements": one or two sentences for the programmer who will
repair the code, who reads them and never reads your criteria. Say what the
module is for and the units and conventions its arguments use, as the
documentation gives them: that a rate is a percentage, that prices are in a
currency with cents. Never a boundary value, a matching rule or an
expected result your criteria name: those must stay with the criteria.

Reply with JSON only. Every answer that has a quote or a judgement must have
its criterion written out as a call and its result. An example of the shape,
for a different module:
{{"requirements": "Converts temperatures; a temperature is in degrees Celsius.",
 "answers": [
  {{"question": 1, "criterion": "to_kelvin(0) returns 273.15", "source": "docs",
   "quote": "Zero Celsius is 273.15 kelvin.", "check": false}},
  {{"question": 2, "criterion": "to_kelvin(-300) raises ValueError", "source": "purpose",
   "quote": "", "check": true}},
  {{"question": 3, "criterion": null, "source": "purpose", "quote": "", "check": true}}]}}

THE DOCUMENTATION

{readme or "(no README)"}

THE MODULE'S INTERFACE: signatures and docstrings, no code

{interface or "(no public functions)"}

THE QUESTIONS

{numbered}
"""


def _squash(text):
    return re.sub(r"\s+", " ", re.sub(r"[`*_]", "", text or "")).strip().lower()


def quoted(quote, documentation):
    """
    Whether a quote is in the documentation: word for word, apart from case,
    spacing and markup, where an ellipsis may stand for words left out, as
    long as the pieces it joins appear in their order.
    """
    pieces = [p.strip(" .,;:") for p in re.split(r"\.\.\.|\u2026", _squash(quote))]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    at = 0
    for piece in pieces:
        found = documentation.find(piece, at)
        if found < 0:
            return False
        at = found + len(piece)
    return True


def draft(module, cwd, questions, seed=None, call=None):
    """
    {"requirements": str, "answers": {question number: {criterion, source,
    quote, check}}} from one model call, or None when nothing usable came
    back. A "docs" answer whose quote is not in the documentation is dropped.
    """
    from qikly.start import _read

    source = _read(module)
    readme = readme_text(module, cwd)
    interface = interface_text(source)
    prompt = build_prompt(os.path.basename(module), readme, interface, questions,
                          public_callers(source))
    if call is None:
        from qikly.agent_api.call_llm import call_llm as call
    if seed is None:
        # Seeded as a run is, so the same file drafts the same way twice.
        # 42 is cli.HARDCODED_SEED, the seed every run uses by default.
        seed = int(os.environ.get("AGENT_SEED") or 42)
    reply = call("spec_draft", prompt, seed=seed)
    found = re.search(r"\{.*\}", reply or "", re.S)
    if not found:
        return None
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    documentation = _squash(readme + "\n" + interface)
    answers, dropped = {}, 0
    for item in data.get("answers") or []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("question"))
        except (TypeError, ValueError):
            continue
        criterion = item.get("criterion")
        if not isinstance(criterion, str) or not criterion.strip():
            continue
        source_of = "docs" if item.get("source") == "docs" else "purpose"
        quote = item.get("quote") if isinstance(item.get("quote"), str) else ""
        if source_of == "docs" and not quoted(quote, documentation):
            # A quote that is not there is a claim with nothing behind it.
            dropped += 1
            continue
        answers[number] = {"criterion": " ".join(criterion.split()),
                           "source": source_of, "quote": " ".join(quote.split()),
                           "check": source_of == "purpose" or bool(item.get("check"))}
    requirements = data.get("requirements")
    return {"requirements": " ".join(requirements.split())
            if isinstance(requirements, str) else None,
            "answers": answers, "dropped": dropped}


# ---------------------------------------------------- into the task file --

def _quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def apply(text, drafted):
    """
    `text` with the drafted requirements line and criteria written in place
    of their TODOs, each criterion under a note saying where it came from.
    Returns (text, drafted count, count marked to check).
    """
    from qikly.score_questions import REQUIREMENT_MARK, _printable

    lines = text.split("\n")
    if drafted.get("requirements"):
        for i, line in enumerate(lines):
            if line.startswith("  - ") and REQUIREMENT_MARK in line:
                lines[i] = "  - " + _quote(_printable(drafted["requirements"]))
                lines.insert(i, "  #? Drafted by the spec agent from your README and "
                                "docstrings. Change it if it misses the point.")
                break
    start = next((i for i, l in enumerate(lines) if l.startswith("acceptance_criteria:")), None)
    if start is None:
        return "\n".join(lines), 0, 0
    number, done, check, i = 0, 0, 0, start + 1
    while i < len(lines):
        line = lines[i]
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        if re.match(r'^  - "TODO: ', line):
            number += 1
            answer = drafted["answers"].get(number)
            if answer:
                note = (f'  #? Drafted from your documentation: "{_printable(answer["quote"])}"'
                        if answer["source"] == "docs" else
                        f"  #? {CHECK}: drafted from the module's purpose; nothing "
                        f"written decides it.")
                lines[i] = "  - " + _quote(_printable(answer["criterion"]))
                lines.insert(i, note)
                done += 1
                check += answer["check"]
                i += 1
        i += 1
    return "\n".join(lines), done, check
