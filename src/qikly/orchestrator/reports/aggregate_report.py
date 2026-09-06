import sys
"""
Aggregates many runs' convergence outcomes into one report.

Every other report in this package describes a single run. That is the wrong
unit for the question this answers: convergence is not deterministic. Real
sweeps of the same nine tasks have come back 5/9, 6/9, and 8/9, and one task
has stalled on a run using the same inputs and seed that passed the day
before. A single sweep's "8 of 9 converged" is one draw from a distribution,
and quoting it as though it were a measurement overstates what one run can
support.

So this reads the machine-readable per-run summaries that
orchestrator/run_summary.py already writes (one JSON per task per run) and
reports, per task and pooled:

  - convergence rate with a Wilson score interval, which behaves sensibly at
    the small n and extreme proportions this actually runs at, where the
    textbook normal approximation produces intervals running past 0 or 1
  - iterations, FIX attempts, apply failures and regressions as a spread
    (mean, sd, min-max), not a single number
  - how many runs did not converge, kept separate rather than folded in

That last point is the one worth stating plainly. A run that exhausts its
retry budget is right-censored: it tells you convergence took *more* than
the budget, not that it would never have happened. Averaging iteration counts
over converged runs alone therefore biases the mean downward, and this report
labels that rather than hiding it. Proper survival estimation over these
censored observations is the natural next step and is deliberately not done
here.

Reads only files already on disk and makes no LLM calls, so it is free to
re-run and gives the same answer every time.

    python -m qikly.orchestrator.reports.aggregate_report
    python -m qikly.orchestrator.reports.aggregate_report --last 10
    python -m qikly.orchestrator.reports.aggregate_report --task CALC_TAX
    python -m qikly.orchestrator.reports.aggregate_report --runs 20260813_152716,20260813_144016
"""
import glob
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime

from qikly.orchestrator.reports.report import _esc
from qikly.orchestrator.reports.metrics_report import CSS

AGGREGATE_DIR = "outputs/reports/aggregate"
RUN_SUMMARY_DIR = "outputs/reports/run_summary"
LOG_DIR = "outputs/logs"

# 95%. Kept as a name rather than inlined because it appears in the rendered
# report's own labels, and the two must not drift apart.
Z_95 = 1.959963985
# Every run-summary schema this reader can pool. It is a set rather than a
# single number for a reason worth recording: when `run_summary.py` went to 4
# to carry provenance, this constant stayed at 3, so a 400-run sweep was
# skipped in full and the aggregate silently reported a rate computed from
# two-week-old runs instead. Nothing failed and the number looked plausible.
#
# 4 adds a `provenance` block and changes no existing field, so 3 and 4 pool
# safely. `tests/test_aggregate_schema.py` fails the build if the writer ever
# moves ahead of this set again.
SUPPORTED_SCHEMAS = frozenset({3, 4})


def load_summaries(task_ids=None, run_timestamps=None, last=None):
    """
    Every run summary on disk, optionally filtered to some tasks and/or some
    run_timestamps, then optionally trimmed to each task's `last` most recent
    runs. Returns a list of payload dicts, oldest first.

    Summaries written by a schema this reader does not know are skipped rather
    than guessed at: the fields are documented as free to change shape, so a
    reader that silently accepted any version would eventually average
    incomparable numbers together.

    Skipping is counted and surfaced by the caller. A silent skip is how a
    sweep can vanish and leave a plausible number behind.
    """
    payloads, skipped = [], 0
    for path in sorted(glob.glob(os.path.join(RUN_SUMMARY_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if payload.get("schema_version") not in SUPPORTED_SCHEMAS:
            skipped += 1
            continue
        if task_ids and payload.get("task_id") not in task_ids:
            continue
        if run_timestamps and payload.get("run_timestamp") not in run_timestamps:
            continue
        payloads.append(payload)

    payloads.sort(key=lambda p: (p.get("task_id") or "", p.get("run_timestamp") or ""))

    if last:
        trimmed = []
        by_task = defaultdict(list)
        for p in payloads:
            by_task[p["task_id"]].append(p)
        for task_id in sorted(by_task):
            trimmed.extend(by_task[task_id][-last:])
        payloads = trimmed

    return payloads, skipped


def wilson_interval(successes, n, z=Z_95):
    """
    Wilson score interval for a binomial proportion. Chosen over the normal
    approximation because n here is the number of repeated sweeps -- often
    under 20 -- and the proportion is often 0 or 1, exactly where the normal
    approximation degenerates into a zero-width or out-of-range interval.
    """
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _spread(values):
    """mean/sd/min/max, with sd None below two observations rather than 0."""
    if not values:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    n = len(values)
    mean = sum(values) / n
    sd = None
    if n > 1:
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return {"n": n, "mean": mean, "sd": sd, "min": min(values), "max": max(values)}


def _median(values):
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _total_iterations(payload):
    return sum((payload.get("stage_iterations") or {}).values())


def _test_names(failed_tests):
    """
    pytest's own output is echoed into the log twice per failure -- once as
    the progress line ("path::name FAILED [ 43%]") and once in the summary
    ("FAILED path::name"). Both are kept verbatim in the log on purpose, so
    reducing them to a set of bare test names is this reader's job.
    """
    names = set()
    for entry in failed_tests or []:
        text = entry.strip()
        if text.startswith("FAILED "):
            text = text[len("FAILED "):]
        name = text.split("::")[-1]
        name = re.sub(r"\s+FAILED.*$", "", name).strip()
        if name:
            names.add(name)
    return names


# Words that appear in test names regardless of what is being tested, so
# carry no signal about what a run got stuck on.
_STOP_TOKENS = {
    "test", "and", "or", "the", "a", "an", "is", "are", "with", "without",
    "to", "of", "for", "in", "on", "as", "run", "etl", "end", "row", "rows",
    "valid", "invalid", "handling", "output", "input", "case", "cases",
}

# Crude suffix stripping, not real stemming: enough to make "abbreviation"
# and "abbreviations", or "expand" and "expansion", land on the same token.
# Deliberately not a dependency -- this only has to group test names.
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ies", "s")


def _stem(token):
    for suffix in _SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def persistent_failure_signature(task_id, run_timestamp):
    """
    What a run was *persistently* stuck on, not merely what failed last.

    Taking the final failing test run turns out to be misleading: a stalled
    run's last iteration often shows a narrower, incidental failure while the
    tests it never managed to fix appeared over and over before it. So this
    counts how many failing test runs each test name appears in and keeps the
    ones present in at least half of them.

    Returns (stage, tuple_of_names) or None when nothing can be recovered.
    """
    path = os.path.join(LOG_DIR, f"transactions_{task_id}_{run_timestamp}.jsonl")
    if not os.path.exists(path):
        return None

    occurrences = defaultdict(int)
    failing_runs = 0
    last_stage = None
    last_names = ()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (event.get("action") != "test_run"
                        or event.get("status") != "fail"
                        or not event.get("failed_tests")):
                    continue
                names = _test_names(event.get("failed_tests"))
                if not names:
                    continue
                failing_runs += 1
                last_stage = event.get("stage")
                last_names = tuple(sorted(names))
                for name in names:
                    occurrences[name] += 1
    except OSError:
        return None

    if not failing_runs:
        return None

    # "Survived at least one fix attempt" -- a test that failed, was fixed
    # against, and failed again. A proportional threshold looked cleaner but
    # discarded the real signal: a stalled run's later iterations often narrow
    # to one incidental failure, which then outvotes the cluster that actually
    # blocked it.
    persistent = sorted(n for n, c in occurrences.items() if c >= 2)
    return (last_stage, tuple(persistent or last_names)) if (persistent or last_names) else None


def _vocabulary(clusters):
    """
    How many stalled runs mention each meaningful word across their stuck
    tests. Generated test names are model-written, so two runs stuck on the
    same rule rarely produce identical names -- but they do reuse the same
    vocabulary. This is what shows "four runs, one theme" when exact-set
    grouping would show four singletons.
    """
    counts = defaultdict(int)
    for cluster in clusters:
        tokens = set()
        for name in cluster["tests"]:
            for raw in name.split("_"):
                token = _stem(raw.lower())
                if token and token not in _STOP_TOKENS and len(token) > 2:
                    tokens.add(token)
        for token in tokens:
            counts[token] += cluster["runs"]
    return [
        {"token": t, "runs": c}
        for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _cluster_failures(censored_runs, task_id):
    """
    Groups non-converged runs by what they were stuck on, most common first.
    Runs whose signature can't be recovered are reported as unattributed
    rather than silently dropped -- an unexplained stall is the one that
    actually counts against the tool.
    """
    groups = defaultdict(list)
    unattributed = []
    for run in censored_runs:
        stamp = run.get("run_timestamp")
        sig = persistent_failure_signature(task_id, stamp) if stamp else None
        if sig is None:
            unattributed.append(stamp)
        else:
            groups[sig].append(stamp)

    clusters = [
        {
            "stage": stage,
            "tests": list(tests),
            "runs": len(stamps),
            "run_timestamps": sorted(s for s in stamps if s),
        }
        for (stage, tests), stamps in groups.items()
    ]
    clusters.sort(key=lambda c: (-c["runs"], c["stage"] or ""))
    return clusters, sorted(s for s in unattributed if s)


def aggregate(payloads):
    """
    Per-task and pooled statistics over the given run summaries.

    Iteration statistics are computed over converged runs only, with the
    censored count reported alongside, because a budget-exhausted run's
    iteration count is a lower bound on what convergence would have cost, not
    an observation of it.
    """
    by_task = defaultdict(list)
    for p in payloads:
        by_task[p["task_id"]].append(p)

    tasks = {}
    for task_id, runs in sorted(by_task.items()):
        converged = [r for r in runs if r.get("passed_overall")]
        censored = [r for r in runs if not r.get("passed_overall")]
        n = len(runs)
        k = len(converged)
        lo, hi = wilson_interval(k, n)
        clusters, unattributed = _cluster_failures(censored, task_id)
        tasks[task_id] = {
            "failure_clusters": clusters,
            "failure_vocabulary": _vocabulary(clusters),
            "unattributed_failures": unattributed,
            "runs": n,
            "converged": k,
            "censored": len(censored),
            "convergence_rate": k / n if n else None,
            "ci_low": lo,
            "ci_high": hi,
            "iterations_converged": _spread([_total_iterations(r) for r in converged]),
            "iterations_median_converged": _median([_total_iterations(r) for r in converged]),
            "iterations_censored_at": _spread([_total_iterations(r) for r in censored]),
            "fix_attempts": _spread([r.get("total_fix_attempts", 0) for r in runs]),
            "apply_failed": _spread([r.get("apply_failed", 0) for r in runs]),
            "regression_fails": _spread([r.get("regression_fails", 0) for r in runs]),
            "duration_seconds": _spread(
                [r["duration_seconds"] for r in runs if r.get("duration_seconds") is not None]
            ),
            "run_timestamps": sorted({r.get("run_timestamp") for r in runs if r.get("run_timestamp")}),
        }

    total_runs = len(payloads)
    total_converged = sum(1 for p in payloads if p.get("passed_overall"))
    pooled_lo, pooled_hi = wilson_interval(total_converged, total_runs)

    return {
        "schema_version": 1,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "task_count": len(tasks),
        "total_runs": total_runs,
        "total_converged": total_converged,
        "pooled_convergence_rate": total_converged / total_runs if total_runs else None,
        "pooled_ci_low": pooled_lo,
        "pooled_ci_high": pooled_hi,
        "tasks": tasks,
    }


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def _num(x, places=1):
    if x is None:
        return "n/a"
    return f"{x:.{places}f}" if isinstance(x, float) else str(x)


def _spread_cell(s):
    if not s["n"]:
        return "n/a"
    if s["sd"] is None:
        return f"{_num(s['mean'])}"
    return f"{_num(s['mean'])} ± {_num(s['sd'])} <span class=\"muted\">({s['min']}-{s['max']})</span>"


def _task_table_html(agg):
    rows = []
    for task_id, t in agg["tasks"].items():
        ci = "n/a"
        if t["ci_low"] is not None:
            ci = f"{_pct(t['ci_low'])}-{_pct(t['ci_high'])}"
        censored_note = f"{t['censored']}" if t["censored"] else "0"
        rows.append(
            f"<tr><td>{_esc(task_id)}</td>"
            f"<td>{t['converged']} / {t['runs']}</td>"
            f"<td>{_pct(t['convergence_rate'])}</td>"
            f"<td>{_esc(ci)}</td>"
            f"<td>{_num(t['iterations_median_converged'])}</td>"
            f"<td>{_spread_cell(t['fix_attempts'])}</td>"
            f"<td>{_spread_cell(t['regression_fails'])}</td>"
            f"<td>{censored_note}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Task</th><th>Converged</th><th>Rate</th>"
        "<th>95% CI (Wilson)</th><th>Median iterations<br>(converged only)</th>"
        "<th>FIX attempts</th><th>Regression failures</th>"
        "<th>Censored runs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _failure_clusters_html(agg):
    blocks = []
    for task_id, t in agg["tasks"].items():
        clusters = t.get("failure_clusters") or []
        unattributed = t.get("unattributed_failures") or []
        if not clusters and not unattributed:
            continue
        rows = []
        for c in clusters:
            share = f"{c['runs']} of {t['censored']}"
            tests = "".join(f"<li><span class=\"mono\">{_esc(name)}</span></li>" for name in c["tests"])
            rows.append(
                f"<tr><td>{_esc(share)}</td><td>{_esc(c['stage'] or ', ')}</td>"
                f"<td><ul class=\"sig\">{tests}</ul></td></tr>"
            )
        if unattributed:
            rows.append(
                f"<tr><td>{len(unattributed)} of {t['censored']}</td><td>, </td>"
                "<td><em>No failing test run recorded, so this run is unexplained.</em></td></tr>"
            )
        vocab = [v for v in (t.get("failure_vocabulary") or []) if v["runs"] > 1]
        vocab_html = ""
        if vocab:
            chips = "".join(
                f'<span class="badge">{_esc(v["token"])} <strong>{v["runs"]}/{t["censored"]}</strong></span>'
                for v in vocab[:10]
            )
            vocab_html = (
                "<p class=\"lede-note\">Shared vocabulary across the stalled runs, model-written "
                "test names rarely match exactly, so this is what actually reveals a common cause:</p>"
                f'<div class="badge-row">{chips}</div>'
            )
        blocks.append(
            f"<h3>{_esc(task_id)}: {t['censored']} run(s) did not converge</h3>"
            f"{vocab_html}"
            "<table><thead><tr><th>Runs</th><th>Stage</th>"
            "<th>Persistently failing when the budget ran out</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    if not blocks:
        return "<p>Every run converged, so there is nothing to attribute.</p>"
    return "".join(blocks)


def render_aggregate_html(agg, skipped):
    pooled_ci = "n/a"
    if agg["pooled_ci_low"] is not None:
        pooled_ci = f"{_pct(agg['pooled_ci_low'])}-{_pct(agg['pooled_ci_high'])}"
    skipped_note = (
        f" {skipped} summary file(s) skipped: unreadable, or written by an older schema."
        if skipped else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aggregate metrics - {agg['total_runs']} runs</title>
<style>{CSS}
.muted {{ opacity: 0.65; font-size: 0.9em; }}
.lede-note {{ max-width: 70ch; opacity: 0.8; }}
ul.sig {{ margin: 0; padding-left: 1.1em; }}
ul.sig li {{ margin: 0.15em 0; }}
.caveat {{ margin-top: 2em; padding: 1em 1.2em; border-left: 3px solid var(--status-warning); }}
</style>
</head>
<body>
<main>
  <h1>Aggregate metrics</h1>
  <div class="run-meta">{agg['total_runs']} run(s) across {agg['task_count']} task(s), generated {_esc(agg['generated'])}</div>
  <div class="result-banner {'result-pass' if (agg['pooled_convergence_rate'] or 0) >= 0.5 else 'result-fail'}">
    POOLED CONVERGENCE {agg['total_converged']} / {agg['total_runs']} = {_pct(agg['pooled_convergence_rate'])} (95% CI {_esc(pooled_ci)})
  </div>

  <h2>By task</h2>
  {_task_table_html(agg)}

  <h2>What the non-converged runs were stuck on</h2>
  <p class="lede-note">A convergence rate on its own cannot distinguish &ldquo;unreliable&rdquo; from
  &ldquo;one defective rule, hit repeatedly&rdquo;. These are the tests each stalled run was still
  failing when its budget ran out, grouped by signature. Several runs sharing one signature is a
  single defect, not several.</p>
  {_failure_clusters_html(agg)}

  <div class="caveat">
    <strong>Reading the censored column.</strong> A run that exhausted its retry budget
    did not prove convergence impossible; it proves only that convergence would have
    cost more than the budget allowed. Those runs are right-censored, so the median
    iteration count above (computed over converged runs only) is biased low wherever
    that column is non-zero. Treat it as a lower bound, not an estimate.
    {_esc(skipped_note)}
  </div>

  <footer class="report-footer">Generated by orchestrator/reports/aggregate_report.py from {_esc(RUN_SUMMARY_DIR)}/*.json. The per-run transaction logs under outputs/logs/ remain the source of truth.</footer>
</main>
</body>
</html>
"""


def generate_aggregate_report(task_ids=None, run_timestamps=None, last=None, label=None):
    """
    Writes an HTML report and its JSON companion. Returns (html_path,
    json_path), or (None, None) if no usable run summaries matched.
    """
    payloads, skipped = load_summaries(task_ids=task_ids, run_timestamps=run_timestamps, last=last)
    if not payloads:
        return None, None

    agg = aggregate(payloads)
    stamp = label or datetime.now().strftime("%Y%m%d_%H%M%S")

    os.makedirs(AGGREGATE_DIR, exist_ok=True)
    html_path = os.path.join(AGGREGATE_DIR, f"aggregate_{stamp}.html")
    json_path = os.path.join(AGGREGATE_DIR, f"aggregate_{stamp}.json")

    with open(html_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_aggregate_html(agg, skipped))
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(agg, f, indent=2)

    return html_path, json_path


def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Aggregate many runs' convergence outcomes into one report, "
                    "with confidence intervals rather than single-run point estimates."
    )
    parser.add_argument("--task", default=None, help="Comma-separated task_ids (default: every task with summaries)")
    parser.add_argument("--runs", default=None, help="Comma-separated run_timestamps to include (default: all on disk)")
    parser.add_argument("--last", type=int, default=None, help="Use only each task's N most recent runs")
    parser.add_argument("--label", default=None, help="Filename stamp for the output (default: now)")
    return parser.parse_args()


def main():
    from qikly.console import use_utf8

    use_utf8()

    args = _parse_args()
    task_ids = [t.strip() for t in args.task.split(",") if t.strip()] if args.task else None
    run_timestamps = [r.strip() for r in args.runs.split(",") if r.strip()] if args.runs else None

    html_path, json_path = generate_aggregate_report(
        task_ids=task_ids, run_timestamps=run_timestamps, last=args.last, label=args.label
    )
    if not html_path:
        print(f"No usable run summaries found under {RUN_SUMMARY_DIR}/ for that filter.")
        return

    # Said on the console, not only in the HTML. A skipped summary used to be a
    # footnote in a file nobody opens, which is how a whole sweep was dropped
    # while the printed rate still looked reasonable.
    _, skipped = load_summaries(task_ids=task_ids, run_timestamps=run_timestamps)
    if skipped:
        print(
            f"WARNING: {skipped} summary file(s) were skipped as unreadable or "
            f"written by a schema this reader does not know "
            f"({', '.join(str(v) for v in sorted(SUPPORTED_SCHEMAS))}). "
            f"The figures below do NOT include them."
        )

    with open(json_path, encoding="utf-8") as f:
        agg = json.load(f)
    rate = agg["pooled_convergence_rate"]
    print(
        f"Pooled convergence: {agg['total_converged']}/{agg['total_runs']} "
        f"= {', ' if rate is None else f'{100 * rate:.0f}%'} "
        f"(95% CI {_pct(agg['pooled_ci_low'])}-{_pct(agg['pooled_ci_high'])}) "
        f"across {agg['task_count']} task(s)"
    )
    print(f"Wrote {html_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
