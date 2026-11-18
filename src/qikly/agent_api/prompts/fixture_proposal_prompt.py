import os

from qikly.agent_api.prompts.template_loader import load_template

# Enough of each fixture file for the model to see the column order and the
# shape of a normal row, and not so much that a large file crowds out the
# criteria it is meant to be compared against.
MAX_ROWS_PER_FILE = 40

# How much of a file to look at before deciding it is binary. A NUL byte near
# the start is the test git uses too. UTF-8 text never has one; UTF-16 and
# UTF-32 text always does, which is why a byte order mark is checked first.
_SNIFF_BYTES = 8192

# Longest first, because the UTF-32 little-endian mark begins with UTF-16's.
_BOMS = ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
         (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))


def _head(path):
    """The first bytes of a file, or None if it cannot be read."""
    try:
        with open(path, "rb") as handle:
            return handle.read(_SNIFF_BYTES)
    except OSError:
        return None


def text_encoding(path):
    """
    The codec to read a text fixture with. Excel's "Unicode Text" export is
    UTF-16 with a byte order mark, and read as UTF-8 it is noise.
    """
    head = _head(path) or b""
    for mark, codec in _BOMS:
        if head.startswith(mark):
            return codec
    return "utf-8"


def looks_binary(path):
    """
    True for a file that is not UTF-8 text and does not say which encoding it
    is: an image, an audio clip, a pickle, or UTF-16 with no byte order mark.

    Decoding one with errors="replace" never fails, which is the problem. It
    turns the bytes into replacement characters, and the model is then asked
    to propose rows for a "file" that is noise, or a count of its "rows" goes
    into a report. A file that cannot be read says False, so the caller's own
    handling of a missing file still applies.
    """
    head = _head(path)
    if head is None or text_encoding(path) != "utf-8":
        return False
    return b"\0" in head


def read_fixtures(paths, max_rows=MAX_ROWS_PER_FILE):
    """
    The fixture files as text, each under its own filename heading.

    Truncated per file rather than overall, so a task with one big input and
    one small one still shows both. A file that cannot be read is named and
    skipped: a missing fixture is a fact worth showing the model, since it
    explains why nothing exercises the criteria that depend on it.
    """
    blocks = []
    for path in paths:
        name = os.path.basename(path)
        if looks_binary(path):
            # Named, so the model knows the input exists, and said to hold no
            # rows, so it does not propose one for a file it cannot append to.
            blocks.append(f"### {name}\n(binary or non-UTF-8 file, {os.path.getsize(path)} "
                          f"bytes: contents not shown, and no row can be proposed for it)")
            continue
        try:
            with open(path, encoding=text_encoding(path), errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError as e:
            blocks.append(f"### {name}\n(could not be read: {type(e).__name__})")
            continue
        shown = lines[: max_rows + 1]          # +1 for the header
        body = "\n".join(shown)
        if len(lines) > len(shown):
            body += f"\n... {len(lines) - len(shown)} more row(s) not shown"
        blocks.append(f"### {name}\n{body}")
    return "\n\n".join(blocks) if blocks else "(this task declares no fixture files)"


def build_fixture_proposal_prompt(task, criteria, fixtures_text):
    """
    Ask which criteria no existing row can trigger, and what row would fix it.

    Criteria are numbered here rather than in the template, because the reply
    refers to them by number and the numbering has to be the same on both
    sides. Numbering in the prompt text and parsing by position would put the
    two a rename apart from disagreeing silently.
    """
    numbered = "\n".join(f'{i}. "{c}"' for i, c in enumerate(criteria, start=1))
    return load_template(
        "fixture_proposal_prompt.md",
        task=task,
        criteria=numbered,
        fixtures=fixtures_text,
    )
