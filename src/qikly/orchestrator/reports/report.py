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


from qikly.code_identity import describe

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
        elif action == "criteria_independence":
            blocks.append({"type": "criteria_independence", **e})
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
    # Seeded runs log one of these at the start. Carried through the summary
    # rather than passed as its own argument so that every consumer of a run
    # (this report, the metrics report, run_summary.py's JSON) picks it up
    # without a signature change.
    independence = next(
        (b for b in blocks if b["type"] == "criteria_independence"), None)
    if independence is not None:
        independence = {k: v for k, v in independence.items()
                        if k not in ("type", "action", "ts")}
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
        "criteria_independence": independence,
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

    # Only a seeded run carries this. A run that wrote its own implementation
    # says nothing here, because for those the separation is enforced rather
    # than evidenced and a note claiming it would be noise.
    evidence = summary.get("criteria_independence") or {}
    independence_html = ""
    if evidence.get("detail"):
        cls = "evidence-ok" if evidence.get("verdict") == "criteria_first" else "evidence-open"
        limit = evidence.get("limit")
        limit_html = f'<div class="evidence-limit">{_esc(limit)}</div>' if limit else ""
        independence_html = (
            f'\n  <div class="independence {cls}"><b>{_esc(evidence.get("headline"))}</b>: '
            f'{_esc(evidence.get("detail"))}{limit_html}</div>'
        )

    return f"""
<header class="report-header">
  <h1>{_esc(task_id)}{title_extra}</h1>
  <div class="run-meta">Run {_esc(ts_display)} - {_esc(describe())} - <a href="{metrics_href}">view metrics report</a></div>
  <div class="result-banner {result_cls}">{result_text}</div>{independence_html}
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
.coverage { margin: 22px 0; }
.cov-lead, .cov-notes { color: var(--muted); margin: 4px 0 10px; }
.cov-notes { color: var(--warn); }
.cov-table { border-collapse: collapse; width: 100%; }
.cov-table th, .cov-table td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
.cov-table th { color: var(--muted); font-weight: 600; }
.cov-n, .cov-c { width: 1%; white-space: nowrap; text-align: right; font-variant-numeric: tabular-nums; }
.cov-ok .cov-c { color: var(--ok); }
.cov-none { background: var(--warn-bg); }
.cov-none .cov-c { color: var(--warn); font-weight: 700; }
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
.independence {
  font-size: 0.85rem; padding: 0.45rem 0.7rem; border-radius: 6px;
  border: 1px solid var(--border); margin: 0.2rem 0 1rem; max-width: 860px;
}
.evidence-ok { color: var(--ok); background: var(--ok-bg); }
.evidence-open { color: var(--warn); background: var(--warn-bg); }
.evidence-limit { color: var(--muted); margin-top: 0.35rem; }
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


def _coverage_section_html(task_id):
    """
    Which acceptance criterion each generated test says it came from.

    Read from the suites on disk rather than from the transaction log,
    because the log records what the run did and this describes what it
    produced. Self-reported by test generation, so it shows intent rather
    than proof, and the section says so rather than letting a reader take a
    green row as coverage.

    Never raises, and the whole body sits inside the guard rather than only
    the call that looked risky. An earlier version wrapped just `trace()` and
    left the row building outside, so a result missing a key, or a task whose
    acceptance_criteria hold a non-string, raised from here and cost the
    caller the entire HTML report rather than this one section. Found in
    review, 2026-09-17.
    """
    try:
        return _coverage_rows_html(task_id)
    except Exception:
        return ""


def _coverage_rows_html(task_id):
    """The section itself. Only ever called from inside the guard above."""
    from qikly.orchestrator.orchestrator import GENERATED_TESTS_ROOT
    from qikly.orchestrator.tuning.trace_criteria import trace

    result = trace(task_id, os.path.join(GENERATED_TESTS_ROOT, task_id))
    if not result or not result.get("criteria_count"):
        return ""

    rows = []
    for index, text in enumerate(result.get("criteria") or [], start=1):
        count = result["per_criterion"].get(index, 0)
        cls = "cov-none" if not count else "cov-ok"
        rows.append(
            f'<tr class="{cls}"><td class="cov-n">{index}</td>'
            f'<td class="cov-c">{count}</td><td>{_esc(str(text))}</td></tr>')

    notes = []
    if result.get("uncovered"):
        notes.append("%d criteri%s named by no test" % (
            len(result["uncovered"]), "on" if len(result["uncovered"]) == 1 else "a"))
    if result.get("tests_untraced"):
        notes.append("%d test(s) carry no criterion label" % len(result["tests_untraced"]))
    if result.get("tests_requirements_only"):
        notes.append("%d written from the requirements rather than a criterion"
                     % len(result["tests_requirements_only"]))
    if result.get("out_of_range"):
        notes.append("%d test(s) name a criterion that does not exist"
                     % len(result["out_of_range"]))
    if result.get("tests_ambiguous"):
        notes.append("%d label(s) could mean two things and were not read"
                     % len(result["tests_ambiguous"]))
    if result.get("tests_outside_supported_shape"):
        notes.append("%d test(s) sit in a class or another function and are missing "
                     "from these counts" % len(result["tests_outside_supported_shape"]))
    notes_html = (f'<p class="cov-notes">{_esc("; ".join(notes))}</p>' if notes else "")

    return f"""<section class="coverage"><h2>Criteria coverage</h2>
<p class="cov-lead">{result["tests_traced"]} of {result["tests_total"]} generated tests name the criteria they were written from. Self-reported by test generation, so this shows what it set out to cover, not what it achieved.</p>
{notes_html}
<table class="cov-table"><thead><tr><th>#</th><th>Tests</th><th>Acceptance criterion</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>"""


def _final_counts(stage_groups):
    """
    How many tests each stage ended up running, from its last real run.

    The last rather than the first: a stage's suite can be rewritten mid-run
    by the suite check, and the number a reader wants is the one the verdict
    was reached on. Regression re-checks are skipped, since those re-run an
    earlier stage and would otherwise overwrite that stage's own total.
    """
    totals = {}
    for stage, blocks in stage_groups.items():
        for b in blocks:
            if b["type"] != "test_run" or b.get("is_regression_check"):
                continue
            total = (b.get("counts") or {}).get("total")
            if total:
                totals[stage] = total
    return totals


def _setup_section_html(setup_blocks, stage_groups):
    """
    What was generated, and how much of it.

    This was three file paths, which answers "where", the least interesting
    question a reader has here. The count is what makes the next section
    legible, because criteria coverage is a proportion of it.
    """
    if not setup_blocks:
        return ""
    totals = _final_counts(stage_groups)
    rows = []
    for b in setup_blocks:
        count = totals.get(b["stage"])
        rows.append(
            '<tr><td>%s</td><td class="cov-n">%s</td><td><code>%s</code></td></tr>'
            % (_esc(_stage_label(b["stage"])),
               _esc(str(count)) if count else "&mdash;",
               _esc(b.get("test_path", ""))))
    return (
        '<section class="setup"><h2>Generated test suites</h2>'
        '<p class="cov-lead">None of these were written by hand. Counts are the '
        'tests each suite ran on its final attempt.</p>'
        '<table class="cov-table"><thead><tr><th>Suite</th><th>Tests</th>'
        '<th>Written to</th></tr></thead><tbody>%s</tbody>'
        '<tfoot><tr><td><b>Total</b></td><td class="cov-n"><b>%d</b></td>'
        '<td></td></tr></tfoot></table></section>'
        % ("".join(rows), sum(totals.values())))


def _sequence_section_html(stage_groups):
    """
    The run at a glance, before the iteration-by-iteration detail.

    That detail is long, and without a summary above it the bootstrap reads
    as the integration stage repeating itself. This says what actually
    happened in one table, and names the thing that makes the shape make
    sense: there is no separate step that writes the implementation.
    """
    if not stage_groups:
        return ""
    rows = []
    for stage, blocks in stage_groups.items():
        runs = [b for b in blocks
                if b["type"] == "test_run" and not b.get("is_regression_check")]
        repairs = sum(1 for b in blocks if b["type"] == "fix_cycle")
        last = runs[-1] if runs else None
        counts = (last.get("counts") or {}) if last else {}
        if last and last.get("status") == "pass":
            outcome, cls = "passed", "pill-pass"
        elif last:
            outcome = "%d of %d passed" % (counts.get("passed", 0), counts.get("total", 0))
            cls = "pill-fail"
        else:
            outcome, cls = "nothing ran", "pill-fail"
        rows.append(
            '<tr><td>%s</td><td class="cov-n">%d</td><td class="cov-n">%d</td>'
            '<td><span class="%s">%s</span></td></tr>'
            % (_esc(_stage_label(stage)), len(runs), repairs, cls, _esc(outcome)))
    return (
        '<section class="sequence"><h2>How the run went</h2>'
        '<p class="cov-lead">Each stage runs its suite, and every failure produces '
        'a FIX, which is reasoning, and then a PATCH, which is a diff. There is no '
        'separate step anywhere that writes the first implementation. The bootstrap '
        'below runs the integration suite against an empty source tree on purpose, '
        'and the import error that raises goes through the same FIX and PATCH cycle '
        'to create the code. The first line written and every later repair arrive '
        'the same way, which is why the bootstrap is not the integration stage '
        'repeating itself.</p>'
        '<table class="cov-table"><thead><tr><th>Stage</th><th>Suite runs</th>'
        '<th>Repairs</th><th>Ended</th></tr></thead><tbody>%s</tbody></table>'
        '</section>' % "".join(rows))


def render_html(task_id, run_timestamp, setup_blocks, stage_groups, summary, task_meta):
    setup_html = _setup_section_html(setup_blocks, stage_groups)
    sequence_html = _sequence_section_html(stage_groups)

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
{_coverage_section_html(task_id)}
{sequence_html}
<section class="detail-head"><h2>Every attempt, in order</h2>
<p class="cov-lead">The same run again, iteration by iteration: what ran, what failed, and the reasoning and the diff behind each repair.</p></section>
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
    parser.add_argument("--task", default=None, help="task_id (default: every task under config/tasks/ (yours in inputs_private/, plus the bundled ones))")
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
