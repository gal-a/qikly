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
import functools
import json
import os
import re
import textwrap

# Enough for a README and a module's docstrings, without paying for a whole
# documentation site on every scaffold.
DOC_LIMIT = 24000
README_NAMES = ("README.md", "README.rst", "README.txt", "README")
# A project's documentation folder, read as well as its README: jambo explains
# that clear_ref_cache(None) clears every namespace only in
# docs/source/usage.ref_cache.rst, so a spec agent shown the README alone could
# not answer the question --score asked about it. Its own budget, so a long
# README does not crowd it out.
DOC_DIRS = ("docs", "doc")
DOCS_LIMIT = 24000
# Top-level files that are not about what the code should do: the README (read
# on its own, translations too), licences, contribution and conduct rules.
# requirements_spec.md and SECURITY_MODEL.md are kept: they may state intent.
_ROOT_SKIP = re.compile(
    r"(?i)(?:(?:readme|licen[cs]e|copying)(?:[-_.][\w.-]*)?"
    r"|(?:notice|authors|contributors|contributing|code[-_]of[-_]conduct|security"
    r"|governance|funding|third_party_notices)(?:\.[\w.]+)?)$")
# At the top level only these: a .txt there is as often a diff, a test log or
# saved output, whose code lines the docs filter cannot always recognise.
_ROOT_SUFFIXES = (".md", ".rst", ".markdown")
# A changelog names the module's functions in every entry and describes old
# behaviour too, so it is read after every other page, and never crowds one out.
_CHANGELOG = re.compile(r"(?i)(?:changelog|changes|history|news|release[-_]?notes)(?:[-_.][\w.-]*)?$")
# Set to 1 to keep --scaffold from calling a model, as the test suite does.
NO_DRAFT = "QIKLY_NO_DRAFT"
CHECK = "CHECK"
# The notes beside drafted answers in the task file. Each says where the
# answer came from and what to do with it: written for someone reading a task
# file for the first time, who does not know what a spec agent is.
DRAFTED_DOCS = "Answer below drafted by qikly from your README, docs or docstrings:"
READ_FIRST = "Read it before you run."
GUESSED = ("your docs don't say. The answer below is qikly's guess from what the "
           "module is for. " + READ_FIRST)


# ------------------------------------------------------- what it may read --

# What a README link may point at: documentation, never a source file. A
# README holding only "pricing.py" put the module's whole code in the prompt.
_DOC_SUFFIXES = (".md", ".rst", ".txt", ".markdown")


def _read_readme(path, root=None):
    """
    A README's text, following it when it is a symbolic link git could not
    make. tenacity's README.rst links to doc/source/index.rst, and a Windows
    checkout without symlink support writes the link as a file holding only
    that path: 20 characters, so the spec agent was told there was no README.
    Only to a documentation file inside the project.
    """
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        text = handle.read()
    target = text.strip()
    if target and "\n" not in target and len(target) < 260:
        linked = os.path.normpath(os.path.join(os.path.dirname(path), target))
        inside = root is None or os.path.normcase(os.path.abspath(linked)).startswith(
            os.path.normcase(os.path.abspath(root)) + os.sep)
        if os.path.isfile(linked) and linked.lower().endswith(_DOC_SUFFIXES) and inside:
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
                    found.append(_read_readme(path, root))
                except OSError:
                    pass
                break
        if os.path.normcase(here) == os.path.normcase(root) or os.path.dirname(here) == here:
            break
        here = os.path.dirname(here)
    return "\n\n".join(found)[:DOC_LIMIT]


def docs_text(module, cwd):
    """
    Pages of the project's docs/ (or doc/) folder, and its top-level doc files
    other than the README, licences and the like, that name one of the
    module's public functions, classes or methods, the most mentions first,
    up to DOCS_LIMIT characters. Documentation files only, never source: the
    spec agent must not see a function body. A page that names nothing from
    the module is left out, so a large documentation site does not crowd the
    relevant pages out of the prompt.
    """
    from qikly.start import _read, project_root

    root = os.path.realpath(project_root(module, cwd))
    try:
        source = _read(module)
        names = {n for n in interface_names(source) if len(n) > 2}
    except (OSError, ValueError):
        return ""
    if not names:
        return ""
    return _docs_text_cached(root, *_own_code(module, source), tuple(sorted(names)))


# A documentation file larger than this is a generated site or a data dump,
# not prose to quote.
_DOC_FILE_MAX = 400_000
# A code line this long or longer (whitespace removed), found in a docs page,
# is taken to be the module's own source; shorter lines ("return x") are too
# common to judge.
_SOURCE_LINE_MIN = 12
# Outside a code block, a part of a line is taken to be code only when it has
# an operator or bracket in it: a bare "media_id: str" or "TextChannel,
# VoiceChannel," from an argument list also reads as prose.
_OPERATOR = re.compile(r"[()=\[\]{}<>+*/%]")


def _normal(line):
    """
    A line as compared with the module's source: doctest prompts, a trailing
    comment and all whitespace taken out, so a body reformatted in a docs page
    or copied into a doctest still matches. A `#` inside a string is kept.
    """
    line = re.sub(r"^\s*(?:>>>|\.\.\.)(?=\s|$)", "", line)
    quote = None
    for at, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (at == 0 or line[at - 1].isspace()):
            line = line[:at]
            break
    return re.sub(r"\s+", "", line)


@functools.lru_cache(maxsize=64)
def _code_lines(source):
    """
    The source's code lines, normalised: the lines of its bodies. Left out are
    docstrings, comments, lines of punctuation alone, imports, decorators and
    the def and class lines with their signatures. Those are the interface,
    which the spec agent sees anyway, and users write the same lines in their
    own examples ("from pkg import load"); a "------" line is an rst
    underline too.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    skip = set()
    for node in ast.walk(tree) if tree else ():
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            skip.update(range(node.lineno, node.end_lineno + 1))
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            top = min([d.lineno for d in node.decorator_list] + [node.lineno])
            skip.update(range(top, node.body[0].lineno if node.body else node.lineno + 1))
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                skip.update(range(first.lineno, first.end_lineno + 1))
        # The inside of a multi-line string stays code, even when it looks
        # like markup: a C, YAML or diff string can too. A template that
        # renders the project's own docs pages costs those pages' matching
        # lines; that is the safe side.
    out = set()
    # Split as Python numbers lines: str.splitlines also splits on form feeds.
    for number, line in enumerate(re.split(r"\r\n|\r|\n", source), 1):
        if number in skip or line.lstrip().startswith("#"):
            continue
        line = _normal(line)
        if (len(line) >= _SOURCE_LINE_MIN and re.search(r"[A-Za-z0-9]", line)
                and not _IDIOM.match(line)):
            out.add(line)
    return frozenset(out)


# Lines any Python code has, normalised: matching one proves nothing. A
# keyword argument with a literal default ("bg_rgb=None,") is one too: an API
# list in the docs repeats them. One with a name as its value
# ("url=UPLOAD_ENDPOINT_V2,") stays code.
_IDIOM = re.compile(r"except.*:$|(\w+)=\1,?\)?$"
                    r"|\w+=(?:None|True|False|-?\d[\d.]*|'[^']*'|\"[^\"]*\")(?:,|\)|,\))$"
                    r"|super\(\)\.\w+\(.*\)$|return(?:self\.)?\w+$")


@functools.lru_cache(maxsize=64)
def _defined_names(source):
    """
    The functions and classes the source defines at its top level, private
    ones too. Not methods: a user's subclass that overrides `__init__` or
    `validate` in an example is how the module is used. A method's body shown
    under its own class is caught through the class's name.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()
    return frozenset(node.name for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def _sibling_sources(module, source):
    """
    The sources of the modules of the same package that this module imports
    (`from . import x`, `from .x import y`, `from .sub.x import y`, and the
    same through the package's name). A thin wrapper's behaviour lives in the
    module it delegates to, so that module's body must stay out of the prompt
    too. Imports from a parent package (`from ..x`) are not followed.
    """
    here = os.path.dirname(os.path.realpath(module))
    package = os.path.basename(here)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    wanted = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = node.module.split(".") if node.module else []
            if node.level == 0:
                if not parts or parts[0] != package:
                    continue
                parts = parts[1:]
            elif node.level != 1:
                continue
            if parts:
                wanted.add(tuple(parts))
            else:
                wanted.update((alias.name,) for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if len(parts) > 1 and parts[0] == package:
                    wanted.add(tuple(parts[1:]))
    found = []
    for parts in sorted(wanted):
        for path in (os.path.join(here, *parts) + ".py",
                     os.path.join(here, *parts, "__init__.py")):
            real = os.path.realpath(path)
            if (os.path.isfile(real) and real != os.path.realpath(module)
                    and real.startswith(here + os.sep)):
                try:
                    with open(real, encoding="utf-8-sig", errors="replace") as handle:
                        found.append(handle.read())
                except OSError:
                    pass
                break
    return tuple(found)


def _own_code(module, source=None):
    """
    The normalised code lines, and the names defined, of the module and of the
    siblings it imports: (lines, names).
    """
    if source is None:
        from qikly.start import _read
        try:
            source = _read(module)
        except (OSError, ValueError):
            return frozenset(), frozenset()
    lines, names = set(_code_lines(source)), set(_defined_names(source))
    for sibling in _sibling_sources(module, source):
        lines |= _code_lines(sibling)
        names |= _defined_names(sibling)
    return frozenset(lines), frozenset(names)


_GRAM = 8


@functools.lru_cache(maxsize=16)
def _index(own):
    """The code lines by their first 8 characters, to find one inside a line fast."""
    index = {}
    for code in own:
        index.setdefault(code[:_GRAM], []).append(code)
    return index


def _is_source(line, own, in_code):
    """
    A docs line that holds a code line of the module. In a code block, a
    doctest or a <pre>, any part of the line counts, so a body reformatted
    onto one line is caught. In prose, the whole line must be a code line, or
    hold one with an operator or bracket in it.
    """
    line = _normal(line)
    if len(line) < _SOURCE_LINE_MIN:
        return False
    if line in own:
        return True
    index = _index(own)
    for at in range(len(line) - _GRAM + 1):
        for code in index.get(line[at:at + _GRAM], ()):
            if line.startswith(code, at) and (
                    in_code or _OPERATOR.search(code)):
                return True
    return False


# Cached on the module's code and names: one CLI run drafts several answers
# from the same pages. A long-running process that drafts (the MCP server does
# not today) would need the pages' modification times in the key.
@functools.lru_cache(maxsize=16)
def _docs_text_cached(root, own, defined, names):
    # A mention is a call or a backticked name; a bare word counts only for a
    # name long enough not to be ordinary English ("get", "run", "load").
    called = re.compile(r"`?\b(?:%s)\b(?:\(|`)" % "|".join(re.escape(n) for n in names))
    worded = [n for n in names if len(n) >= 6]
    bare = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in worded)) if worded else None

    def mentions(text):
        return len(called.findall(text)) + (len(bare.findall(text)) if bare else 0)

    pages, seen = [], set()

    def consider(here, name, tier=0):
        if not name.lower().endswith(_DOC_SUFFIXES):
            return
        path = os.path.realpath(os.path.join(here, name))
        # The real file, inside the project, and a documentation file: a link
        # named usage.md that points at the module is code.
        if (not os.path.isfile(path)
                or not path.lower().endswith(_DOC_SUFFIXES)
                or not path.startswith(root + os.sep)
                or os.path.normcase(path) in seen):
            return
        seen.add(os.path.normcase(path))
        try:
            if os.path.getsize(path) > _DOC_FILE_MAX:
                return
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read()
        except OSError:
            return
        if not mentions(text):
            return  # not about this module: no need to filter it
        text = _without_code(text, own, defined)
        if text is None:
            return
        hits = mentions(text)
        if hits:
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            pages.append((tier, -hits, rel, text))

    for folder in DOC_DIRS:
        top = os.path.join(root, folder)
        if not os.path.isdir(top):
            continue
        for here, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs
                             if not d.startswith((".", "_")) and d not in ("build", "site"))
            for name in sorted(files):
                consider(here, name)
    # The project's top-level doc files besides the README, which is read on
    # its own: ydnatl documents pop(index=-1), "Remove last child", only in
    # LLM_GUIDE.md, and RetroFlow its layout rules in GROUP_BOX_PLAN.md.
    # CLAUDE.md and AGENTS.md count: they are the author's written intent.
    try:
        top_files = sorted(os.listdir(root))
    except OSError:
        top_files = []
    for name in top_files:
        if not _ROOT_SKIP.match(name) and name.lower().endswith(_ROOT_SUFFIXES):
            consider(root, name, 1 if _CHANGELOG.match(name) else 0)
    pages.sort()
    out, used = [], 0
    for _, _, rel, text in pages:
        chunk = f"--- {rel} ---\n{text}"
        room = DOCS_LIMIT - used
        if len(chunk) > room:
            if room < 2000:
                continue  # a smaller relevant page may still fit
            chunk = chunk[:room]  # the most relevant page, trimmed, beats none
        out.append(chunk)
        used += len(chunk)
    return "\n\n".join(out)


_CODE_DIRECTIVE = re.compile(r"^\s*\.\.\s+(?:code-block|code|sourcecode|literalinclude)::")
_DEFINES = re.compile(r"\s*(?:(?:>>>|\.\.\.)\s*)?(?:async\s+)?"
                      r"(?:def\s+(\w+)\s*\(|class\s+(\w+)\s*[(:])")
_INLINE_CODE = re.compile(r"^\s*(?:>>>|\.\.\.)(?:\s|$)|<pre|<code", re.IGNORECASE)


def _code_blocks(lines):
    """
    The page's code blocks, as (first, end, body_first, kept): lines first to
    end-1 are the block, its code starts at body_first, and kept is a header
    line to keep when the block goes ("Example::"), or None.
    """
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*(```|~~~)", line)
        # A line of tildes under a title, at least as long as the title and
        # followed by a blank line, is an rst section underline. A `~~~`
        # after a sentence, or with code right under it, is a fence.
        if (fence and fence.group(1) == "~~~" and i and lines[i - 1].strip()
                and not line.strip().strip("~")
                and len(line.strip()) >= len(lines[i - 1].strip())
                and (i + 1 >= len(lines) or not lines[i + 1].strip())):
            fence = None
        rst = _CODE_DIRECTIVE.match(line) or (line.rstrip().endswith("::")
                                                and not line.lstrip().startswith(".."))
        # A Markdown code block that defines something: indented four spaces,
        # after a blank line. Other indented text is left as prose: rst
        # indents the bodies of its directives, and those are documentation.
        indented = (not fence and not rst and re.match(r"(?: {4}|\t)\S", line)
                    and (i == 0 or not lines[i - 1].strip()) and _DEFINES.match(line))
        if not (fence or rst or indented):
            i += 1
            continue
        j = i + 1
        if fence:
            while j < len(lines) and not lines[j].lstrip().startswith(fence.group(1)):
                j += 1
            blocks.append((i, min(j + 1, len(lines)), i + 1, None))
            i = j + 1
            continue
        # The block's content is as indented as its first line, at least
        # deeper than a header's: a less indented line ends it, so the prose
        # after a code block nested in `.. note::` is not part of the block.
        start = i if indented else i + 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        if start >= len(lines):
            i += 1
            continue
        depth = len(lines[start]) - len(lines[start].lstrip())
        if not indented and depth <= len(line) - len(line.lstrip()):
            i += 1
            continue  # nothing indented under the header: not a block
        j = start
        while j < len(lines) and (not lines[j].strip()
                                  or len(lines[j]) - len(lines[j].lstrip()) >= depth):
            j += 1
        if indented:
            blocks.append((i, j, i, None))
        else:
            blocks.append((i, j, i + 1, None if _CODE_DIRECTIVE.match(line) else i))
        i = max(j, i + 1)
    return blocks


def _looks_like_python(text):
    """A page that parses as Python and defines something: a copy of code."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for node in tree.body)


_PROMPT = re.compile(r"^(\s*)(?:>>> |\.\.\. )")
_STATEMENT = re.compile(r"^\s*(?:return|raise|yield|if|elif|for|while|with|try|assert|await)\b"
                        r"|^\s*[\w.\[\]]+\s*[-+*/%|&]?=(?!=)|^\s+[\w.]+\(.*\)\s*$")


def _has_body(block):
    """
    A block whose definitions do something: a statement under a def beyond a
    docstring, `...` or `pass`. A list of signatures is an API reference.
    """
    plain = [_PROMPT.sub(r"\1", line) for line in block
             if not re.match(r"\s*(?:```|~~~)", line)]  # a closing fence
    try:
        tree = ast.parse(textwrap.dedent("\n".join(plain)))
    except (SyntaxError, ValueError):
        return any(_STATEMENT.match(line) for line in plain[1:])
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in node.body:
                if isinstance(stmt, ast.Pass) or (
                        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)):
                    continue  # pass, a docstring or `...`
                return True
    return False


def _without_code(text, own, defined=frozenset()):
    """
    The page with the module's code taken out, or None when the page is a copy
    of code (a module saved as .txt). The spec agent must never see a function
    body, and documentation pages can hold one.

    A code block that defines a function or class goes whole when it holds a
    line of the module's code (or of a sibling it imports), or gives a body to
    a function or class of the same name. A block that only lists the module's
    signatures (stubs with `...` or a docstring) is kept: that is an API
    reference. So is a block that defines only the user's own callback: it is
    how the module is used. Anywhere else, only the lines that hold the
    module's code go. A body that differs from the current code (an old
    version, rewritten) under another name cannot be told from an example.
    """
    if _looks_like_python(text):
        return None
    lines = text.splitlines()
    in_code = [bool(_INLINE_CODE.search(line)) for line in lines]
    blocks = _code_blocks(lines)
    for first, end, body, _ in blocks:
        for k in range(body, end):
            in_code[k] = True
    source = ([_is_source(line, own, code) for line, code in zip(lines, in_code)]
              if own else [False] * len(lines))
    # Much of the module, and most of the page: a copy of the code that did
    # not parse as a whole. (One that parses was caught above.)
    matched = sum(source)
    counted = sum(1 for line in lines if line.strip())
    if own and matched >= max(3, len(own) // 3) and matched * 2 >= counted:
        return None
    drop = [False] * len(lines)
    for first, end, body, kept in blocks:
        block = lines[body:end]
        names = {m.group(1) or m.group(2) for m in map(_DEFINES.match, block) if m}
        held = sum(source[body:end])
        # One shared line ("id: Mapped[int] = mapped_column(") in a user's own
        # example costs that line; two, or a third of the block, are a body.
        if names and ((names & defined and _has_body(block)) or held >= 2
                      or (held and held * 3 >= sum(1 for b in block if b.strip()))):
            for k in range(first, end):
                drop[k] = k != kept
    return "\n".join(line for k, line in enumerate(lines)
                     if not drop[k] and not source[k])


def all_docs(module, cwd):
    """
    The README and the documentation folder's relevant pages, as one text,
    with the module's code taken out of both.
    """
    readme = readme_text(module, cwd)
    if readme:
        readme = _without_code(readme, *_own_code(module)) or ""
    return "\n\n".join(t for t in (readme, docs_text(module, cwd)) if t)


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

    for node in _public_top(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature(node)
        else:
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
# Fewer words than this in a quote, and it proves nothing about the answer.
QUOTE_WORDS = 4


def _public_top(tree):
    """
    The module's public functions and classes, each under the name callers
    use, the same set the task file's interface lists (scaffold's
    top_definitions): msgspec-ext defines _EmailStr and exports EmailStr.
    """
    from qikly.scaffold import top_definitions
    return top_definitions(tree)


def public_docstrings(source):
    """
    The docstrings `interface_text` shows the spec agent, and no others: the
    module's, and each public function's, class's and public method's.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    nodes = [tree]
    for node in _public_top(tree):
        nodes.append(node)
        if isinstance(node, ast.ClassDef):
            nodes += [item for item in node.body
                      if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and (not item.name.startswith("_") or item.name == "__init__")]
    return [doc for doc in (ast.get_docstring(n) for n in nodes) if doc]


def documentation(module, cwd):
    """
    The README and the docstrings the spec agent is shown: what a draft may
    rest on. Every docstring in the file used to count, so a private helper's
    could pass the minimum while the agent itself saw only function names.
    """
    from qikly.start import _read
    return (all_docs(module, cwd) + "\n" + "\n".join(public_docstrings(_read(module)))).strip()


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
            signatures.append((node.lineno, node.body[0].lineno, node))
    out = []
    for q in questions:
        line, code = q.get("line"), q.get("code") or ""
        here = [n for start, first, n in signatures
                if isinstance(line, int) and start <= line < first]
        found = _PARAMETER.match(code)
        name = found.group(1) if found and here else None
        if name and _defaults_on_line(here[-1], line) > 1:
            # "a=1, b=-1, key=lambda x: x + 1": the first name on the line is
            # not necessarily the default the change flipped.
            name = None
        if name is None and here:
            # A one-line def, or a signature line _PARAMETER cannot read:
            # pywho's "*, include_packages: bool = True, include_pip: bool =
            # True", whose first default is the behaviour its PR #73 tests.
            name = _default_on_line(here[-1], line, q.get("change") or "")
        if name and name not in ("self", "cls"):
            q = dict(q, parameter=name)
        out.append(q)
    return out


def _defaults_on_line(node, line):
    """How many of the function's parameter defaults sit on `line`."""
    a = node.args
    return sum(1 for d in list(a.defaults) + list(a.kw_defaults)
               if d is not None and d.lineno == line)


def _default_on_line(node, line, change):
    """
    The parameter whose default sits on `line` and is the value a change
    flipped. When several on the line have that value the change does not say
    which, so all are named ("include_packages or include_pip"); the spec
    agent sees every signature anyway.
    """
    before = re.match(r"\s*\w+\s+(.+?)\s+->", change)
    if not before:
        return None
    a = node.args
    positional = a.posonlyargs + a.args
    pairs = list(zip(positional[len(positional) - len(a.defaults):], a.defaults))
    pairs += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
    value = before.group(1)
    holding = [(arg.arg, d) for arg, d in pairs
               if d.lineno == line and arg.arg not in ("self", "cls")
               and any(isinstance(n, ast.Constant) and ast.unparse(n) == value
                       for n in ast.walk(d))]
    # One default holds the flipped value (ydnatl's index=-1, whose 1 is
    # flipped), or several are exactly that value; otherwise the change could
    # be in any of them (a=1, b=-1, key=lambda x: x + 1), so none is named.
    if len(holding) == 1:
        return holding[0][0]
    if holding and all(ast.unparse(d) == value for _, d in holding):
        return " or ".join(name for name, _ in holding)
    return None


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
    # A quote is what lets an answer skip review, so it has to say something:
    # "slug", "a" and "Slug ... configurable" all passed, being somewhere in
    # any README. Four words in all, and two in every piece an ellipsis joins.
    if (not pieces or sum(len(p.split()) for p in pieces) < QUOTE_WORDS
            or any(len(p.split()) < 2 for p in pieces)):
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
    line and the text still says where the break was. Every other character YAML
    reads as a line break too (a lone carriage return, U+0085, U+2028, U+2029):
    one of those split a criterion in two and shifted every later one.
    """
    from qikly.score_questions import exact_text

    return exact_text(text)


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
# A whole call with its arguments, one level of brackets: apply_discount(100, 100).
_CALL_TEXT = re.compile(r"\b[A-Za-z_][\w.]*\([^()]*\)")


# A criterion that says only that a call works. On jambo the one drafted
# answer was "clear_ref_cache() runs without error": the test written from it
# could not tell a cache that cleared from one that did not.
_ONLY_WORKS = re.compile(
    r"\b(?:runs?|succeeds?|works?|completes?|executes?)\b"
    r"|\bwithout (?:an? )?(?:error|exception)s?\b"
    r"|\b(?:does not|doesn't|never) (?:raises?|fails?|errors?|crash(?:es)?)\b"
    r"|\bno (?:error|exception)s?\b", re.IGNORECASE)
# What a criterion says when it does name an outcome.
_RESULT_VERB = (
    r"\b(?:return|raise|equal|give|yield|produce|contain|include|become|hold|write"
    r"|print|reject|accept|leave|clear|remove|add|set|keep|output|exist|emit|log"
    r"|store|save|create|delete|update|append|match)(?:s|es|ing|ed)?\b")
_STATES_A_RESULT = re.compile(
    _RESULT_VERB + r"|\b(?:is|are|has|have)\b|==|!=|\bTrue\b|\bFalse\b|\bNone\b",
    re.IGNORECASE)
# A condition says when, not what: "works when x is 0" names no result. It
# ends at a comma, a semicolon or an "and" that goes on to a result:
# "succeeds when the server is up and returns the body" and "works when the
# list is empty and the total is zero" both name one. The cost: "works when x
# is 0 and y is 1" is read as naming one too, a missed warning, not a false one.
_CONDITION = re.compile(
    r"\b(?:when|whenever|if|unless|for|given|on)\b.*?"
    r"(?=[,;]|\band\b(?=[^,;]*?(?:%s|\b(?:is|are|equals?|says?|has|have)\b))|$)"
    % _RESULT_VERB, re.IGNORECASE)
# A call, its name included: "update(cfg) works" names no result, though
# "update" is a result verb.
_BRACKETED_CALL = re.compile(r"[A-Za-z_][\w.]*\x01")
# A number or a quoted value outside a call's brackets is a stated result:
# "completes 5 jobs", "succeeds with status 200". Its own name: it once shared
# _LITERAL's, and replacing that at import let neutral_question show the spec
# agent code such as `'(' in sys.version` and drop True, False and None.
_STATED_VALUE = re.compile(r"\d|'[^']*'|\"[^\"]*\"")


def weak_criterion(criterion):
    """
    Why a criterion needs a second look, or None: it says only that a call
    runs or does not fail, and names no value, error or effect a test could
    check. A test written from it passes whatever the call returns.
    """
    if not _ONLY_WORKS.search(criterion):
        return None
    # A call's arguments ("apply_discount(100, 0)") are the input, not a result.
    rest, before = criterion, None
    while rest != before:  # nested brackets, innermost first
        before, rest = rest, re.sub(r"\([^()]*\)", "\x01", rest)
    rest = _BRACKETED_CALL.sub(" it ", rest).replace("\x01", " ")
    rest = _CONDITION.sub(" ", _ONLY_WORKS.sub(" ", rest))
    if _STATES_A_RESULT.search(rest) or _STATED_VALUE.search(rest):
        return None
    return ("it names no expected value: a test written from it passes "
            "whatever the call returns. Say what the call should return, "
            "raise or change")


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
    # The same call, another result: the quote shows `slugify('one two') ==
    # 'one-two'` and the answer says it returns 'one_two'. Only compared when
    # both say what comes back, after spacing and quote marks are evened out.
    told, said = _results(quote, names), _results(criterion, names)
    for key in sorted(set(told) & set(said)):
        if told[key] != said[key]:
            return (f"the quote's example of {key[0]}() gives another result than this "
                    f"answer does")
    return None


def _norm(text):
    """Text compared as code: no spaces, one kind of quote mark."""
    return re.sub(r"\s+", "", text).replace('"', "'").rstrip(".,;")


def _call_spans(text, names):
    """(function, argument text, end of the call) for each call to one of `names`."""
    text = text or ""
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
                    yield name, text[start + 1:at], at + 1
                    break


def _calls(text, names):
    """{function: {argument text, compared as code}} for each call to one of `names`."""
    found = {}
    for name, args, _ in _call_spans(text, names):
        found.setdefault(name, set()).add(_norm(args))
    return found


_RESULT = re.compile(r"^\s*(?:==|returns|->|gives|is)?\s*(?P<result>[^\s].*?)\s*$")


def _results(text, names):
    """{(function, arguments): what the text says it returns}, where it says."""
    text = text or ""
    found = {}
    for name, args, end in _call_spans(text, names):
        rest = text[end:].split(">>>")[0]
        if re.match(r"\s*raises\b", rest):
            continue
        got = _RESULT.match(rest)
        if got and got.group("result"):
            found[(name, _norm(args))] = _norm(got.group("result"))
    return found


def draft(module, cwd, questions, seed=None, call=None):
    """
    {"requirements": str, "answers": {question number: {criterion, source,
    quote, check}}} from one model call, or None when nothing usable came
    back. A "docs" answer whose quote is not in the documentation is dropped.
    """
    from qikly.start import _read

    source = _read(module)
    readme = all_docs(module, cwd)
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
    # The first complete JSON object in the reply. A greedy match from the
    # first brace to the last made any brace after the JSON, in a note or a
    # code fence, an unreadable reply.
    data, reply = None, reply or ""
    decoder = json.JSONDecoder()
    for start in (m.start() for m in re.finditer(r"\{", reply)):
        try:
            candidate, _ = decoder.raw_decode(reply, start)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            data = candidate
            break
    if data is None:
        return None
    # Quotes are checked against prose, not signatures: the interface text
    # holds every `def` line, and "def f(x, strict=False):" passed as a quote.
    documentation = _squash(readme + "\n" + "\n".join(public_docstrings(source)))
    names = interface_names(source)
    answers, dropped = {}, 0
    for item in data.get("answers") or []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("question"))
        except (TypeError, ValueError):
            continue
        if not 1 <= number <= len(questions):
            # An answer to a question nobody asked: shown on screen, it was
            # never written to the file, so the screen and the file disagreed.
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
        why = ((other_function(quote, criterion, names) if source_of == "docs" else None)
               or weak_criterion(criterion))
        answers[number] = {"criterion": criterion_text(criterion),
                           "source": source_of, "quote": " ".join(quote.split()),
                           "check": source_of == "purpose" or bool(item.get("check")) or bool(why),
                           "why": why}
    requirements = data.get("requirements")
    requirements = " ".join(requirements.split()) if isinstance(requirements, str) else None
    # The requirements line is the one thing drafted here that the coding
    # agent reads. The spec agent sees every question, so it can write a
    # criterion into it, and only the prompt asked it not to: a requirement
    # saying "apply_discount(100, 100) raises ValueError" handed the answer to
    # the agent being tested. Checked here, with the measure --validate uses,
    # and with the plainest test there is: a call a criterion makes.
    leaked = False
    if requirements:
        from qikly.from_doc import restated
        criteria = [a["criterion"] for a in answers.values()]
        calls = {c for a in answers.values() for c in _CALL_TEXT.findall(a["criterion"])}
        leaked = bool(restated([requirements], criteria)) or any(
            call in requirements for call in calls)
        if leaked:
            requirements = None
    return {"requirements": requirements, "answers": answers, "dropped": dropped,
            "requirements_dropped": leaked}


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
                lines.insert(i, "  #? Drafted by qikly from your README, docs and docstrings. "
                                "Change it if it misses the point.")
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
                note = (f'  #? {DRAFTED_DOCS} "{_printable(answer["quote"])}". '
                        f"Keep it, or change it."
                        if answer["source"] == "docs" else
                        f"  #? {CHECK}: {GUESSED}")
                lines[i] = "  - " + _quote(criterion_text(answer["criterion"]))
                lines.insert(i, note)
                done += 1
                check += answer["check"]
                i += 1
                if answer.get("why"):
                    lines.insert(i, f"  #? {CHECK}: {_printable(answer['why'])}. {READ_FIRST}")
                    i += 1
                elif answer["check"] and answer["source"] == "docs":
                    # Counted and shown as CHECK, so marked CHECK in the file
                    # too: --take-tests reads its labels from here.
                    lines.insert(i, f"  #? {CHECK}: qikly was unsure of this answer. {READ_FIRST}")
                    i += 1
        i += 1
    return "\n".join(lines), done, check
