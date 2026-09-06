"""
The aggregate reader must know the schema the run-summary writer emits.

This exists because of a specific failure. `run_summary.py` was bumped to
schema 4 to carry provenance, and `aggregate_report.py` kept accepting only 3.
A 400-run sweep was then skipped in full, and the aggregator quietly pooled
two-week-old runs instead and printed a convergence rate that looked entirely
reasonable. No exception, no warning on the console, no missing file: just a
plausible number computed from the wrong data.

That is the worst shape a bug can take in this project, because the whole point
of the tool is that a green result should mean something. So the coupling
between the writer and the reader is pinned here rather than left to whoever
remembers.
"""
import inspect
import json
import re

from qikly.orchestrator import run_summary
from qikly.orchestrator.reports import aggregate_report


def _writer_schema():
    """The literal the writer stamps into every summary it emits."""
    source = inspect.getsource(run_summary)
    match = re.search(r'"schema_version":\s*(\d+)', source)
    assert match, "run_summary.py no longer stamps a literal schema_version"
    return int(match.group(1))


def test_the_reader_accepts_what_the_writer_currently_writes():
    """
    The regression guard. If you bump the writer, this fails until the reader
    is told about the new version, which is the conversation that did not
    happen last time.
    """
    written = _writer_schema()
    assert written in aggregate_report.SUPPORTED_SCHEMAS, (
        f"run_summary.py writes schema_version {written}, which "
        f"aggregate_report.py does not accept "
        f"({sorted(aggregate_report.SUPPORTED_SCHEMAS)}). Every run would be "
        f"silently skipped and the aggregate would pool older runs instead."
    )


def test_a_summary_of_an_unknown_schema_is_counted_as_skipped(tmp_path, monkeypatch):
    """
    Skipping is correct behaviour: pooling incomparable fields would be worse.
    What matters is that it is counted, so it can be said out loud.
    """
    monkeypatch.setattr(aggregate_report, "RUN_SUMMARY_DIR", str(tmp_path))
    unknown = max(aggregate_report.SUPPORTED_SCHEMAS) + 99
    (tmp_path / "T_20260101_000000.json").write_text(
        json.dumps({"schema_version": unknown, "task_id": "T",
                    "run_timestamp": "20260101_000000"}), encoding="utf-8")

    payloads, skipped = aggregate_report.load_summaries()
    assert payloads == []
    assert skipped == 1


def test_the_console_warns_rather_than_only_the_html():
    """
    The skip note already existed, in the rendered HTML, which is a file nobody
    opens when the console has just printed a number. The warning has to reach
    the place the rate is read.
    """
    source = inspect.getsource(aggregate_report.main)
    assert "WARNING" in source
    assert "skipped" in source
    assert "do NOT include them" in source


def test_the_supported_set_is_a_set_not_a_single_version():
    """
    A single version means every bump silently invalidates the reader. A set
    makes accepting an additive change a one-line, deliberate act.
    """
    assert isinstance(aggregate_report.SUPPORTED_SCHEMAS, frozenset)
    assert len(aggregate_report.SUPPORTED_SCHEMAS) >= 2
