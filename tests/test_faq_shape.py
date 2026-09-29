"""
The FAQ's two house rules, enforced rather than remembered.

Both come from the same observation: the page is read by someone deciding
whether to try the tool, and it stops working as soon as an answer turns into
an essay. The long answer that prompted this had grown to 95 lines and was
split into `EXISTING_CODE_AND_HELPERS.md`.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAQ = os.path.join(ROOT, "docs", "FAQ.md")

# Long enough for a real answer with a code block in it, short enough that an
# answer growing into a page trips it. The rule is "link to the detail", not
# "leave the detail out".
MAX_LINES = 26


def _text():
    with open(FAQ, encoding="utf-8") as handle:
        return handle.read()


def _questions():
    """(heading line number, heading text) for every question, in order."""
    found = []
    for number, line in enumerate(_text().split("\n"), start=1):
        if line.startswith("## "):
            found.append((number, line[3:].strip()))
    return found


def test_the_faq_still_has_questions_in_it():
    """So that a rename cannot turn both rules below into vacuous passes."""
    assert len(_questions()) >= 5


def test_every_question_is_numbered_in_sequence_from_one():
    for expected, (line_number, heading) in enumerate(_questions(), start=1):
        match = re.match(r"^(\d+)\. \S", heading)
        assert match, (
            "FAQ.md line %d: every question is numbered, so this one needs a "
            "number too: %r" % (line_number, heading))
        assert int(match.group(1)) == expected, (
            "FAQ.md line %d: questions run in sequence from 1, so this should "
            "be %d rather than %s. Renumber the ones after an insertion."
            % (line_number, expected, match.group(1)))


def test_no_answer_has_grown_into_an_article():
    lines = _text().split("\n")
    starts = [n for n, _ in _questions()]
    overlong = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines)
        body = [l for l in lines[start:end] if l.strip()]
        if len(body) > MAX_LINES:
            overlong.append((lines[start - 1][3:].strip(), len(body)))
    assert not overlong, (
        "an answer over %d non-blank lines belongs in its own page with a link "
        "from here, the way EXISTING_CODE_AND_HELPERS.md was split out: %s"
        % (MAX_LINES, ", ".join("%s (%d lines)" % pair for pair in overlong)))


@pytest.mark.parametrize("target", [
    "EXISTING_CODE_AND_HELPERS.md",
    "PROVIDER_KEY_SETUP.md",
    "design_2_performance.md",
    "mcp.md",
])
def test_every_page_the_faq_sends_people_to_exists(target):
    """A split-out answer is only an improvement if the link resolves."""
    assert target in _text(), "the FAQ no longer links to %s" % target
    assert os.path.isfile(os.path.join(ROOT, "docs", target))
