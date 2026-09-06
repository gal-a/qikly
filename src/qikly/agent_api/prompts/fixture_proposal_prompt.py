import os

from qikly.agent_api.prompts.template_loader import load_template

# Enough of each fixture file for the model to see the column order and the
# shape of a normal row, and not so much that a large file crowds out the
# criteria it is meant to be compared against.
MAX_ROWS_PER_FILE = 40


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
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
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
