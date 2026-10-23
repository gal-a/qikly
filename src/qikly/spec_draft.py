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

def _read_readme(path):
    """
    A README's text, following it when it is a symbolic link git could not
    make. tenacity's README.rst links to doc/source/index.rst, and a Windows
    checkout without symlink support writes the link as a file holding only
    that path: 20 characters, so the spec agent was told there was no README.
    """
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        text = handle.read()
    target = text.strip()
    if target and "\n" not in target and len(target) < 260:
        linked = os.path.normpath(os.path.join(os.path.dirname(path), target))
        if os.path.isfile(linked):
            with open(linked, encoding="utf-8-sig", errors="replace") as handle:
                return handle.read()
    return text


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
                    found.append(_read_readme(path))
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


# Fewer characters of README and docstrings than this, and there is nothing to
# draft from: with function names alone, the agent guessed that label('VIP')
# raises ValueError, every answer a guess.
MIN_DOCS = 80


def documentation(module, cwd):
    """The README and the module's docstrings: what a draft may rest on."""
    from qikly.start import _read
    try:
        tree = ast.parse(_read(module))
    except SyntaxError:
        tree = None
    docs = []
    if tree is not None:
        for node in [tree] + list(ast.walk(tree)):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc:
                    docs.append(doc)
    return (readme_text(module, cwd) + "\n" + "\n".join(docs)).strip()


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


_PARAMETER = re.compile(r"^\s*\**([A-Za-z_]\w*)\s*[:=]")


def with_parameters(questions, source):
    """
    `questions` with the parameter named where a question is about a
    parameter's default: the question about iniconfig's
    `strip_section_whitespace: bool = False,` reached the spec agent as "Your
    tests pass with this False flipped", which says nothing of which one. The
    agent already reads every signature with its defaults, so the name
    reveals nothing of the code. Copies; the originals are the saved questions.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return questions
    signatures = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            signatures.append((node.lineno, node.body[0].lineno))
    out = []
    for q in questions:
        line, code = q.get("line"), q.get("code") or ""
        found = _PARAMETER.match(code)
        if (found and isinstance(line, int) and found.group(1) not in ("self", "cls")
                and any(start <= line < first for start, first in signatures)):
            q = dict(q, parameter=found.group(1))
        out.append(q)
    return out


def in_classes(questions, source):
    """
    `questions` with a method's name given with its class: step 1 records
    `parse` or `__init__` alone, which says nothing about which part of a
    module made of classes the question is about. Copies; the originals are
    the saved questions.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return questions
    spans = [(n.lineno, getattr(n, "end_lineno", n.lineno), n.name)
             for n in tree.body if isinstance(n, ast.ClassDef)]
    out = []
    for q in questions:
        line, name = q.get("line"), q.get("function")
        owner = next((c for start, end, c in spans
                      if isinstance(line, int) and start <= line <= end), None)
        if owner and name and "." not in name and name != owner:
            q = dict(q, function=owner if name == "__init__" else f"{owner}.{name}")
        out.append(q)
    return out


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
    about = f"About the default of the parameter {q['parameter']}. " if q.get("parameter") else ""
    return (f"In {where}: " if where else "") + about + " ".join(kept)


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

Each criterion must answer its own question: the call must use the input the
question is about, so that the expected result depends on the answer. A
question about inputs that differ only by spaces around them is answered with
such an input, as in "parse(' 12 ') returns 12"; a question about a value, a
boundary or an option is answered with a call that uses that value, sits on
that boundary or sets that option. A true statement about the module that
would hold whatever the answer is does not answer the question.

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


def criterion_text(text):
    """
    A drafted criterion as one line, its spaces kept exactly.

    It used to be squeezed like prose, every run of spaces made one, which
    rewrote an expected output: tabulate aligns its columns with runs of
    spaces, so `'strings      numbers'` became a string no table prints. A line
    break becomes a visible `\\n`, so the task file keeps one criterion to a
    line and the text still says where the break was.
    """
    from qikly.score_questions import _UNPRINTABLE

    text = str(text).strip().replace("\r\n", "\n").replace("\n", "\\n").replace("\t", "\\t")
    return _UNPRINTABLE.sub("?", text)


def interface_names(source):
    """
    The module's public function, class and method names, the last part of
    each, and whatever it exports in `__all__`: python-slugify defines
    `smart_truncate` elsewhere and re-exports it from `slugify.py`.
    """
    from qikly.scaffold import read_interface
    try:
        names = {m.name.rpartition(".")[2] for m in read_interface(source)}
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__"
                                                 for t in node.targets)
                and isinstance(node.value, (ast.List, ast.Tuple))):
            names |= {e.value for e in node.value.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return names


_CALL = re.compile(r"\b([A-Za-z_][\w.]*)\s*\(")


def other_function(quote, criterion, names):
    """
    Why a drafted answer needs a second look, or None: its quote shows a call
    to one of the module's functions and the answer calls a different one.

    On python-slugify the README's example was `slugify('one two three
    four', max_length=12, word_boundary=True) == 'one-two-four'`, quoted word
    for word, and the answer gave that result to `smart_truncate`, whose
    separator is a space. The quote check passed it; only the names differ.
    Only the module's own names count, so a `Decimal(...)` in a quote is not
    taken for a call the answer had to make.
    """
    shown, used = _calls(quote, names), _calls(criterion, names)
    if shown and used and not set(shown) & set(used):
        return (f"the quote's example calls {', '.join(sorted(shown))}(), and this "
                f"answer calls {', '.join(sorted(used))}() instead")
    # The same function, other arguments: the expected result is then the
    # agent's, not the documentation's. price-parser's docstring showed
    # parse_number("12,34") and the answer asked about "12€34"; tabulate's
    # README showed "colon_grid" and the answer asked for "plain" and wrote
    # its own table.
    for name in sorted(set(shown) & set(used)):
        if not used[name] & shown[name]:
            return (f"the quote's example calls {name}() with other arguments, so "
                    f"the expected result here is the agent's, not your documentation's")
    return None


def _calls(text, names):
    """{function: {argument text, spaces removed}} for each call to one of `names`."""
    text = text or ""
    found = {}
    for match in _CALL.finditer(text):
        name = match.group(1).rpartition(".")[2]
        if name not in names:
            continue
        depth, start = 0, match.end() - 1
        for at in range(start, len(text)):
            if text[at] in "([{":
                depth += 1
            elif text[at] in ")]}":
                depth -= 1
                if depth == 0:
                    found.setdefault(name, set()).add(re.sub(r"\s+", "", text[start + 1:at]))
                    break
    return found


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
    prompt = build_prompt(os.path.basename(module), readme, interface,
                          in_classes(with_parameters(questions, source), source),
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
    names = interface_names(source)
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
        why = other_function(quote, criterion, names) if source_of == "docs" else None
        answers[number] = {"criterion": criterion_text(criterion),
                           "source": source_of, "quote": " ".join(quote.split()),
                           "check": source_of == "purpose" or bool(item.get("check")) or bool(why),
                           "why": why}
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
                lines[i] = "  - " + _quote(criterion_text(answer["criterion"]))
                lines.insert(i, note)
                done += 1
                check += answer["check"]
                i += 1
                if answer.get("why"):
                    lines.insert(i, f"  #? {CHECK}: {_printable(answer['why'])}.")
                    i += 1
        i += 1
    return "\n".join(lines), done, check
