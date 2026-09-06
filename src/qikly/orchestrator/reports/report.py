import sys
"""
Turns one run's outputs/logs/transactions_<task_id>_<run_timestamp>.jsonl into
a single self-contained HTML page: a chronological debugging timeline (test
run -> agent's FIX reasoning -> PATCH diff -> apply outcome, repeated per
stage) instead of the scattered .jsonl/.diff/.txt files the run leaves behind.
Reads only what orchestrator.py already logs -- no change to run behavior or
console output.
"""
import glob
import html
import json
import os
from collections import OrderedDict
from datetime import datetime

from qikly.paths import chdir_to_project_root, resolve_input

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/logs"
REPORT_DIR = "outputs/reports/iterations"

# Display only. The "bootstrap" stage is the interface-discovery probe: the
# first stage's suite run against an empty source tree, whose import error
# names the module the implementation has to provide. Unrelated to
# --generate-criteria "criteria seeding" (orchestrator.py), which never
# appears as a stage.
STAGE_LABELS = {"bootstrap": "Bootstrap (interface discovery)"}


def _stage_label(stage):
    return STAGE_LABELS.get(stage, stage.capitalize())


def _latest_transactions_path(task_id):
    """
    run_timestamp is always a "%Y%m%d_%H%M%S" stamp (see orchestrator.py),
    so it always starts with a digit -- the glob is restricted to that
    ([0-9]*, not a bare *) so that e.g. task_id="ETL_ADDRESS" doesn't also
    match transactions_ETL_ADDRESS_DRAFT_<ts>.jsonl (the scratch task
    orchestrator/tuning/refine_acceptance_criteria.py runs under a
    "<task_id>_DRAFT" task_id). Without this, "DRAFT" sorts after
    digit-only timestamps and would permanently shadow the real task's
    actual latest run.
    """
    pattern = os.path.join(LOG_DIR, f"transactions_{task_id}_[0-9]*.jsonl")
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No transaction log found for task_id={task_id!r} under {LOG_DIR}/ "
            f"-- run the orchestrator for this task first."
        )
    return matches[-1]


def _run_timestamp_from_path(task_id, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    prefix = f"transactions_{task_id}_"
    return stem[len(prefix):] if stem.startswith(prefix) else stem


def load_events(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def build_blocks(events):
    """
    Replay the transaction log in order into a flat list of typed blocks:
    "tests_generated", "test_run", "fix_cycle" (one per FIX/PATCH attempt,
    accumulating its own agent_fix_generated/patch_created/apply-outcome
    steps as they arrive), and "all_tests_passed". Blocks stay in the exact
    order the orchestrator logged them, since transactions.jsonl is a single
    append-only log for one (single-process) task run.
    """
    blocks = []
    current = None
    for e in events:
        action = e.get("action")
        if action == "tests_generated":
            blocks.append({"type": "tests_generated", **e})
            current = None
        elif action == "test_run":
            blocks.append({"type": "test_run", **e})
            current = None
        elif action == "agent_fix_requested":
            current = {
                "type": "fix_cycle",
                "fix_id": e.get("fix_id"),
                "stage": e.get("stage"),
                "iteration": e.get("iteration"),
                "failure": e.get("failure"),
                "repeat_failure": e.get("repeat_failure"),
                "steps": [],
            }
            blocks.append(current)
        elif action in (
            "agent_fix_generated", "fix_generation_failed", "patch_created",
            "patch_generation_failed", "patch_too_large", "patch_apply_failed",
        ):
            if current is not None and e.get("fix_id") == current["fix_id"]:
                current["steps"].append(e)
        elif action == "all_tests_passed":
            blocks.append({"type": "all_tests_passed"})
            current = None
    return blocks


def _group_key(block):
    if block["type"] == "test_run":
        return "bootstrap" if block.get("is_bootstrap") else block["stage"]
    if block["type"] == "fix_cycle":
        return block["stage"]
    return None


def group_by_stage(blocks):
    """
    Group into per-stage sections for display, preserving first-seen order
    within each group. A regression fix is logged under the *current* stage
    (see orchestrator.orchestrate()'s call to run_fix_patch_cycle), not the
    stage that regressed -- that's intentional (it reflects whose attempt
    budget the fix counted against), so it's left where the log puts it and
    just badged distinctly in _fix_cycle_html().
    """
    groups = OrderedDict()
    for b in blocks:
        key = _group_key(b)
        if key is None:
            continue
        groups.setdefault(key, []).append(b)
    if "bootstrap" in groups:
        groups.move_to_end("bootstrap", last=False)
    return groups


def _fix_cycle_outcome(block):
    actions = {s.get("action") for s in block["steps"]}
    if "fix_generation_failed" in actions:
        return "FIX generation failed", "outcome-error"
    if "patch_generation_failed" in actions:
        return "PATCH generation failed", "outcome-error"
    if "patch_too_large" in actions:
        return "PATCH too large, rejected", "outcome-warn"
    if "patch_apply_failed" in actions:
        return "PATCH did not apply", "outcome-warn"
    if "patch_created" in actions:
        return "PATCH applied", "outcome-ok"
    return "no patch produced", "outcome-error"


def _read_patch(block):
    for s in block["steps"]:
        if s.get("action") == "patch_created" and s.get("patch_path"):
            path = os.path.normpath(s["patch_path"])
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
    return None


def _error_text(block):
    for s in block["steps"]:
        if "error" in s:
            return s["error"]
    return None


def compute_summary(blocks):
    test_runs = [b for b in blocks if b["type"] == "test_run"]
    fix_cycles = [b for b in blocks if b["type"] == "fix_cycle"]
    stage_iterations = OrderedDict()
    for b in test_runs:
        if b.get("is_regression_check"):
            continue
        key = "bootstrap" if b.get("is_bootstrap") else b["stage"]
        stage_iterations[key] = stage_iterations.get(key, 0) + 1
    return {
        "passed_overall": any(b["type"] == "all_tests_passed" for b in blocks),
        "total_fix_attempts": len(fix_cycles),
        "regression_fails": sum(
            1 for b in test_runs if b.get("is_regression_check") and b.get("status") != "pass"
        ),
        "apply_failed": sum(
            1 for b in fix_cycles if any(s.get("action") == "patch_apply_failed" for s in b["steps"])
        ),
        "ineffective_patches": sum(1 for b in fix_cycles if b.get("repeat_failure")),
        "stage_iterations": stage_iterations,
    }


def _load_task_meta(task_id):
    path = resolve_input(f"config/tasks/{task_id}.yaml")
    try:
        import yaml
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return {"task_name": data.get("task_name"), "description": data.get("description")}
    except Exception:
        return {}


def _esc(s):
    return html.escape(s if s is not None else "", quote=False)


def _diff_html(diff_text):
    if not diff_text:
        return '<div class="empty">(no diff captured)</div>'
    lines = ['<pre class="diff">']
    for line in diff_text.splitlines():
        esc = html.escape(line)
        if line.startswith("+++") or line.startswith("---"):
            cls = "diff-file"
        elif line.startswith("@@"):
            cls = "diff-hunk"
        elif line.startswith("+"):
            cls = "diff-add"
        elif line.startswith("-"):
            cls = "diff-del"
        else:
            cls = "diff-ctx"
        lines.append(f'<span class="{cls}">{esc}</span>')
    lines.append("</pre>")
    return "\n".join(lines)


def _test_pill(block):
    status = block.get("status")
    counts = block.get("counts") or {}
    passed, total = counts.get("passed", 0), counts.get("total", 0)
    failed_names = [name for name, s in (block.get("tests") or []) if s != "passed"]
    ok = status == "pass"
    cls = "pill-pass" if ok else "pill-fail"
    is_regcheck = block.get("is_regression_check")
    label = "Regression re-check" if is_regcheck else f"Iteration {block.get('iteration')}"
    text = f"{passed}/{total} passed" if total else _esc(status)
    extra = f' - FAILED: {_esc(", ".join(failed_names))}' if failed_names else ""
    return (
        f'<div class="test-pill {cls}">'
        f'<span class="pill-label">{_esc(label)}</span>'
        f'<span class="pill-result">{text}{extra}</span>'
        f'</div>'
    )


def _fix_cycle_html(block):
    outcome_text, outcome_cls = _fix_cycle_outcome(block)
    fix_text = next(
        (s.get("fix") for s in block["steps"] if s.get("action") == "agent_fix_generated"), None
    )
    diff_text = _read_patch(block)
    error_text = _error_text(block)

    badges = [f'<span class="badge {outcome_cls}">{_esc(outcome_text)}</span>']
    if block.get("repeat_failure"):
        badges.append('<span class="badge badge-repeat">same failure as last attempt, patch had no effect</span>')
    if (block.get("failure") or "").startswith("REGRESSION:"):
        badges.append('<span class="badge badge-regression">cross-stage regression fix</span>')

    parts = ['<details class="fix-cycle" open>']
    parts.append(
        f'<summary><span class="fix-id">FIX #{_esc(block.get("fix_id"))}</span> {"".join(badges)}</summary>'
    )
    parts.append('<div class="fix-body">')
    parts.append(
        '<details class="raw-failure"><summary>Test failure the agent saw</summary>'
        f'<pre class="raw">{_esc(block.get("failure"))}</pre></details>'
    )
    if fix_text:
        parts.append(f'<div class="fix-reasoning"><h4>Agent\'s FIX reasoning</h4><pre>{_esc(fix_text)}</pre></div>')
    if diff_text:
        parts.append(f'<div class="fix-patch"><h4>PATCH</h4>{_diff_html(diff_text)}</div>')
    if error_text:
        parts.append(f'<div class="fix-error"><h4>Error</h4><pre class="raw error">{_esc(error_text)}</pre></div>')
    parts.append("</div></details>")
    return "\n".join(parts)


def _stage_section_html(stage, blocks):
    parts = [f'<section class="stage"><h2>{_esc(_stage_label(stage))}</h2>']
    for b in blocks:
        if b["type"] == "test_run":
            parts.append(_test_pill(b))
        elif b["type"] == "fix_cycle":
            parts.append(_fix_cycle_html(b))
    parts.append("</section>")
    return "\n".join(parts)


def _summary_html(task_id, run_timestamp, summary, task_meta):
    """
    Just enough to orient the reader before the timeline: title, when, and
    pass/fail. Numbers (iteration counts, apply-failure rate, etc.) live in
    the metrics report now (orchestrator/reports/metrics_report.py) rather
    than being duplicated here -- this stays focused on the narrative.
    """
    result_cls = "result-pass" if summary["passed_overall"] else "result-fail"
    result_text = "ALL STAGES PASSED" if summary["passed_overall"] else "DID NOT COMPLETE"
    try:
        ts_display = datetime.strptime(run_timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        ts_display = run_timestamp

    title_extra = f': {_esc(task_meta["task_name"])}' if task_meta.get("task_name") else ""
    metrics_href = f"../metrics/{_esc(task_id)}_{_esc(run_timestamp)}_metrics.html"

    return f"""
<header class="report-header">
  <h1>{_esc(task_id)}{title_extra}</h1>
  <div class="run-meta">Run {_esc(ts_display)} - <a href="{metrics_href}">view metrics report</a></div>
  <div class="result-banner {result_cls}">{result_text}</div>
</header>
"""


CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --border: #e2e2e5;
  --card: #f7f7f8; --ok: #1a7f37; --ok-bg: #e6f4ea; --warn: #9a6700; --warn-bg: #fff3d6;
  --err: #b3261e; --err-bg: #fbe6e4; --accent: #2f5fd6; --accent-bg: #e8edfc;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16171a; --fg: #e6e6e6; --muted: #9a9ea6; --border: #2c2d31;
    --card: #1e1f23; --ok: #4fbf67; --ok-bg: #163420; --warn: #d9a441; --warn-bg: #3a2f10;
    --err: #e5695f; --err-bg: #3a1c1a; --accent: #7d9dfa; --accent-bg: #1c2440;
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); margin: 0; padding: 2rem 1.25rem 4rem;
  font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; line-height: 1.5;
}
.report-header, .setup, .stage, .report-footer { max-width: 860px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 0.15rem; }
h2 { font-size: 1.15rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; margin-top: 2.5rem; }
h4 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--muted); margin: 1rem 0 0.35rem; }
.run-meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 0.9rem; }
.result-banner {
  display: inline-block; font-weight: 600; font-size: 0.85rem; letter-spacing: 0.03em;
  padding: 0.3rem 0.7rem; border-radius: 6px; margin-bottom: 1rem;
}
.result-pass { color: var(--ok); background: var(--ok-bg); }
.result-fail { color: var(--err); background: var(--err-bg); }
.run-meta a { color: var(--accent); }
.setup ul { color: var(--muted); font-size: 0.9rem; }
code { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 0.85em; }

.test-pill {
  display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  padding: 0.5rem 0.8rem; border-radius: 6px; margin: 0.4rem 0; font-size: 0.9rem;
  border: 1px solid var(--border);
}
.pill-pass { background: var(--ok-bg); }
.pill-fail { background: var(--err-bg); }
.pill-label { font-weight: 600; }
.pill-result { color: var(--muted); text-align: right; }

.fix-cycle {
  border: 1px solid var(--border); border-radius: 8px; margin: 0.6rem 0; background: var(--card);
}
.fix-cycle summary {
  cursor: pointer; padding: 0.6rem 0.9rem; font-weight: 600; list-style: none;
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
}
.fix-cycle summary::-webkit-details-marker { display: none; }
.fix-cycle summary::before { content: "▸"; color: var(--muted); }
.fix-cycle[open] summary::before { content: "▾"; }
.fix-id { font-family: ui-monospace, Consolas, Menlo, monospace; font-weight: 600; }
.fix-body { padding: 0 0.9rem 0.9rem; }

.badge {
  font-size: 0.72rem; font-weight: 600; padding: 0.15rem 0.5rem; border-radius: 999px;
}
.outcome-ok { color: var(--ok); background: var(--ok-bg); }
.outcome-warn { color: var(--warn); background: var(--warn-bg); }
.outcome-error { color: var(--err); background: var(--err-bg); }
.badge-repeat { color: var(--warn); background: var(--warn-bg); }
.badge-regression { color: var(--accent); background: var(--accent-bg); }

.raw-failure summary { cursor: pointer; color: var(--muted); font-size: 0.85rem; margin-top: 0.5rem; }
pre {
  background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 0.7rem 0.8rem;
  overflow-x: auto; font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 0.8rem;
  white-space: pre; margin: 0.4rem 0 0;
}
pre.raw.error { color: var(--err); }
.diff span { display: block; }
.diff-add { color: var(--ok); }
.diff-del { color: var(--err); }
.diff-hunk { color: var(--accent); }
.diff-file { color: var(--muted); font-weight: 600; }
.diff-ctx { color: var(--fg); }
.empty { color: var(--muted); font-size: 0.85rem; }

.report-footer { color: var(--muted); font-size: 0.75rem; margin-top: 3rem; border-top: 1px solid var(--border); padding-top: 0.75rem; }
"""


def render_html(task_id, run_timestamp, setup_blocks, stage_groups, summary, task_meta):
    setup_html = ""
    if setup_blocks:
        items = "".join(
            f'<li>{_esc(_stage_label(b["stage"]))} tests written to <code>{_esc(b.get("test_path", ""))}</code></li>'
            for b in setup_blocks
        )
        setup_html = f'<section class="setup"><h2>Setup</h2><ul>{items}</ul></section>'

    stage_html = "\n".join(_stage_section_html(stage, blocks) for stage, blocks in stage_groups.items())

    metrics_href = f"../metrics/{_esc(task_id)}_{_esc(run_timestamp)}_metrics.html"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>qikly report - {_esc(task_id)} - {_esc(run_timestamp)}</title>
<style>{CSS}</style>
</head>
<body>
{_summary_html(task_id, run_timestamp, summary, task_meta)}
{setup_html}
{stage_html}
<footer class="report-footer">Generated by orchestrator/reports/report.py from outputs/logs/transactions_{_esc(task_id)}_{_esc(run_timestamp)}.jsonl. Numbers-first view: <a href="{metrics_href}">{_esc(task_id)}_{_esc(run_timestamp)}_metrics.html</a></footer>
</body>
</html>
"""


def generate_report(task_id, run_timestamp=None):
    """
    Build the HTML report for one task's run and write it to
    outputs/reports/iterations/<task_id>_<run_timestamp>_report.html.
    Defaults to that task's most recent run when run_timestamp is omitted.
    Returns the written path.
    """
    if run_timestamp is None:
        path = _latest_transactions_path(task_id)
        run_timestamp = _run_timestamp_from_path(task_id, path)
    else:
        path = os.path.join(LOG_DIR, f"transactions_{task_id}_{run_timestamp}.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No transaction log at {path}")

    events = load_events(path)
    blocks = build_blocks(events)
    setup_blocks = [b for b in blocks if b["type"] == "tests_generated"]
    stage_groups = group_by_stage(blocks)
    summary = compute_summary(blocks)
    task_meta = _load_task_meta(task_id)

    html_doc = render_html(task_id, run_timestamp, setup_blocks, stage_groups, summary, task_meta)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out_path = os.path.join(REPORT_DIR, f"{task_id}_{run_timestamp}_report.html")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_doc)
    return out_path


def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate an HTML debugging-timeline report from a V&V run's transaction log."
    )
    parser.add_argument("--task", default=None, help="task_id (default: every task under inputs/config/tasks/)")
    parser.add_argument("--run", default=None, help="run_timestamp to report on (default: that task's latest run)")
    return parser.parse_args()


def main():
    from qikly.orchestrator.orchestrator import discover_task_ids

    args = _parse_args()
    task_ids = [args.task] if args.task else discover_task_ids()
    for task_id in task_ids:
        try:
            path = generate_report(task_id, run_timestamp=args.run)
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
