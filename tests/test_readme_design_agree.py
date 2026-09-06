"""
README.md and the DESIGN parts agree where they overlap.

They show the same diagram, byte for byte, and describe a run with the
same five steps.

They used to show two different ones, drawn at different times, disagreeing
about whether the strip was a node and about which parts were coloured. A
reader who saw both had to work out whether the difference meant anything. It
did not.

Since there is no include mechanism in GitHub markdown, the copies are
maintained by hand, and hand-maintained copies drift. This is the check that
they have not.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The diagram is in part 1, which makes the case. The five run steps are in
# part 3, which is the architecture. Each pairs with README separately.
DIAGRAM_DOCS = ("README.md", os.path.join("docs", "DESIGN_1_CASE_STUDY.md"))
STAGES_DOCS = ("README.md", os.path.join("docs", "DESIGN_3_MECHANISM.md"))
DOCS = DIAGRAM_DOCS


def _diagram(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        text = handle.read()
    blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.S)
    assert blocks, f"{name} has no mermaid diagram"
    return blocks[0]


@pytest.mark.parametrize("name", DOCS)
def test_the_document_has_the_diagram(name):
    assert _diagram(name).strip()


def test_both_documents_show_the_same_diagram():
    readme, design = (_diagram(name) for name in DOCS)
    assert readme == design, (
        "the diagram in README.md and docs/DESIGN_1_CASE_STUDY.md have "
        "drifted apart; "
        "edit one and copy it to the other")


def test_the_repair_loop_is_drawn_and_highlighted():
    """
    The loop back into the coding agent is the whole mechanism, and it was
    once present in the graph but invisible as a loop: an unlabelled edge
    among thirteen others. It is labelled and coloured now, and `linkStyle`
    indices are positional, so an edge inserted above them silently recolours
    the wrong arrows.
    """
    diagram = _diagram("README.md")
    edges = [line.strip() for line in diagram.split("\n")
             if re.search(r"(-->|\.->|\.-x)", line)
             and not line.strip().startswith(("linkStyle", "class"))]

    back = next((i for i, e in enumerate(edges) if e.startswith("FAIL")), None)
    assert back is not None, "no edge runs from the failure back to the agent"
    assert "repair loop" in edges[back], "the back edge is unlabelled"

    styled = re.findall(r"linkStyle ([\d,]+)", diagram)
    assert styled, "the repair loop is not highlighted"
    highlighted = {int(n) for group in styled for n in group.split(",")}
    assert back in highlighted, (
        f"linkStyle highlights {sorted(highlighted)} but the repair loop is "
        f"edge {back}; an edge was probably added above it")


def test_the_passing_path_is_drawn_in_its_own_colour():
    """
    Pass and fail leave the same decision node, so they are only telling the
    reader different things if they look different.
    """
    diagram = _diagram("README.md")
    assert re.search(r"linkStyle \d+ stroke:#15803d", diagram), (
        "the pass edge has lost its green")


def _stage_list(name):
    """The five numbered steps a run works through, as one block of text."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("A run works through three stages")
    start = text.index("1. **Integration and system tests", start)
    end = text.index("silently break something that already passed.", start)
    return text[start:end]


def test_both_documents_describe_the_run_the_same_way():
    """
    The two copies had drifted into describing different things: one said the
    specification was split in two, the other correctly said three parts, and
    the five steps were worded differently enough to read as different
    processes. A reader consulting both should not have to reconcile them.
    """
    readme, design = (_stage_list(name) for name in STAGES_DOCS)
    assert readme.split() == design.split(), (
        "the stage list in README.md and docs/DESIGN_3_MECHANISM.md have "
        "drifted apart")


@pytest.mark.parametrize("name", sorted(set(DIAGRAM_DOCS + STAGES_DOCS)))
def test_neither_document_says_the_specification_is_split_in_two(name):
    """
    A task file has three parts. Saying "split in two" describes the cut,
    which runs between the criteria and the rest, but it reads as a claim
    about the file and contradicts every other list in both documents.
    """
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        text = handle.read()
    assert "split in two" not in text


@pytest.mark.parametrize("name", DOCS)
def test_the_diagram_shows_what_a_stalled_run_still_gives_you(name):
    """
    The diagram used to draw only the converged outcome, which read as though
    a run that does not converge produces nothing. It produces the same audit
    trail, and that is when the trail is most useful. The stall terminal says
    so, so it should not quietly disappear in a later edit.
    """
    diagram = _diagram(name)
    assert "STALL" in diagram, "the diagram no longer shows a non-converged run"
    assert "audit trail" in diagram, (
        "the stall outcome no longer says what you get from it")
