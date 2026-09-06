"""
Retrieval within a file: showing a large module's relevant parts, not all of it.

Until now a PATCH prompt loaded every file the preceding FIX named, and loaded
each one whole. That is fine when a module is two hundred lines and impossible
when it is five thousand: the file either fits in the prompt or the run cannot
proceed, and there was no third option. It is the single reason this tool has
been described as working on modules rather than on repositories.

This is the third option. A file over the threshold is not truncated and not
summarised. It is parsed, and the symbols that matter are reproduced verbatim
while the rest collapses to signatures.

## Why AST rather than embeddings

Nothing here is a similarity search. The relevant symbols are *named*, by the
FIX that said which files it would touch and by the failing tests that said
what broke, so the retrieval problem is a lookup rather than a guess. An
embedding index would add a model call, a stored artifact, a similarity
threshold and a new way to be wrong, in exchange for solving a problem that is
already solved by reading the failure message.

It also keeps the property the rest of the project depends on: this is
deterministic. The same file and the same failing test produce the same
excerpt, every time, on any machine, with no API key.

## What the model sees

Whole, verbatim:

  - every import and module-level assignment, because a patch that cannot see
    the imports will reintroduce one that already exists
  - every symbol named as relevant, with its decorators and docstring
  - the enclosing class of a relevant method, with its other methods elided,
    so an indented diff has somewhere to anchor

Collapsed to one line each:

  - every other function and class, as `def name(args): ...`, so the model
    knows what exists and does not invent a second implementation of it

The elisions are marked with a comment giving the line numbers removed, so a
unified diff can still be produced against the real file. A patch tool needs
line numbers, and an excerpt that silently renumbered would produce diffs that
do not apply.
"""
import ast
import io
import os

# Below this, a file goes in whole. Excerpting a small module costs clarity and
# saves nothing, and whole-file context is strictly better when it is
# affordable. Roughly 400 lines of typical Python.
DEFAULT_MAX_CHARS = 16000

ENV_MAX_CHARS = "QIKLY_MAX_FILE_CHARS"


def max_chars():
    """The threshold, overridable for a model with a much larger context."""
    raw = os.environ.get(ENV_MAX_CHARS)
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_CHARS


def _segment(node):
    """The full source span of a definition, decorators included."""
    start = min([d.lineno for d in getattr(node, "decorator_list", [])] +
                [node.lineno])
    return start, getattr(node, "end_lineno", node.lineno)


def _signature(node, source_lines):
    """One line standing in for a definition that was elided."""
    start, _ = _segment(node)
    text = source_lines[node.lineno - 1].strip()
    # A signature can wrap over several lines; take up to the colon.
    line = node.lineno
    while not text.rstrip().endswith(":") and line < len(source_lines):
        line += 1
        text += " " + source_lines[line - 1].strip()
    return f"{text} ...", start


def relevant_names(text):
    """
    Every identifier in a blob of text, for matching against symbol names.

    Deliberately crude. The inputs are a FIX's prose and a pytest failure
    report, and over-matching costs a few extra lines of context while
    under-matching costs the model the function it needed. The asymmetry is not
    close, so this errs toward including.
    """
    import re

    return {m for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or "")}


def excerpt_source(source, wanted, path="<file>"):
    """
    `source` with irrelevant definitions collapsed to signatures.

    Returns the source unchanged when it cannot be parsed. A file the agent is
    part way through writing is often not valid Python, and that is exactly
    when it most needs to be seen in full: excerpting it would hide the syntax
    error the next patch has to fix.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.split("\n")
    keep = set()      # line numbers reproduced verbatim
    elided = []       # (start, end, replacement_line)

    def wants(node):
        return node.name in wanted

    def handle(node, inside_kept_class=False):
        start, end = _segment(node)
        if wants(node) or inside_kept_class:
            keep.update(range(start, end + 1))
            return True
        signature, sig_start = _signature(node, lines)
        elided.append((start, end, signature, sig_start))
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handle(node)
        elif isinstance(node, ast.ClassDef):
            methods = [n for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            class_wanted = wants(node)
            method_wanted = [m for m in methods if wants(m)]
            if class_wanted or method_wanted:
                # Keep the class statement and anything that is not a method,
                # so a patch has the class body to anchor against.
                start, end = _segment(node)
                body_starts = [_segment(m)[0] for m in methods]
                first_method = min(body_starts) if body_starts else end + 1
                keep.update(range(start, first_method))
                for method in methods:
                    handle(method, inside_kept_class=class_wanted or method in method_wanted)
            else:
                handle(node)
        else:
            start = getattr(node, "lineno", None)
            if start:
                keep.update(range(start, getattr(node, "end_lineno", start) + 1))

    if not elided:
        return source

    out, skip_until, emitted = [], 0, 0
    by_start = {e[0]: e for e in elided}
    for number, line in enumerate(lines, start=1):
        if number < skip_until:
            continue
        if number in by_start:
            start, end, signature, _ = by_start[number]
            indent = " " * (len(line) - len(line.lstrip()))
            out.append(f"{indent}{signature}")
            out.append(f"{indent}# ... body elided, lines {start}-{end} of {path}")
            emitted += 1
            skip_until = end + 1
            continue
        out.append(line)

    header = (
        f"# EXCERPT: {emitted} definition(s) collapsed to signatures because "
        f"this file is {len(source)} characters.\n"
        f"# Imports, module constants and the definitions relevant to this "
        f"failure are reproduced in full.\n"
        f"# Elided line ranges are marked, so line numbers below are the real "
        f"ones in {path}.\n"
    )
    return header + "\n".join(out)


def excerpt_file(path, wanted, limit=None):
    """Read `path`, excerpting it if it is over the threshold."""
    with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    if len(source) <= (limit if limit is not None else max_chars()):
        return source
    return excerpt_source(source, wanted, path=path)
