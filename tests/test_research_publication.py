"""
Every research harness is marked public or private, and the split holds.

A published figure needs its harness visible, or it is asking to be taken on
trust, which is the one thing this project argues against. Work in progress is
the opposite case: an unfinished measurement read by a stranger is a claim
nobody made.

Both failure modes are silent. A new harness added tomorrow would become
public simply by existing, and a file quietly reclassified would change what
ships with no diff anyone reads. So the classification lives in
`research/README.md`, where a person will see it, and this file checks that it
covers reality.

The split itself is applied when the public branch is built, since the
harnesses import each other and moving the private ones to another repository
would break that. See MAINTAIN.md in the private repository.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(ROOT, "research")
README = os.path.join(RESEARCH, "README.md")

# Public because each backs a figure that is already published: the 38%
# detection rate, the 950 cross-run verdicts, and the intervals under both.
EXPECTED_PUBLIC = {"mutation_test.py", "backanalysis.py", "stats_helpers.py",
                   "stage_breakdown.py"}


def _classified():
    """{filename: "public" | "private"} as research/README.md declares it."""
    with open(README, encoding="utf-8") as handle:
        text = handle.read()
    found = {}
    for kind, name in re.findall(r"\*\*(public|private)\*\*\s+`([^`]+)`", text):
        found[name] = kind
    return found


def _harnesses():
    return {n for n in os.listdir(RESEARCH)
            if n.endswith((".py", ".ps1")) and not n.startswith("__")}


def test_every_harness_is_classified():
    """
    The one that matters. A harness added tomorrow and never mentioned here
    would ship publicly by default, which is the wrong default for research.
    """
    missing = _harnesses() - set(_classified())
    assert not missing, (
        "these are neither public nor private in research/README.md, so nobody "
        "has decided whether they should ship: " + ", ".join(sorted(missing))
    )


def test_no_classification_names_a_file_that_is_gone():
    """
    A stale entry would leave the split looking complete when it is not.

    Absence means two different things depending on which tree this runs in.
    On the private tree every classified harness is present, so a missing one
    is a stale row. The public branch is built by excluding the private
    harnesses, so there they are absent all at once, which is the split
    working rather than rot.

    A **public** classification naming a missing file is an error in either
    tree, and asserting that separately is what found `stage_breakdown.py`
    missing from the public branch build: the figure it derives is quoted in
    two documents and its harness would not have shipped.
    """
    classified = _classified()
    present = _harnesses()

    missing_public = {n for n, kind in classified.items()
                      if kind == "public" and n not in present}
    assert not missing_public, (
        "classified public but absent, so a published figure has no visible "
        "harness: " + ", ".join(sorted(missing_public)))

    private = {n for n, kind in classified.items() if kind == "private"}
    missing_private = private - present
    assert not missing_private or missing_private == private, (
        "classified private but absent: " + ", ".join(sorted(missing_private)))


@pytest.mark.parametrize("name", sorted(EXPECTED_PUBLIC))
def test_the_harnesses_behind_published_figures_stay_public(name):
    """
    Making one of these private would leave a published number with no visible
    way to reproduce it, which is exactly the position the article criticises
    other tools for.
    """
    assert _classified().get(name) == "public", (
        f"{name} produced a published figure and must remain public"
    )


def test_the_refinement_harnesses_are_private():
    """
    The open question. Held back until its results are settled enough to
    publish deliberately rather than by default.
    """
    classified = _classified()
    for name in ("escaped_faults.py", "strictness.py", "shared_substrate.py",
                 "false_rejection.py"):
        if name in _harnesses():
            assert classified.get(name) == "private", f"{name} should not ship yet"


def test_a_public_harness_never_imports_a_private_one():
    """
    The split has to survive the build. A public file importing a private one
    would be broken the moment the private one is left out, and the breakage
    would only appear for people who cloned the public repository.
    """
    classified = _classified()
    private = {n[:-3] for n, kind in classified.items()
               if kind == "private" and n.endswith(".py")}
    offenders = []
    for name, kind in classified.items():
        if kind != "public" or not name.endswith(".py"):
            continue
        with open(os.path.join(RESEARCH, name), encoding="utf-8") as handle:
            source = handle.read()
        for module in private:
            if re.search(r"^\s*(import|from)\s+" + module + r"\b", source, re.M):
                offenders.append(f"{name} imports {module}")
    assert not offenders, "; ".join(offenders)


def test_the_readme_explains_the_split_rather_than_just_listing_it():
    """
    A bare list invites someone to move a file without knowing the reason.
    """
    with open(README, encoding="utf-8") as handle:
        text = handle.read().lower()
    assert "published, or not" in text
    assert "taken on trust" in text
