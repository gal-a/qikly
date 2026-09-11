"""
The code that produces published numbers, pinned by the properties that matter.

Every defect this project has found by chance lived here rather than in the
tool: a settings override that was not recorded, a report file that overwrote
its own evidence, a schema bump that made an aggregator skip a whole sweep. The
tool was correct each time. The apparatus that measures the tool was not.

These modules were then mutation tested against the existing suite, which is
how this file got its contents. Eight single-token edits to logic in
`aggregate_report`, `metrics_report`, `run_all` and `run_summary` left all 660
tests passing, and twelve more edits corrupted the generated HTML without
anything noticing. Each test below kills at least one of those survivors, so
this file is a record of measured gaps rather than a guess at what might break.

The register throughout is: assert the property a reader depends on, not the
implementation that currently provides it.
"""
import datetime
import json
import re

import pytest

from qikly.orchestrator import run_summary
from qikly.orchestrator.reports import aggregate_report, metrics_report


# ------------------------------------------------- provenance is present ----

def test_provenance_names_the_model_and_the_provider():
    """
    The single most important line in this file.

    Provenance exists *because* a stale `criteria_per_batch: 4` in a local
    settings file tripled every suite size and made convergence look like model
    drift. The block was added so a stored rate could always say which
    configuration produced it.

    Mutating `agents.get("default") or {}` to `and {}` makes provider and model
    both None, and the full suite passed. The fix for the first defect was
    itself unprotected against the same class of defect, which is the exact
    shape of the problem this file exists to close.
    """
    prov = run_summary._provenance()
    assert prov.get("model"), "a run summary with no model cannot be compared to another"
    assert prov.get("provider"), "provenance without a provider is not provenance"


def test_provenance_records_the_setting_that_once_tripled_the_bar():
    """`criteria_per_batch` is recorded because not recording it cost half a day."""
    prov = run_summary._provenance()
    assert "criteria_per_batch" in prov
    assert "max_retries_per_stage" in prov


def test_provenance_survives_a_broken_settings_file(monkeypatch):
    """
    A run summary is written at the end of a real run. It must never be the
    thing that fails one, so unreadable settings degrade to a thinner block
    rather than an exception.
    """
    def boom():
        raise OSError("settings unreadable")

    monkeypatch.setattr("qikly.orchestrator.orchestrator.load_settings", boom)
    prov = run_summary._provenance()
    assert "recorded_at" in prov


# ------------------------------------------------ output identity ----------

def test_the_label_decides_the_filename(tmp_path, monkeypatch):
    """
    `--label` is how a sweep names its own aggregate, and an earlier defect in
    this project was a report written to a fixed filename that every later run
    overwrote, destroying the evidence behind a published claim.

    `stamp = label or now()` survived becoming `label and now()`, which either
    ignores the label or produces `aggregate_None`. Nothing noticed.
    """
    monkeypatch.setattr(aggregate_report, "RUN_SUMMARY_DIR", str(tmp_path / "in"))
    monkeypatch.setattr(aggregate_report, "AGGREGATE_DIR", str(tmp_path / "out"))
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "T_20260101_000000.json").write_text(json.dumps({
        "schema_version": max(aggregate_report.SUPPORTED_SCHEMAS),
        "task_id": "T", "run_timestamp": "20260101_000000",
        "passed_overall": True, "stage_iterations": {"unit": 1},
    }), encoding="utf-8")

    html_path, json_path = aggregate_report.generate_aggregate_report(label="my_label")
    assert "my_label" in html_path and "my_label" in json_path
    assert "None" not in html_path


# ------------------------------------------------ the repetition warning ----

def test_a_single_repetition_is_called_out_as_not_a_measurement(capsys, monkeypatch):
    """
    At `--repeat 1` a sweep produces artifacts, not a rate, and the script says
    so before the spend. `if reps > 1` survived becoming `>=`, which silences
    that warning for exactly the case it was written for.
    """
    from qikly.orchestrator import run_all

    monkeypatch.setattr(run_all, "discover_task_ids", lambda: ["T"], raising=False)
    monkeypatch.setattr("qikly.orchestrator.orchestrator.discover_task_ids", lambda: ["T"])
    monkeypatch.setattr(run_all, "_run_stage", lambda *a, **k: 0)
    monkeypatch.setattr("sys.argv", ["run_all", "--tasks", "T", "--repeat", "1",
                                     "--skip-eval", "--skip-refine", "--yes"])
    run_all.main()
    out = capsys.readouterr().out
    assert "not a measurement" in out


def test_many_repetitions_are_not_called_out_that_way(capsys, monkeypatch):
    """The other side of the same boundary, so the assertion above is real."""
    from qikly.orchestrator import run_all

    monkeypatch.setattr("qikly.orchestrator.orchestrator.discover_task_ids", lambda: ["T"])
    monkeypatch.setattr(run_all, "_run_stage", lambda *a, **k: 0)
    monkeypatch.setattr("sys.argv", ["run_all", "--tasks", "T", "--repeat", "5",
                                     "--skip-eval", "--skip-refine", "--yes"])
    run_all.main()
    out = capsys.readouterr().out
    assert "not a measurement" not in out
    assert "own seed" in out, "independent draws are what make repetition worth paying for"


def test_seeds_only_vary_when_there_is_more_than_one_repetition(monkeypatch):
    """
    `if reps > 1 and base_seed is not None` survived becoming `>=`, which
    overrides the seed on a single run. A one-off run is meant to reproduce
    exactly what its seed says, and quietly shifting it makes a run that cannot
    be repeated from its own record.
    """
    from qikly.orchestrator import run_all

    seen = []
    monkeypatch.setattr("qikly.orchestrator.orchestrator.discover_task_ids", lambda: ["T"])
    monkeypatch.setattr(run_all, "_run_stage",
                        lambda label, cmd, env=None: seen.append(env) or 0)
    monkeypatch.setattr("sys.argv", ["run_all", "--tasks", "T", "--repeat", "1",
                                     "--seed", "7", "--skip-eval", "--skip-refine", "--yes"])
    run_all.main()
    assert seen, "no stage ran"
    assert all("AGENT_SEED" not in (env or {}) for env in seen), (
        "a single run had its seed overridden, so it cannot be reproduced "
        "from the seed it was asked for")


# ----------------------------------------------- rendered numbers ----------

def _summary(n, passed):
    """One run summary, in the shape run_summary.py actually writes."""
    return {
        "schema_version": max(aggregate_report.SUPPORTED_SCHEMAS),
        "provenance": {"model": "test-model", "provider": "test"},
        "task_id": "T", "task_name": "T", "run_timestamp": f"20260101_{n:06d}",
        "passed_overall": passed, "total_fix_attempts": 8, "regression_fails": 0,
        "apply_failed": 0, "ineffective_patches": 0,
        "stage_iterations": {"integration": 2, "system": 1, "unit": 3},
        "patch_outcomes": {"applied": 6, "apply_failed": 0,
                           "too_large": 0, "generation_failed": 0},
        "duration_seconds": 50,
        "stage_first_attempt_pass": {"integration": False, "system": True, "unit": False},
    }


def _agg(converged=6, total=10):
    """
    Built by calling the real `aggregate()` rather than by hand-shaping a dict.
    A fixture that guesses at the shape drifts away from the producer, which is
    the same class of defect this file exists to catch.
    """
    return aggregate_report.aggregate(
        [_summary(i, i < converged) for i in range(total)])


def test_an_interval_that_exists_is_rendered():
    """
    `if t["ci_low"] is not None` survived becoming `is None`, which drops the
    interval from every task that has one and prints "n/a" instead. A rate
    without its interval is the single most misleading thing this project can
    publish.

    The first version of this test asserted that the two percentages appeared
    anywhere in the page, and it survived the mutation: those two-digit strings
    also occur in the stylesheet and in the generated timestamp. A test that
    can pass for an unrelated reason is exactly the vacuous assertion this file
    was written to find, so it now matches the rendered cell.
    """
    agg = _agg()
    t = agg["tasks"]["T"]
    lo = aggregate_report._pct(t["ci_low"])
    hi = aggregate_report._pct(t["ci_high"])
    html = aggregate_report._task_table_html(agg)
    assert f"<td>{lo}-{hi}</td>" in html, "the interval cell is missing or malformed"
    assert "<td>n/a</td>" not in html, "an interval that exists was rendered as n/a"


def test_a_missing_interval_is_marked_absent_rather_than_invented():
    """The other side of the same branch, so the assertion above is real."""
    agg = _agg()
    task = agg["tasks"]["T"]
    task["ci_low"] = task["ci_high"] = task["convergence_rate"] = None
    html = aggregate_report._task_table_html(agg)
    assert "<td>n/a</td>" in html
    assert ">None<" not in html


def test_an_unexplained_censored_run_is_still_reported(tmp_path):
    """
    `unattributed_failures or []` survived becoming `and []`, which silently
    drops every censored run that left no failing test behind. Those are the
    runs whose cause is unknown, so dropping them makes the failure analysis
    look tidier than the data is.
    """
    agg = _agg()
    t = agg["tasks"]["T"]
    t["censored"] = 2
    t["unattributed_failures"] = ["20260101_000009"]
    t["failure_clusters"] = []
    html = aggregate_report._failure_clusters_html(agg)
    assert "1 of 2" in html, "the unexplained run is missing from the cluster table"
    assert "unexplained" in html


def test_a_skipped_summary_is_reported_in_the_html_too():
    """Loud in both places: the console for the reader, the report for the record."""
    assert "skipped" in aggregate_report.render_aggregate_html(_agg(), 3)


def test_outcome_percentages_are_taken_over_the_real_total():
    """
    `total = sum(outcomes.values()) or 1` survived becoming `and 1`, which
    makes every denominator 1 and every percentage a raw count. The `or 1`
    guards division by zero; the `and` inverts its whole meaning.
    """
    html = metrics_report._outcome_breakdown_html(
        {"applied": 3, "apply_failed": 1, "too_large": 0, "generation_failed": 0})
    pcts = [int(x) for x in re.findall(r"width:\s*([0-9]+(?:\.[0-9]+)?)%", html)]
    assert pcts, "no bar widths rendered"
    assert sum(pcts) <= 101, f"widths sum to {sum(pcts)}%, so the denominator is wrong"


def test_no_outcomes_at_all_does_not_divide_by_zero():
    metrics_report._outcome_breakdown_html(
        {"applied": 0, "apply_failed": 0, "too_large": 0, "generation_failed": 0})


# ----------------------------------------- the reports stay well formed ----

def _metrics_html():
    """The metrics report, rendered through its real entry point."""
    summary = _summary(0, True)
    stage_details = {
        "integration": {"iterations": 2, "first_attempt_pass": False,
                        "regression_checks": 0, "regression_failures": 0},
        "system": {"iterations": 1, "first_attempt_pass": True,
                   "regression_checks": 1, "regression_failures": 0},
        "unit": {"iterations": 3, "first_attempt_pass": False,
                 "regression_checks": 2, "regression_failures": 1},
    }
    return metrics_report.render_metrics_html(
        "T", "20260101_000000", summary, summary["patch_outcomes"],
        stage_details, datetime.timedelta(seconds=90), {"task_name": "T"})


REPORT_RENDERERS = [
    ("aggregate", lambda: aggregate_report.render_aggregate_html(_agg(), 0)),
    ("metrics", _metrics_html),
]


@pytest.mark.parametrize("name,render", REPORT_RENDERERS)
def test_the_generated_report_is_well_formed_html(name, render):
    """
    Twelve of the twenty surviving mutants were single characters inside HTML
    string literals: `<table>` becoming `<=table>`, and so on. Every one left
    all 660 tests passing while producing a report that no longer parses.

    This project has already been burned by exactly that, when a tree-wide
    character substitution silently broke all three report modules. Static text
    guards were added then; they check specific strings, so they cannot see a
    tag that has been mangled into something else.
    """
    import html.parser

    VOID = {"br", "img", "hr", "meta", "link", "input", "source", "col", "area"}

    class Checker(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in VOID:
                return
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.bad.append((tag, list(self.stack[-3:])))

    markup = render()
    checker = Checker()
    checker.feed(markup)
    assert not checker.bad, f"{name}: mismatched close tags {checker.bad}"
    assert not checker.stack, f"{name}: tags never closed {checker.stack}"


@pytest.mark.parametrize("name,render", REPORT_RENDERERS)
def test_the_report_still_has_the_structure_a_reader_looks_for(name, render):
    """
    Well formed is not the same as intact. A mangled opening tag can still
    parse into *something*, so the elements a reader actually scans for are
    named here.
    """
    markup = render()
    for tag in ("<table", "<thead", "<tbody", "<tr", "<td"):
        assert tag in markup, f"{name}: no {tag} in the rendered report"


# ------------------------------------------------------ boundary counts ----

def test_two_timestamps_are_enough_to_measure_a_duration():
    """
    `if len(timestamps) < 2` survived becoming `<=`, which discards the
    shortest measurable run. Off-by-one at a boundary is the fault class this
    project has documented as the hardest for a generated suite to catch, so
    its own boundaries are worth stating explicitly.
    """
    assert metrics_report.compute_duration(
        [{"ts": "2026-01-01T00:00:00"},
         {"ts": "2026-01-01T00:00:30"}]) is not None


def test_one_timestamp_is_not():
    assert metrics_report.compute_duration([{"ts": "2026-01-01T00:00:00"}]) is None


# --------------------------------------- selecting the right runs ----------

def _write_summary(directory, task, stamp, passed=True):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{task}_{stamp}.json").write_text(json.dumps({
        "schema_version": max(aggregate_report.SUPPORTED_SCHEMAS),
        "provenance": {"model": "m", "provider": "p"},
        "task_id": task, "task_name": task, "run_timestamp": stamp,
        "passed_overall": passed, "total_fix_attempts": 1, "regression_fails": 0,
        "apply_failed": 0, "ineffective_patches": 0,
        "stage_iterations": {"integration": 1, "system": 1, "unit": 1},
        "patch_outcomes": {"applied": 1, "apply_failed": 0,
                           "too_large": 0, "generation_failed": 0},
        "duration_seconds": 10,
        "stage_first_attempt_pass": {"integration": True, "system": True, "unit": True},
    }), encoding="utf-8")


def test_last_n_selects_the_newest_runs_not_an_arbitrary_n(tmp_path, monkeypatch):
    """
    `--last N` is how a sweep is scoped to the runs it just produced, and it
    depends entirely on the sort two lines above it. Mutating the sort key from
    `or ""` to `and ""` makes every key the empty string, so the order becomes
    arbitrary and `--last` returns whichever runs happen to be first on disk.

    That is the same failure as the schema bug this file was started for: not a
    crash, not a missing file, just a number computed over the wrong runs. It
    is worth an explicit test because the symptom is indistinguishable from a
    correct answer.
    """
    monkeypatch.setattr(aggregate_report, "RUN_SUMMARY_DIR", str(tmp_path))
    for stamp in ("20260101_000000", "20260301_000000", "20260201_000000"):
        _write_summary(tmp_path, "T", stamp)

    payloads, _ = aggregate_report.load_summaries(last=2)
    got = [p["run_timestamp"] for p in payloads]
    assert got == ["20260201_000000", "20260301_000000"], (
        f"--last 2 returned {got}, so it is not selecting the newest runs")


def test_summaries_come_back_oldest_first(tmp_path, monkeypatch):
    """The documented order, which the trimming above relies on."""
    monkeypatch.setattr(aggregate_report, "RUN_SUMMARY_DIR", str(tmp_path))
    for stamp in ("20260301_000000", "20260101_000000", "20260201_000000"):
        _write_summary(tmp_path, "T", stamp)
    payloads, _ = aggregate_report.load_summaries()
    stamps = [p["run_timestamp"] for p in payloads]
    assert stamps == sorted(stamps)


# ------------------------------------------ writing twice is not an error ---

def test_a_second_aggregate_does_not_fail_on_an_existing_directory(tmp_path, monkeypatch):
    """
    `os.makedirs(..., exist_ok=True)` survived becoming `exist_ok=False`, and
    with that change the *second* aggregate ever generated raises
    FileExistsError. Every test used a fresh temporary directory, so nothing
    noticed a bug that would appear on any real machine the moment a report was
    generated twice.
    """
    monkeypatch.setattr(aggregate_report, "RUN_SUMMARY_DIR", str(tmp_path / "in"))
    monkeypatch.setattr(aggregate_report, "AGGREGATE_DIR", str(tmp_path / "out"))
    _write_summary(tmp_path / "in", "T", "20260101_000000")

    first = aggregate_report.generate_aggregate_report(label="one")
    second = aggregate_report.generate_aggregate_report(label="two")
    assert first[0] and second[0]
    assert first[0] != second[0]


def test_writing_a_run_summary_twice_is_not_an_error(tmp_path, monkeypatch):
    """The same guard on the writer side, for the same reason."""
    monkeypatch.setattr(run_summary, "RUN_SUMMARY_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(run_summary, "build_payload",
                        lambda task_id, ts=None: {"task_id": "T", "run_timestamp": ts})
    assert run_summary.record("T", "20260101_000000")
    assert run_summary.record("T", "20260101_000001"), (
        "the second summary of the session failed to write")
    assert len(list((tmp_path / "s").glob("*.json"))) == 2


# -------------------------------------------------- the pooled interval ----

def test_the_pooled_interval_is_rendered_when_it_exists():
    """
    The per-task interval was pinned earlier; this is the pooled one, which is
    the figure that actually gets quoted. `is not None` survived becoming
    `is None`, printing n/a for every aggregate that has an interval.
    """
    agg = _agg()
    lo = aggregate_report._pct(agg["pooled_ci_low"])
    hi = aggregate_report._pct(agg["pooled_ci_high"])
    html = aggregate_report.render_aggregate_html(agg, 0)
    assert f"{lo}-{hi}" in html, "the pooled interval is missing"


def test_a_pooled_rate_with_no_interval_says_so():
    agg = _agg()
    agg["pooled_ci_low"] = agg["pooled_ci_high"] = None
    assert "n/a" in aggregate_report.render_aggregate_html(agg, 0)


import pytest


@pytest.fixture(autouse=True)
def _run_all_reports_go_to_a_temp_dir(monkeypatch, tmp_path):
    """
    `run_all.main()` writes a sweep report into outputs/reports/run_all, and
    these tests call it for real with a fake task named T. Nothing redirected
    that, so every pytest run added reports to the live project: 311 of them,
    against 30 real sweeps, before anyone looked. `test_robustness.py` already
    redirected the equivalent directory for its own run_all test; this file
    had simply never been told.
    """
    from qikly.orchestrator import run_all

    monkeypatch.setattr(run_all, "LOG_DIR", str(tmp_path))
