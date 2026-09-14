"""
README.md and the DESIGN parts agree where they overlap.

They show the same diagram and describe a run with the same five steps.

They used to show two different diagrams, drawn at different times, disagreeing
about whether the strip was a node and about which parts were coloured. A
reader who saw both had to work out whether the difference meant anything. It
did not.

The diagram's only source is the mermaid block in design_1. README.md shows an
image rendered from it, because PyPI prints a mermaid block as forty lines of
source. The image carries a fingerprint of the block it was drawn from, so an
edit to the diagram that is not re-rendered fails here rather than leaving the
README quietly showing the old one.

The stage lists have no include mechanism either, so those copies are
maintained by hand, and this is the check that they have not drifted.
"""
import hashlib
import os
import re
import struct

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The diagram is in part 1, which makes the case. The five run steps are in
# part 3, which is the architecture. Each pairs with README separately.
DIAGRAM_DOC = os.path.join("docs", "design_1_case_study.md")
STAGES_DOCS = ("README.md", os.path.join("docs", "design_3_mechanism.md"))
IMAGE = os.path.join("docs", "images", "qikly_flow.png")
IMAGE_URL = "https://raw.githubusercontent.com/gal-a/qikly/main/docs/images/qikly_flow.png"
FINGERPRINT_KEY = "qikly-diagram-sha256"


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _diagram(name=DIAGRAM_DOC):
    blocks = re.findall(r"```mermaid\n(.*?)\n```", _read(name), re.S)
    assert blocks, f"{name} has no mermaid diagram"
    return blocks[0]


def _png_text_chunks(path):
    with open(path, "rb") as handle:
        data = handle.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    found, pos = {}, 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"tEXt":
            key, _, value = data[pos + 8:pos + 8 + length].partition(b"\0")
            found[key.decode("latin-1")] = value.decode("latin-1")
        pos += 12 + length
    return found


def test_the_design_has_the_diagram():
    assert _diagram().strip()


def test_the_readme_shows_the_diagram_as_an_image():
    readme = _read("README.md")
    assert "```mermaid" not in readme, (
        "README.md has a mermaid block again; PyPI prints it as source, so "
        "show the rendered image instead")
    assert IMAGE_URL in readme, "README.md no longer shows the flow diagram"


def test_the_image_was_rendered_from_the_current_diagram():
    expected = hashlib.sha256(_diagram().encode("utf-8")).hexdigest()
    found = _png_text_chunks(os.path.join(ROOT, IMAGE)).get(FINGERPRINT_KEY)
    assert found == expected, (
        "docs/images/qikly_flow.png was drawn from a different version of the "
        "diagram in docs/design_1_case_study.md; run "
        "`python tools/render_flow_diagram.py` and commit the image")


def test_the_repair_loop_is_drawn_and_highlighted():
    """
    The loop back into the coding agent is the whole mechanism, and it was
    once present in the graph but invisible as a loop: an unlabelled edge
    among thirteen others. It is labelled and coloured now, and `linkStyle`
    indices are positional, so an edge inserted above them silently recolours
    the wrong arrows.
    """
    diagram = _diagram()
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
    assert re.search(r"linkStyle \d+ stroke:#15803d", _diagram()), (
        "the pass edge has lost its green")


def _stage_list(name):
    """The five numbered steps a run works through, as one block of text."""
    text = _read(name)
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
        "the stage list in README.md and docs/design_3_mechanism.md have "
        "drifted apart")


@pytest.mark.parametrize("name", sorted({DIAGRAM_DOC} | set(STAGES_DOCS)))
def test_neither_document_says_the_specification_is_split_in_two(name):
    """
    A task file has three parts. Saying "split in two" describes the cut,
    which runs between the criteria and the rest, but it reads as a claim
    about the file and contradicts every other list in both documents.
    """
    assert "split in two" not in _read(name)


def test_the_diagram_shows_what_a_stalled_run_still_gives_you():
    """
    The diagram used to draw only the converged outcome, which read as though
    a run that does not converge produces nothing. It produces the same audit
    trail, and that is when the trail is most useful. The stall terminal says
    so, so it should not quietly disappear in a later edit.
    """
    diagram = _diagram()
    assert "STALL" in diagram, "the diagram no longer shows a non-converged run"
    assert "audit trail" in diagram, (
        "the stall outcome no longer says what you get from it")
