"""
The landing page footer links to the author's books.

That link points at www.qikly.com, a separate site this repository does not
control, so nothing here would notice if it moved. If it does, change
BOOKS_URL below and the footer in docs/index.html together.

Offline by default. Before a release, check every footer link still answers:

    QIKLY_CHECK_LINKS=1 python -m pytest -q tests/test_landing_page_footer.py
"""
import os
import re
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_URL = "https://www.qikly.com/"


def _footer():
    with open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    return page[page.index("<footer>"):page.index("</footer>")]


def test_the_footer_links_the_books():
    footer = _footer()
    assert 'Also by the author: <a href="%s">Applied Statistics for Data Science</a>' % BOOKS_URL in footer


@pytest.mark.skipif(not os.environ.get("QIKLY_CHECK_LINKS"),
                    reason="network check, set QIKLY_CHECK_LINKS=1 to run")
@pytest.mark.parametrize("url", re.findall(r'href="(https?://[^"]+)"', _footer()))
def test_every_footer_link_still_answers(url, monkeypatch):
    # conftest blocks the network for every test; this one exists to use it.
    monkeypatch.undo()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200, url
