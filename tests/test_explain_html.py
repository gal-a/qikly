"""
`qikly --explain TASK --html`: the withholding as a page someone can share.

The terminal output of --explain is the most persuasive thing the tool prints
and the hardest to pass on. The page has to say exactly what the terminal says:
the same lines marked as removed, no criterion in the coding agent's column,
and a failed verdict when something leaks. It also has to stand alone, since
the point is that it gets attached, hosted or screenshotted somewhere else.
"""
import re

from qikly import cli, explain


def _column(page, cls):
    start = page.index('<section class="col %s">' % cls)
    return page[start:page.index("</section>", start)]


def _marked(column):
    return [text for text in re.findall(r'<span class="ln cut">([^<]*)</span>', column)
            if text.strip()]


def test_the_page_marks_exactly_the_lines_the_terminal_counts():
    facts = explain.build("MERGE_SALES")
    counted = int(re.search(r"(\d+) line(?:s|\(s\))? removed", explain.render(facts)).group(1))
    page = explain.render_html(facts)
    assert len(_marked(_column(page, "tests"))) == counted
    assert "%d lines removed" % counted in page


def test_the_cut_lines_lead_the_page_and_leave_a_marked_hole():
    """
    In a task file the criteria sit at the bottom, so a screenshot of the top
    of the page showed two identical columns. The removed lines come first,
    and the coding agent's column says where they used to be.
    """
    facts = explain.build("MERGE_SALES")
    page = explain.render_html(facts)
    counted = len(_marked(_column(page, "tests")))
    assert page.index('class="cutbox"') < page.index('class="cols"')
    box = page[page.index('class="cutbox"'):page.index('class="cols"')]
    assert len(_marked(box)) == counted
    assert "%d lines removed here" % counted in _column(page, "code")


def test_no_criterion_appears_in_the_coding_agent_column():
    import html

    facts = explain.build("CALC_TAX")
    page = explain.render_html(facts)
    code = _column(page, "code")
    assert "acceptance_criteria:" in _column(page, "tests")
    assert "acceptance_criteria:" not in code
    for criterion in facts["criteria"]:
        assert html.escape(criterion) not in code, criterion[:60]
    assert "No criterion text reaches the coding agent" in page


def test_a_leak_shows_as_a_failed_verdict():
    facts = explain.build("CALC_TAX")
    facts = dict(facts, withheld_ok=False, leaked=[facts["criteria"][0]])
    assert "FAILED" in explain.render_html(facts)


def test_task_text_is_escaped():
    text = 'acceptance_criteria:\n  - "<script>alert(1)</script> & more"\n'
    facts = {"task_id": "T", "task_path": "x", "criteria_count": 1,
             "criteria": ["<script>alert(1)</script> & more"],
             "test_generation_chars": len(text), "coding_agent_chars": 0,
             "test_generation_sees": text, "coding_agent_sees": "",
             "leaked": [], "withheld_ok": True}
    page = explain.render_html(facts)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_the_page_loads_nothing_from_anywhere():
    page = explain.render_html(explain.build("MERGE_SALES"))
    for needle in ("<script", "<link", "<img", "src=", "@import", "url("):
        assert needle not in page, needle
    assert re.findall(r'href="([^"]+)"', page) == ["https://test.qikly.com/?ref=explain"]


def test_the_command_writes_the_page_where_it_was_typed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_explain("MERGE_SALES", False, html_path="") == 0
    written = tmp_path / "qikly_explain_MERGE_SALES.html"
    assert written.is_file()
    assert "What each agent sees: MERGE_SALES" in written.read_text(encoding="utf-8")

    assert cli._do_explain("MERGE_SALES", False, html_path="share.html") == 0
    assert (tmp_path / "share.html").is_file()
