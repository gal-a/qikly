"""
Acceptance criteria, read out of the place they were already written.

The largest thing standing between someone and their first qikly run is a blank
`acceptance_criteria:` list. That barrier is mostly imaginary: teams working in
Jira, Linear, Azure DevOps or a design doc have usually already written the
rules down, because their process asks for them before any code is cut. The
content is right there in a ticket. Only the container is wrong.

So this reads a ticket, a markdown file or a feature file and returns the
criteria in it. It is deliberately a parser and not an integration: no API
tokens, no OAuth, no vendor. Copy the ticket into a file, or pipe it in, and
the shape it is already in is the shape this understands.

## What it accepts, in the order these actually occur in the wild

**Bullet lists.** By far the common case. `-`, `*`, `+`, `1.` and `1)` all
count, at any indent.

**A headed section.** If something like "Acceptance Criteria" appears as a
heading or a bolded line, only what follows it is read, up to the next heading.
That is what lets a whole ticket be pasted in without the description becoming
criteria too.

**Gherkin.** `Scenario:` blocks with Given/When/Then, collapsed to one criterion
per scenario, because one scenario describes one rule. Supported because Xray,
Cucumber and SpecFlow speak it, and explicitly *not* treated as the expected
format: plain bullets are far more common in real tickets, and presenting
Given/When/Then as the standard would be an overclaim.

## What it does not do

It never guesses at prose. A paragraph is not split into sentences and offered
up as criteria, because a criterion that nobody wrote is exactly the kind of
invented bar this project argues against. If a file has no list and no
scenarios, the honest answer is that it contains none, and that is what comes
back.
"""
import re

# Lines that mark the start of a criteria section. Matched case-insensitively
# against the line with markdown decoration stripped, so "## Acceptance
# Criteria", "**Acceptance criteria:**" and "AC:" all land here.
_SECTION_HEADS = (
    "acceptance criteria", "acceptance critera", "acceptance_criteria",
    "criteria", "ac", "definition of done", "dod", "requirements to accept",
)

_BULLET = re.compile(r"^\s*(?:[-*+•]|\(?\d+[.)])\s+(.*\S)\s*$")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+|\*\*|__)?(.+?)(?:\*\*|__)?\s*:?\s*$")
_SCENARIO = re.compile(r"^\s*(?:Scenario(?: Outline)?|Example)\s*:\s*(.*)$", re.I)
_STEP = re.compile(r"^\s*(Given|When|Then|And|But)\s+(.*\S)\s*$", re.I)
_FEATURE_NOISE = re.compile(r"^\s*(?:Feature|Background|Rule)\s*:", re.I)


def _decorated_text(line):
    """A heading line reduced to its words, for matching against the heads."""
    text = line.strip().strip("#").strip()
    text = re.sub(r"^\*\*|\*\*$|^__|__$", "", text).strip()
    return text.rstrip(":").strip().lower()


def _looks_like_heading(line):
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    # A short bolded line on its own is a heading in most ticket templates.
    if (stripped.startswith("**") and stripped.endswith("**")) or (
            stripped.startswith("__") and stripped.endswith("__")):
        return True
    # "Acceptance Criteria:" with no decoration at all.
    return bool(re.match(r"^[A-Za-z][A-Za-z /_-]{1,40}:$", stripped))


def _gherkin(lines):
    """One criterion per scenario, steps joined into a sentence."""
    out, steps, open_scenario = [], [], False

    def flush():
        if steps:
            out.append(" ".join(steps))
        steps.clear()

    for line in lines:
        if _FEATURE_NOISE.match(line):
            flush()
            open_scenario = False
            continue
        scenario = _SCENARIO.match(line)
        if scenario:
            flush()
            open_scenario = True
            title = scenario.group(1).strip()
            if title:
                steps.append(title.rstrip(".") + ":")
            continue
        step = _STEP.match(line)
        if step and open_scenario:
            steps.append(f"{step.group(1).lower()} {step.group(2)}")
    flush()
    return out


def _section(lines):
    """
    The lines under a criteria heading, or every line if there is no heading.

    Returning everything when no heading is found is deliberate. A file that is
    only a list of criteria is a completely normal thing to be handed, and
    demanding a heading for it would fail the simplest case.
    """
    start = None
    for i, line in enumerate(lines):
        if _looks_like_heading(line) and _decorated_text(line) in _SECTION_HEADS:
            start = i + 1
            break
    if start is None:
        return lines
    end = len(lines)
    for j in range(start, len(lines)):
        if _looks_like_heading(lines[j]) and _decorated_text(lines[j]) not in _SECTION_HEADS:
            end = j
            break
    return lines[start:end]


def parse_criteria(text):
    """
    Every acceptance criterion in `text`, in the order it appears.

    Returns [] rather than guessing when the text holds no list and no
    scenarios. An empty result is a real answer: it means nobody wrote criteria
    here, which is worth being told plainly instead of being handed sentences
    chopped out of a paragraph.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    scenarios = _gherkin(lines)
    if scenarios:
        return scenarios

    body = _section(lines)
    out = []
    for line in body:
        bullet = _BULLET.match(line)
        if not bullet:
            continue
        item = bullet.group(1).strip()
        # Ticket lists often carry checkbox syntax. The box is markup, not a
        # criterion, and an unticked box is still a rule that must hold.
        item = re.sub(r"^\[[ xX]\]\s*", "", item).strip()
        if item:
            out.append(item)
    return out


def parse_file(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_criteria(handle.read())
