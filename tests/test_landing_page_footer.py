"""
The landing page footer's outbound links, pinned.

Every one of them points at a site this repository does not control, so
nothing here would notice if one moved or was renamed. Each is pinned below
and in docs/index.html, and the two have to change together.

The newsletter link is the one worth watching: it is the only channel on the
page that the project owns, and it is the conversion for a visitor who liked
what they read and is not going to install anything today.

Offline by default. Before a release, check every footer link still answers:

    QIKLY_CHECK_LINKS=1 python -m pytest -q tests/test_landing_page_footer.py
"""
import os
import re
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_URL = "https://leanpub.com/applied-statistics-for-data-science"
SUBSTACK_URL = "https://qikly.substack.com/subscribe"
X_URL = "https://x.com/GA4198498563411"
LINKEDIN_URL = "https://www.linkedin.com/in/galarav/"


def _footer():
    with open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    return page[page.index("<footer>"):page.index("</footer>")]


def test_the_footer_carries_every_channel_we_want_counted():
    """
    Each link, with the GoatCounter name that makes its clicks countable.

    A link without `data-goatcounter-click` is a link nobody can tell apart
    from the others in the dashboard, which is the whole reason for adding
    these: to find out which of three channels a visitor actually uses.
    """
    footer = _footer()
    for url, counter in ((SUBSTACK_URL, "footer-substack"),
                         (X_URL, "footer-x"),
                         (LINKEDIN_URL, "footer-linkedin"),
                         (BOOKS_URL, "footer-books")):
        pattern = r'<a href="%s"[^>]*data-goatcounter-click="%s"' % (
            re.escape(url), re.escape(counter))
        assert re.search(pattern, footer), (
            "%s is missing from the footer, or is not counted as %s"
            % (url, counter))


def test_the_footer_links_the_books():
    # Other attributes may sit beside href, such as the click counter's name.
    pattern = r'Also by the author: <a href="%s"[^>]*>Applied Statistics for Data Science</a>'
    assert re.search(pattern % re.escape(BOOKS_URL), _footer())


@pytest.mark.skipif(not os.environ.get("QIKLY_CHECK_LINKS"),
                    reason="network check, set QIKLY_CHECK_LINKS=1 to run")
@pytest.mark.parametrize("url", re.findall(r'href="(https?://[^"]+)"', _footer()))
def test_every_footer_link_still_answers(url, monkeypatch):
    # conftest blocks the network for every test; this one exists to use it.
    monkeypatch.undo()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200, url
