import sys
"""
A numbers-first companion to orchestrator/reports/report.py's
debugging-timeline report: one run's outcome as a KPI row, a per-stage
iteration chart, and a FIX/PATCH outcome breakdown, rather than the full
replay. Scoped to a single run today; the computations here (patch-outcome
buckets, per-stage detail, duration) are the same ones a future cross-run
dashboard would aggregate, so this is deliberately built as "one run's
slice of that dashboard's data" rather than a one-off.

No PROJECT_ROOT/os.chdir of its own -- report.py's module-level chdir
(triggered by the import below) already covers it, since both live in this
same package.
"""
import os
from collections import OrderedDict
from datetime import datetime

from qikly.orchestrator.reports.report import (
    _esc,
    _latest_transactions_path,
    _load_task_meta,
    _run_timestamp_from_path,
    _stage_label,
    build_blocks,
    compute_summary,
    group_by_stage,
    load_events,
)

METRICS_DIR = "outputs/reports/metrics"

_PATCH_OUTCOME_BUCKETS = ["applied", "apply_failed", "too_large", "generation_failed"]
_OUTCOME_LABELS = {
    "applied": "Applied",
    "apply_failed": "Failed to apply",
    "too_large": "Rejected (too large)",
    "generation_failed": "FIX/PATCH generation failed",
}
_OUTCOME_STATUS_VAR = {
    "applied": "--status-good",
    "apply_failed": "--status-serious",
    "too_large": "--status-warning",
    "generation_failed": "--status-critical",
}


def _classify_fix_cycle_outcome(block):
    actions = {s.get("action") for s in block["steps"]}
    if "fix_generation_failed" in actions or "patch_generation_failed" in actions:
        return "generation_failed"
    if "patch_too_large" in actions:
        return "too_large"
    if "patch_apply_failed" in actions:
        return "apply_failed"
    if "patch_created" in actions:
        return "applied"
    return "generation_failed"


def compute_patch_outcomes(blocks):
    counts = {k: 0 for k in _PATCH_OUTCOME_BUCKETS}
    for b in blocks:
        if b["type"] == "fix_cycle":
            counts[_classify_fix_cycle_outcome(b)] += 1
    return counts


def compute_duration(events):
    """
    Wall-clock span from this run's first logged event to its last, using
    the "ts" field log_transaction() stamps on every entry. Returns None for
    logs from before that field existed, or a run too short/incomplete to
    have two distinct timestamps.
    """
    timestamps = [e["ts"] for e in events if e.get("ts")]
    if len(timestamps) < 2:
        return None
    try:
        start = datetime.fromisoformat(timestamps[0])
        end = datetime.fromisoformat(timestamps[-1])
    except ValueError:
        return None
    return end - start


def _format_duration(td):
    if td is None:
        return "unknown"
    total_seconds = int(td.total_seconds())
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def compute_stage_details(stage_groups):
    details = OrderedDict()
    for stage, blocks in stage_groups.items():
        test_runs = [b for b in blocks if b["type"] == "test_run"]
        primary = [b for b in test_runs if not b.get("is_regression_check")]
        regchecks = [b for b in test_runs if b.get("is_regression_check")]
        details[stage] = {
            "iterations": len(primary),
            "first_attempt_pass": bool(primary) and primary[0].get("status") == "pass",
            "regression_checks": len(regchecks),
            "regression_failures": sum(1 for b in regchecks if b.get("status") != "pass"),
        }
    return details


CSS = """
:root {
  color-scheme: light dark;
  --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --border: rgba(11,11,11,0.10); --grid: #e1e0d9;
  --series-1: #2a78d6;
  --status-good: #0ca30c; --status-warning: #fab219; --status-serious: #ec835a; --status-critical: #d03b3b;
  --ok-text: #006300; --ok-bg: #e6f4ea; --err-bg: #fbe6e4;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff; --text-secondary: #c3c2b7;
    --muted: #898781; --border: rgba(255,255,255,0.10); --grid: #2c2c2a;
    --series-1: #3987e5;
    --ok-text: #0ca30c; --ok-bg: #163420; --err-bg: #3a1c1a;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff; --text-secondary: #c3c2b7;
  --muted: #898781; --border: rgba(255,255,255,0.10); --grid: #2c2c2a;
  --series-1: #3987e5;
  --ok-text: #0ca30c; --ok-bg: #163420; --err-bg: #3a1c1a;
}
* { box-sizing: border-box; }
body {
  background: var(--page); color: var(--text-primary); margin: 0; padding: 2rem 1.25rem 4rem;
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.5;
}
main { max-width: 900px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 0.15rem; }
h2 { font-size: 1.05rem; margin: 2.25rem 0 0.75rem; }
.run-meta { color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0.9rem; }
.run-meta a { color: var(--series-1); }
.result-banner {
  display: inline-block; font-weight: 600; font-size: 0.85rem; letter-spacing: 0.03em;
  padding: 0.3rem 0.7rem; border-radius: 6px; margin-bottom: 1.5rem;
}
.result-pass { color: var(--ok-text); background: var(--ok-bg); }
.result-fail { color: var(--status-critical); background: var(--err-bg); }
.single-run-note {
  max-width: 78ch; font-size: 0.85rem; color: var(--text-secondary);
  border-left: 3px solid var(--status-warning); padding: 0.6rem 0 0.6rem 0.9rem;
  margin: 0 0 1.5rem;
}
.single-run-note strong { color: var(--text-primary); }

.kpi-row { display: flex; flex-wrap: wrap; gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.kpi-tile { flex: 1 1 140px; background: var(--surface-1); padding: 0.9rem 1rem; }
.kpi-value { font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums; display: block; }
.kpi-label { font-size: 0.75rem; color: var(--text-secondary); }

.bar-chart { display: flex; flex-direction: column; gap: 0.6rem; }
.bar-row { display: grid; grid-template-columns: 100px 1fr 3rem; align-items: center; gap: 0.6rem; font-size: 0.85rem; }
.bar-row .bar-label { color: var(--text-secondary); text-align: right; }
.bar-track { background: var(--grid); border-radius: 4px; height: 14px; overflow: hidden; }
.bar-fill { background: var(--series-1); height: 100%; border-radius: 4px; min-width: 2px; }
.bar-value { font-variant-numeric: tabular-nums; color: var(--text-secondary); }

.outcome-bar { display: flex; height: 28px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
.outcome-seg { height: 100%; }
.outcome-legend { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.7rem; font-size: 0.85rem; }
.legend-item { display: flex; align-items: center; gap: 0.4rem; color: var(--text-secondary); }
.legend-swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }
.legend-item strong { color: var(--text-primary); font-variant-numeric: tabular-nums; }

table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th, td { text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--border); }
th { color: var(--text-secondary); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.02em; }
td { font-variant-numeric: tabular-nums; }
.yes { color: var(--ok-text); } .no { color: var(--status-critical); }

.report-footer { color: var(--muted); font-size: 0.75rem; margin-top: 3rem; border-top: 1px solid var(--border); padding-top: 0.75rem; }
"""


def _kpi_row_html(summary, outcomes, total_fix_attempts, duration_td, stage_iterations_total):
    apply_failure_rate = (
        round(100 * outcomes["apply_failed"] / total_fix_attempts) if total_fix_attempts else 0
    )
    ineffective_rate = (
        round(100 * summary["ineffective_patches"] / total_fix_attempts) if total_fix_attempts else 0
    )
    tiles = [
        (str(stage_iterations_total), "Total iterations"),
        (str(total_fix_attempts), "FIX/PATCH attempts"),
        (str(summary["regression_fails"]), "Regressions caught"),
        (f"{apply_failure_rate}%", "Patch apply-failure rate"),
        (f"{ineffective_rate}%", "Patches with no effect"),
        (_format_duration(duration_td), "Run duration"),
    ]
    cells = "".join(
        f'<div class="kpi-tile"><span class="kpi-value">{_esc(v)}</span>'
        f'<span class="kpi-label">{_esc(l)}</span></div>'
        for v, l in tiles
    )
    return f'<div class="kpi-row">{cells}</div>'


def _stage_bar_chart_html(stage_details):
    max_iter = max((d["iterations"] for d in stage_details.values()), default=0) or 1
    rows = []
    for stage, d in stage_details.items():
        pct = round(100 * d["iterations"] / max_iter)
        rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{_esc(_stage_label(stage))}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{pct}%"></span></span>'
            f'<span class="bar-value">{d["iterations"]}</span>'
            f'</div>'
        )
    return f'<div class="bar-chart">{"".join(rows)}</div>'


def _outcome_breakdown_html(outcomes):
    total = sum(outcomes.values()) or 1
    segs = []
    legend = []
    for key in _PATCH_OUTCOME_BUCKETS:
        count = outcomes[key]
        if count == 0:
            continue
        pct = round(100 * count / total)
        var = _OUTCOME_STATUS_VAR[key]
        segs.append(f'<span class="outcome-seg" style="width:{pct}%;background:var({var})"></span>')
        legend.append(
            f'<span class="legend-item"><span class="legend-swatch" style="background:var({var})"></span>'
            f'{_esc(_OUTCOME_LABELS[key])}: <strong>{count}</strong></span>'
        )
    bar = f'<div class="outcome-bar">{"".join(segs)}</div>' if segs else '<div class="empty">No FIX/PATCH attempts were made.</div>'
    return bar + f'<div class="outcome-legend">{"".join(legend)}</div>'


def _stage_table_html(stage_details):
    rows = []
    for stage, d in stage_details.items():
        first_pass_cls = "yes" if d["first_attempt_pass"] else "no"
        first_pass_text = "yes" if d["first_attempt_pass"] else "no"
        regcheck_text = (
            f'{d["regression_checks"]} ({d["regression_failures"]} failed)'
            if d["regression_checks"] else "n/a"
        )
        rows.append(
            f"<tr><td>{_esc(_stage_label(stage))}</td><td>{d['iterations']}</td>"
            f'<td class="{first_pass_cls}">{first_pass_text}</td>'
            f"<td>{_esc(regcheck_text)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Stage</th><th>Iterations</th>"
        "<th>Passed first attempt</th><th>Regression re-checks</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_metrics_html(task_id, run_timestamp, summary, outcomes, stage_details, duration_td, task_meta):
    total_fix_attempts = summary["total_fix_attempts"]
    stage_iterations_total = sum(d["iterations"] for d in stage_details.values())
    result_cls = "result-pass" if summary["passed_overall"] else "result-fail"
    result_text = "ALL STAGES PASSED" if summary["passed_overall"] else "DID NOT COMPLETE"
    try:
        ts_display = datetime.strptime(run_timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        ts_display = run_timestamp
    title_extra = f': {_esc(task_meta["task_name"])}' if task_meta.get("task_name") else ""
    timeline_href = f"../iterations/{_esc(task_id)}_{_esc(run_timestamp)}_report.html"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Metrics - {_esc(task_id)} - {_esc(run_timestamp)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
  <h1>{_esc(task_id)}{title_extra}</h1>
  <div class="run-meta">Run {_esc(ts_display)} - <a href="{timeline_href}">view debugging timeline</a></div>
  <div class="result-banner {result_cls}">{result_text}</div>
  <p class="single-run-note"><strong>This is one run, not a measurement.</strong> Convergence is not
  deterministic: the same task, with the same inputs and the same seed, converges on some runs and
  exhausts its budget on others. Nothing on this page supports a claim about how often this task
  converges. For that, repeat the sweep &mdash; <span class="mono">run_all --repeat N</span> &mdash; and read
  the aggregate report, which gives a rate with a confidence interval.</p>

  {_kpi_row_html(summary, outcomes, total_fix_attempts, duration_td, stage_iterations_total)}

  <h2>Iterations per stage</h2>
  {_stage_bar_chart_html(stage_details)}

  <h2>FIX/PATCH outcomes</h2>
  {_outcome_breakdown_html(outcomes)}

  <h2>Stage detail</h2>
  {_stage_table_html(stage_details)}

  <footer class="report-footer">Generated by orchestrator/reports/metrics_report.py from outputs/logs/transactions_{_esc(task_id)}_{_esc(run_timestamp)}.jsonl. Full debugging timeline: <a href="{timeline_href}">{_esc(task_id)}_{_esc(run_timestamp)}_report.html</a></footer>
</main>
</body>
</html>
"""


def generate_metrics_report(task_id, run_timestamp=None):
    if run_timestamp is None:
        path = _latest_transactions_path(task_id)
        run_timestamp = _run_timestamp_from_path(task_id, path)
    else:
        path = os.path.join("outputs/logs", f"transactions_{task_id}_{run_timestamp}.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No transaction log at {path}")

    events = load_events(path)
    blocks = build_blocks(events)
    summary = compute_summary(blocks)
    outcomes = compute_patch_outcomes(blocks)
    stage_groups = group_by_stage(blocks)
    stage_details = compute_stage_details(stage_groups)
    duration_td = compute_duration(events)
    task_meta = _load_task_meta(task_id)

    html_doc = render_metrics_html(
        task_id, run_timestamp, summary, outcomes, stage_details, duration_td, task_meta
    )

    os.makedirs(METRICS_DIR, exist_ok=True)
    out_path = os.path.join(METRICS_DIR, f"{task_id}_{run_timestamp}_metrics.html")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_doc)
    return out_path


def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate a numbers-first metrics report from a V&V run's transaction log."
    )
    parser.add_argument("--task", default=None, help="task_id (default: every task under config/tasks/ (yours in inputs_private/, plus the bundled ones))")
    parser.add_argument("--run", default=None, help="run_timestamp to report on (default: that task's latest run)")
    return parser.parse_args()


def main():
    from qikly.orchestrator.orchestrator import discover_task_ids

    args = _parse_args()
    task_ids = [args.task] if args.task else discover_task_ids()
    for task_id in task_ids:
        try:
            path = generate_metrics_report(task_id, run_timestamp=args.run)
            print(f"[{task_id}] wrote {path}")
        except FileNotFoundError as e:
            print(f"[{task_id}] skipped: {e}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
