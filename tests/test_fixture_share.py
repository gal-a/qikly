"""
Counting how much of your fixture data a machine wrote.

The count exists so drift is visible in aggregate: no single proposed row ever
looks wrong, and after enough rounds the data stops resembling what you
actually process.

The first version recorded it as a comment appended to the row itself. That
was broken in a way worth keeping a test for. A CSV line ending
`2026-01-10  # proposed` parses with a date field of `"2026-01-10  # proposed"`,
so the convention meant to keep the count honest would have silently corrupted
the fixture it was counting. JSON and JSONL inputs have nowhere to put a
trailing comment at all.

It is a sidecar file now, one accepted row per line, next to the data.
"""
import csv
import io

from qikly.orchestrator.tuning import propose_fixtures as pf


def test_an_inline_marker_would_have_corrupted_the_row():
    """Why the sidecar exists, demonstrated rather than asserted."""
    sample = "transaction_id,amount,date\nTXN-1012,0.00,2026-01-10  # proposed\n"
    row = next(iter(csv.DictReader(io.StringIO(sample))))
    assert row["date"] != "2026-01-10", (
        "if this ever passes, an inline marker is safe after all"
    )
    assert "# proposed" in row["date"]


def test_a_row_that_merely_says_proposed_does_not_count(tmp_path, monkeypatch):
    """
    Behavioural rather than a source check. The count comes from the sidecar,
    so a row containing the old marker text is just an oddly written row and
    must not be counted, however much it looks like a claim.
    """
    monkeypatch.setattr(
        pf, "task_config_path",
        lambda t: _task(tmp_path, ["1,5", "2,6  # proposed"], accepted=[]))
    machine, total = pf._machine_share("T")
    assert (machine, total) == (0, 2)


def test_the_sidecar_is_hidden_so_it_is_not_mistaken_for_data():
    assert pf.ACCEPTED_FILE.startswith(".")


def _task(tmp_path, rows, accepted=None):
    fixture = tmp_path / "input_01.csv"
    fixture.write_text("id,amount" + chr(10) + chr(10).join(rows) + chr(10),
                       encoding="utf-8")
    if accepted is not None:
        (tmp_path / pf.ACCEPTED_FILE).write_text(
            chr(10).join(accepted) + chr(10), encoding="utf-8")
    config = tmp_path / "T.yaml"
    config.write_text('inputs:' + chr(10) + '  - "' + fixture.as_posix() + '"' + chr(10),
                      encoding="utf-8")
    return str(config)


def test_the_share_counts_only_rows_that_were_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "task_config_path",
                        lambda t: _task(tmp_path, ["1,5", "2,6"], accepted=["2,6"]))
    assert pf._machine_share("T") == (1, 2)


def test_data_nobody_proposed_reads_as_entirely_yours(tmp_path, monkeypatch):
    """
    The share must not rise on its own. It moves only when a person accepts
    something, which is what makes it a measure of drift rather than activity.
    """
    monkeypatch.setattr(pf, "task_config_path",
                        lambda t: _task(tmp_path, ["1,5", "2,6"]))
    assert pf._machine_share("T") == (0, 2)


def test_the_share_appears_in_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "task_config_path",
                        lambda t: _task(tmp_path, ["1,5", "2,6"], accepted=["2,6"]))
    assert "1 of 2 rows" in pf.render("T", ["c"], [{"criterion": 1, "covered": True}])


def test_a_task_whose_files_cannot_be_read_still_renders(tmp_path, monkeypatch):
    """
    A statistic that cannot be computed is a missing line, not a failed run.
    The proposals are the point of the report.
    """
    monkeypatch.setattr(pf, "task_config_path", lambda t: str(tmp_path / "gone.yaml"))
    assert pf._machine_share("T") == (0, 0)
    assert "Nothing to propose" in pf.render(
        "T", ["c"], [{"criterion": 1, "covered": True}])
