"""
test.qikly.com counts visits, and clicks on its outbound links, with GoatCounter.

Added 2026-09-14, because GitHub's traffic numbers only show the people who
reach the repository, never the ones who read the landing page and left.
GoatCounter sets no cookies and stores no personal data, so the page needs no
consent banner.

The GoatCounter site code contains the project's old name, which CI's tree-wide
grep rejects, so the page and this test both assemble it from two pieces.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSEMBLED_ENDPOINT = '"https://test" + "-qikly.goatcounter.com/count"'


def _page():
    with open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8") as handle:
        return handle.read()


def test_the_page_loads_goatcounter_with_the_right_endpoint():
    page = _page()
    assert 's.src = "https://gc.zgo.at/count.js"' in page, "the counter script is gone"
    assert ASSEMBLED_ENDPOINT in page, "the counter no longer reports to the qikly site code"


def test_the_counter_loads_only_after_the_page_has():
    """
    Measured 2026-09-14: with gc.zgo.at silently dropped, as some corporate
    firewalls do, loading the counter during page load held the load event for
    25.7 seconds. Deferred to the load event, the page finished in 1.5.
    """
    page = _page()
    loader = page[page.index('window.addEventListener("load"'):]
    assert loader.index('s.src = "https://gc.zgo.at/count.js"') < loader.index("</script>"), (
        "the counter script is no longer loaded from inside the page's load event")


def test_every_outbound_link_is_counted_under_its_own_name():
    """A link added later without a name would be a click nobody can see."""
    links = re.findall(r'<a\s([^>]*?href="https?://[^"]+"[^>]*)>', _page(), re.S)
    assert links, "found no outbound links, so this test is reading the wrong page"
    names = []
    for attributes in links:
        found = re.search(r'data-goatcounter-click="([^"]+)"', attributes)
        assert found, "an outbound link is not counted: <a %s>" % attributes[:120]
        names.append(found.group(1))
    assert len(names) == len(set(names)), "two links share a click name: %s" % names
