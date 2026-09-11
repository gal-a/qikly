"""
Prose that describes a picture, checked against the picture.

Found by a reader, not by a test: `docs/index.html` said the repair cycle was
"the dashed orange one" long after that arrow became purple, and `README.md`
called the same arrows red while `design_1_case_study.md` called them purple.
Three documents, two of them wrong, disagreeing with each other and with the
artwork.

Nothing could catch it. The colours live in CSS custom properties and mermaid
`classDef` lines; the descriptions live in sentences a hundred lines away. A
palette change updates one and silently invalidates the other.

So this pins the mapping in the only direction that matters: **the colour word
a document uses for a thing must be the colour that thing actually is.**
"""
import io
import re

import pytest

# role -> (the token or hex it is drawn with, the word prose must use)
ROLES = {
    "coding agent / repair loop": ("--code", "purple"),
    "test side / staged expansion": ("--accent", "teal"),
}

# Words that would be wrong for any of the above, so a stale description is
# caught even if somebody invents a new sentence for it.
WRONG_WORDS = ("orange", "red", "blue", "amber", "violet", "pink", "grey", "gray")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def test_the_landing_page_names_the_colour_its_diagram_actually_uses():
    """
    The two dashed arrows in the inline SVG, and the caption describing them.
    """
    page = _read("docs/index.html")

    # The repair cycle arrow is drawn with --code, the expansion one with
    # --accent. If that stops being true, the caption below is describing
    # something else and this test should be the thing that says so.
    assert 'stroke="var(--code)" stroke-width="1.4" stroke-dasharray' in page, (
        "the repair-cycle arrow is no longer drawn with --code")
    assert 'stroke="var(--accent)" stroke-width="1.4" stroke-dasharray' in page, (
        "the staged-expansion arrow is no longer drawn with --accent")

    caption = page[page.index("The main flow consists of two loops"):][:600]
    assert "dashed purple one is the repair cycle" in caption, caption[:200]
    assert "dashed teal one is the" in caption, caption[:200]


def test_code_is_purple_and_accent_is_teal_on_the_landing_page():
    """The words above are only right because the tokens hold these values."""
    page = _read("docs/index.html")
    assert "--code: #7e22ce;" in page, "light-mode --code is no longer purple"
    assert "--code: #a855f7;" in page, "dark-mode --code is no longer purple"
    assert "--accent: #0e6a70;" in page, "light-mode --accent is no longer teal"
    assert "--accent: #57b8bd;" in page, "dark-mode --accent is no longer teal"


@pytest.mark.parametrize("path", ["README.md", "docs/design_1_case_study.md"])
def test_the_diagram_prose_matches_the_mermaid_link_colours(path):
    """
    The diagram is duplicated in both files and a separate test keeps the
    copies identical. This checks the sentences beside them, which that test
    does not look at.
    """
    text = _read(path)
    assert "linkStyle 11,12 stroke:#7e22ce" in text, (
        "the repair-loop links are no longer purple")
    assert "Purple is what the coding agent can see" in text
    assert "Teal is what the standard is" in text
    assert "purple arrows are the repair loop" in text, (
        "the sentence naming the repair-loop colour is missing or wrong")


@pytest.mark.parametrize("path", ["README.md", "docs/index.html",
                                  "docs/design_1_case_study.md"])
def test_no_document_describes_an_arrow_in_a_colour_it_is_not(path):
    """
    A blunt sweep, so a newly written sentence is covered without anyone
    remembering to extend the specific assertions above.
    """
    text = _read(path)
    offenders = []
    for word in WRONG_WORDS:
        for m in re.finditer(r"\b%s\b" % word, text, re.I):
            window = text[max(0, m.start() - 60):m.end() + 60].lower()
            if any(k in window for k in ("arrow", "dashed", "loop is",
                                         "one is the repair")):
                offenders.append((word, text[max(0, m.start() - 40):m.end() + 40]))
    assert not offenders, (
        "an arrow is described in a colour it is not: %s" % offenders[:3])
