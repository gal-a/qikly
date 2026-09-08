"""
Static checks over the package's own source text.

These exist because of a specific class of incident rather than a
hypothetical. A blanket find and replace across the tree during the rename
turned every literal em dash into ", ". That silently rewrote the missing
value placeholder in three report modules into a bare comma and turned
sentences into "Every run converged ,  nothing to attribute." Nothing raised,
nothing was logged, every test passed, and the reports simply rendered wrong
until someone happened to read one.

A rendered-output test catches that only where a renderer is easy to invoke.
Scanning the source catches it everywhere, costs milliseconds, and needs no
fixtures. The trade is that these tests are about text and will occasionally
need a deliberate exception, which is why each carries its own allowance list
rather than a blanket skip.
"""
import io
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG = os.path.join(_ROOT, "src", "qikly")

# Assembled from pieces rather than written out, so this file does not
# itself match the tree wide grep in .github/workflows/ci.yml. The
# alternative is another entry in that step's exclude list, which loosens
# the guard for every future file that happens to share the name.
OLD_NAMES = ("v" + "_and_v", "v" + "-and-v",
             "test" + "_qikly", "test" + "-qikly")


def _sources():
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(root, name)
                yield os.path.relpath(path, _ROOT).replace("\\", "/"), \
                    io.open(path, encoding="utf-8").read()


# CHANGELOG.md quotes the corrupted sentence verbatim while describing the fix,
# so it is the one file that has to contain the artefact.
_PROSE_SKIP = {"CHANGELOG.md"}


def _prose():
    """Markdown a reader actually meets: the README and the design docs."""
    candidates = [os.path.join(_ROOT, "README.md"),
                  os.path.join(_ROOT, "RELEASE_CHECKLIST.md")]
    for folder in ("docs", "research"):
        full = os.path.join(_ROOT, folder)
        if os.path.isdir(full):
            candidates += [os.path.join(full, n) for n in sorted(os.listdir(full))
                           if n.endswith(".md")]
    for path in candidates:
        if not os.path.isfile(path) or os.path.basename(path) in _PROSE_SKIP:
            continue
        yield os.path.relpath(path, _ROOT).replace("\\", "/"), \
            io.open(path, encoding="utf-8").read()


@pytest.mark.parametrize("path,text", list(_sources()),
                         ids=[p for p, _ in _sources()])
def test_no_comma_separator_artefacts(path, text):
    """
    A comma followed by two or more spaces. No correct sentence produces one,
    and it is exactly what the em dash replacement left behind.
    """
    offenders = [(i, line) for i, line in enumerate(text.splitlines(), 1)
                 if ",  " in line]
    assert not offenders, "\n".join(f"{path}:{i}: {line.strip()}"
                                    for i, line in offenders)


@pytest.mark.parametrize("path,text", list(_sources()),
                         ids=[p for p, _ in _sources()])
def test_no_em_dashes_or_non_breaking_hyphens(path, text):
    """
    Both characters are house style violations, and the non breaking hyphen in
    particular is invisible in a diff while breaking terminal alignment.
    """
    banned = {"—": "em dash", "–": "en dash", "‑": "non breaking hyphen"}
    offenders = []
    for i, line in enumerate(text.splitlines(), 1):
        for char, name in banned.items():
            if char in line:
                offenders.append(f"{path}:{i}: {name}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_no_stale_project_name_in_the_package():
    """
    The CI guard greps the tree and excludes three files that name the old
    project on purpose. This checks the package itself, where there is no
    legitimate reason for the old name to survive, including inside strings
    the tree wide grep would have to allow through.
    """
    offenders = []
    for path, text in _sources():
        for i, line in enumerate(text.splitlines(), 1):
            if any(name in line for name in OLD_NAMES):
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_user_visible_titles_use_the_product_name():
    """
    "V&V" as a description of verification and validation is correct English
    and stays. "V&V" as the name of this tool in a window title or a report
    header is the old brand, and HTML escaping (V&amp;V) hides it from the
    rename grep, which is how it survived once already.
    """
    offenders = []
    for path, text in _sources():
        for i, line in enumerate(text.splitlines(), 1):
            if "V&amp;V" in line:
                offenders.append(f"{path}:{i}: {line.strip()}")
            if "title=\"V&V" in line or "<title>V&V" in line:
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("path,text", list(_prose()),
                         ids=[p for p, _ in _prose()])
def test_documentation_has_no_comma_separator_artefacts(path, text):
    """
    The same replacement hit the documentation, where a reader meets it
    directly. The README's own limitations section said "what a real
    implementation actually does ,  it's good at", which is the first place a
    prospective user looks.
    """
    offenders = [(i, line) for i, line in enumerate(text.splitlines(), 1)
                 if ",  " in line]
    assert not offenders, "\n".join(f"{path}:{i}: {line.strip()}"
                                    for i, line in offenders)


@pytest.mark.parametrize("path,text", list(_prose()),
                         ids=[p for p, _ in _prose()])
def test_documentation_has_no_em_dashes_or_non_breaking_hyphens(path, text):
    banned = {"—": "em dash", "‑": "non breaking hyphen"}
    offenders = []
    for i, line in enumerate(text.splitlines(), 1):
        for char, name in banned.items():
            if char in line:
                offenders.append(f"{path}:{i}: {name}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


# Assembled from pieces for the same reason as OLD_NAMES: this file must not
# be the thing that trips its own search.
_FILING_WORDS = ("prov" + "isional", "USP" + "TO", "patent " + "pending",
                 "37 " + "CFR", "patent " + "application")


@pytest.mark.parametrize("path,text", list(_sources()),
                         ids=[p for p, _ in _sources()])
def test_no_filing_references_in_the_package(path, text):
    """
    Nothing about a filing belongs in the public repository. It lives in the
    private one, deliberately, and a stray line here cannot be taken back once
    the repository is public and cloned.

    The Apache licence's patent-grant clauses are ordinary licence boilerplate
    and are not scanned: LICENSE is not part of the package sources.
    """
    lowered = text.lower()
    found = [w for w in _FILING_WORDS if w.lower() in lowered]
    assert not found, f"{path} mentions {found}"


@pytest.mark.parametrize("path,text", list(_prose()),
                         ids=[p for p, _ in _prose()])
def test_no_filing_references_in_the_documentation(path, text):
    """The README and the article are where such a line would most easily slip in."""
    lowered = text.lower()
    found = [w for w in _FILING_WORDS if w.lower() in lowered]
    assert not found, f"{path} mentions {found}"
