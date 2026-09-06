"""
Is convergence getting better or worse on my task?

The first question a returning user asks, and until now the reports could not
answer it. The metrics report covers one run. The aggregate report pools many
runs into one rate, which deliberately throws away the order they happened in.
Neither says whether last week was better than this week.

This reads the same run summaries the aggregate reads, keeps them in time
order, and reports each task's rate per period alongside the model and settings
that produced it.

## Why the provenance is on every row

Because the most expensive mistake this project has made was reading a change
in a rate as a change in the tool. A local override tripled every generated
suite and the convergence table appeared to collapse across nine tasks at once;
half a day went into diffing prompts before anyone looked at the config.

A trend line invites exactly that mistake, more strongly than a single rate
does, because a line going down looks like a story. So every period carries the
model and the generation settings behind it, and a period where those changed
is marked. **A rate that moved when the configuration moved is not a trend.**

## Why it does not draw a trend line

No regression, no arrow, no "improving" verdict. Convergence is a proportion
from a small sample, and three periods of ten runs each will show a slope
whatever is happening: the intervals overlap almost everything. Printing a
direction would manufacture a finding from noise, which is the failure this
project exists to make harder. The intervals are printed instead, and the
reader draws their own conclusion or collects more runs.
"""
import json
import os
from collections import defaultdict
from datetime import datetime

from qikly.orchestrator.reports.aggregate_report import (SUPPORTED_SCHEMAS,
                                                         wilson_interval)

RUN_SUMMARY_DIR = "outputs/reports/run_summary"
TREND_DIR = "outputs/reports/trend"


def _period(stamp, grain):
    """A run timestamp bucketed by day, week or month."""
    try:
        when = datetime.strptime(stamp[:15], "%Y%m%d_%H%M%S")
    except (ValueError, TypeError):
        return None
    if grain == "month":
        return when.strftime("%Y-%m")
    if grain == "week":
        year, week, _ = when.isocalendar()
        return f"{year}-W{week:02d}"
    return when.strftime("%Y-%m-%d")


def _provenance_key(payload):
    """What a rate belongs to besides the tool: the model and the settings."""
    prov = payload.get("provenance") or {}
    return (prov.get("model") or "unknown",
            prov.get("criteria_per_batch"),
            prov.get("max_retries_per_stage"))


def collect(task_ids=None, grain="day", summary_dir=None):
    """
    Per task, per period: runs, converged, interval, and the configurations
    that produced them.
    """
    directory = summary_dir or RUN_SUMMARY_DIR
    buckets = defaultdict(lambda: defaultdict(
        lambda: {"runs": 0, "converged": 0, "configs": set()}))

    for name in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") not in SUPPORTED_SCHEMAS:
            continue
        task_id = payload.get("task_id")
        if task_ids and task_id not in task_ids:
            continue
        period = _period(payload.get("run_timestamp") or "", grain)
        if not period:
            continue
        cell = buckets[task_id][period]
        cell["runs"] += 1
        cell["converged"] += 1 if payload.get("passed_overall") else 0
        cell["configs"].add(_provenance_key(payload))

    out = {}
    for task_id, periods in buckets.items():
        rows = []
        for period in sorted(periods):
            cell = periods[period]
            low, high = wilson_interval(cell["converged"], cell["runs"])
            rows.append({
                "period": period,
                "runs": cell["runs"],
                "converged": cell["converged"],
                "rate": cell["converged"] / cell["runs"] if cell["runs"] else None,
                "ci_low": low,
                "ci_high": high,
                "configs": sorted(str(c) for c in cell["configs"]),
                "models": sorted({c[0] for c in cell["configs"]}),
            })
        out[task_id] = rows
    return out


def _config_changed(rows):
    """Periods where the model or the generation settings differ from before."""
    marked, seen = [], None
    for row in rows:
        configs = set(row["configs"])
        changed = seen is not None and configs != seen
        marked.append(changed)
        seen = configs
    return marked


def render(trends, grain="day"):
    if not trends:
        return ("No run summaries found, so there is no history to trend. "
                "Convergence history accumulates as you run; come back after a few.")

    lines = [f"Convergence by {grain}, oldest first.", ""]
    for task_id in sorted(trends):
        rows = trends[task_id]
        changed = _config_changed(rows)
        lines.append(f"{task_id}")
        for row, flag in zip(rows, changed):
            rate = f"{100 * row['rate']:3.0f}%" if row["rate"] is not None else "  , "
            interval = f"[{100 * row['ci_low']:3.0f},{100 * row['ci_high']:3.0f}]"
            note = "   <- model or settings changed here" if flag else ""
            lines.append(f"  {row['period']:<12} {row['converged']:>3}/{row['runs']:<3} "
                         f"{rate}  {interval}{note}")
        models = sorted({m for row in rows for m in row["models"]})
        lines.append(f"  model(s): {', '.join(models)}")
        lines.append("")

    lines.append("No trend line is drawn on purpose. A proportion from a small "
                 "sample will show a slope whatever is happening, and the "
                 "intervals above overlap almost everything. Read the intervals, "
                 "or collect more runs.")
    lines.append("A period marked as changed is not comparable with the one "
                 "before it: a rate belongs to a model and a configuration as "
                 "much as to a tool.")
    return "\n".join(lines)


def write_json(trends, label=None, out_dir=None):
    directory = out_dir or TREND_DIR
    os.makedirs(directory, exist_ok=True)
    stamp = label or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(directory, f"trend_{stamp}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(trends, handle, indent=2)
    return path
