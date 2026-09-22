"""
The `--run` flag's wiring, which had no test at all before 2026-09-22.

`--start` was renamed `--run` to match the MCP tool it shares its machinery
with, `qikly_run`, keeping the old spelling as an alias. An audit pointed out
that nothing in the suite exercised the argparse wiring in either direction:
not the alias, not the `dest`, and not the neighbour it now sits beside.

That neighbour is the reason this file exists. `--runs`, plural, is a
`store_true` that lists past runs and starts nothing. `--run TASK` starts one,
which costs money. Two flags one letter apart, doing very different things, is
worth pinning rather than remembering.
"""
import pytest

from qikly import cli


def _parse(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["qikly"] + argv)
    return cli._parse_args()


def test_run_and_start_are_the_same_argument(monkeypatch):
    """The rename must not strand anyone who scripted the old spelling."""
    assert _parse(["--run", "CALC_TAX"], monkeypatch).run == "CALC_TAX"
    assert _parse(["--start", "CALC_TAX"], monkeypatch).run == "CALC_TAX"


def test_runs_plural_is_a_different_flag_and_starts_nothing(monkeypatch):
    """
    The confusable pair, pinned. `--runs` lists; `--run` spends. If these ever
    collapse into one option, this fails.
    """
    listed = _parse(["--runs"], monkeypatch)
    assert listed.runs is True
    assert not listed.run, "--runs must not populate the flag that starts a run"

    started = _parse(["--run", "CALC_TAX"], monkeypatch)
    assert started.run == "CALC_TAX"
    assert started.runs is False, "--run must not trigger the listing"


def test_bare_run_is_an_error_rather_than_a_silent_listing(monkeypatch):
    """
    Before the rename, bare `--run` was an unambiguous abbreviation of
    `--runs` and silently listed runs. It now requires a task, so it fails
    loudly instead of doing something the user did not ask for. Loud is the
    point: the two meanings are not interchangeable.
    """
    with pytest.raises(SystemExit):
        _parse(["--run"], monkeypatch)


def test_the_ambiguous_abbreviation_is_refused(monkeypatch):
    """
    `--ru` could now mean either, so argparse refuses it. Better than picking
    one, given one of them spends money.
    """
    with pytest.raises(SystemExit):
        _parse(["--ru"], monkeypatch)
