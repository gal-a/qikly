"""
A run, summarised as markdown for a pull request comment.

The GitHub Action already runs a task and keeps the artifacts. An artifact is
a zip file someone has to notice, download and open, which in practice means
nobody reads it. A comment is read because it arrives where the conversation
already is.

## What goes in it, and what deliberately does not

**The blocking tests, by name.** The single most useful line in a failed run.
Someone reading a PR wants "which rule is not satisfied", and the test name is
the closest thing to that which fits in a comment.

**Whether it converged, and at which stage it stopped.** Two facts, at the top,
readable without expanding anything.

**A link to the artifacts for everything else.** The full timeline, the
metrics, every FIX and PATCH. Reproducing any of that in a comment would make
it unreadable and it is already generated.

**Not the cost.** It is in the run summary and putting a dollar figure in a
public PR comment on every push is a way to start an argument that has nothing
to do with the code.

**Not a pass/fail verdict on the pull request.** The comment reports; the
workflow decides whether to fail. Those are separate on purpose, because a
stall is a normal outcome and a tool whose first act is failing someone's build
does not get a second look.
"""
import glob
import json
import os

RUN_SUMMARY_DIR = "outputs/reports/run_summary"


def latest_runs(summary_dir=None, task_ids=None):
    """
    The most recent summary per task.

    One per task rather than everything on disk, because a PR comment describes
    what this workflow run just did, and a repository that has been running for
    months would otherwise produce a comment nobody could scroll.
    """
    directory = summary_dir or RUN_SUMMARY_DIR
    best = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        task_id = payload.get("task_id")
        if not task_id or (task_ids and task_id not in task_ids):
            continue
        stamp = payload.get("run_timestamp") or ""
        if task_id not in best or stamp > (best[task_id].get("run_timestamp") or ""):
            best[task_id] = payload
    return [best[k] for k in sorted(best)]


def _blocking(payload):
    """The stage a run stopped in, and how far it got."""
    stages = payload.get("stage_iterations") or {}
    if payload.get("passed_overall"):
        return None, sum(stages.values())
    # The last stage with any iterations is where it ran out of budget.
    order = [s for s in ("integration", "system", "unit") if stages.get(s)]
    return (order[-1] if order else "unknown"), sum(stages.values())


def render(payloads, artifacts_url=None):
    """The comment body. Markdown, and safe to post verbatim."""
    if not payloads:
        return ("### qikly\n\nNo run summary was produced, so there is nothing "
                "to report. The console log in the artifacts says why.")

    converged = [p for p in payloads if p.get("passed_overall")]
    lines = ["### qikly", ""]

    if len(payloads) == 1:
        payload = payloads[0]
        task_id = payload.get("task_id", "?")
        stage, iterations = _blocking(payload)
        if stage is None:
            lines.append(f"**{task_id} converged.** Every generated test passes, "
                         f"unit included, after {iterations} iteration(s).")
        else:
            lines.append(f"**{task_id} did not fully converge**, stopping in the "
                         f"`{stage}` stage after {iterations} iteration(s).")
            lines.append("")
            lines.append("That is a normal outcome rather than a broken build. "
                         "The generated suite is still worth reading: it is the "
                         "standard the code was held to.")
    else:
        lines.append(f"**{len(converged)} of {len(payloads)} task(s) converged.**")
        lines.append("")
        lines.append("| Task | Result | Iterations |")
        lines.append("|---|---|---|")
        for payload in payloads:
            stage, iterations = _blocking(payload)
            result = "converged" if stage is None else f"stopped in `{stage}`"
            lines.append(f"| `{payload.get('task_id','?')}` | {result} | {iterations} |")

    prov = (payloads[0].get("provenance") or {})
    model = prov.get("model")
    if model:
        lines.append("")
        lines.append(f"<sub>{model}, criteria_per_batch "
                     f"{prov.get('criteria_per_batch')}, qikly "
                     f"{prov.get('qikly_version', '?')}. A convergence result "
                     f"belongs to a model and a configuration as much as to a "
                     f"tool.</sub>")

    if artifacts_url:
        lines.append("")
        lines.append(f"[Full timeline, metrics and every patch]({artifacts_url})")

    return "\n".join(lines)
