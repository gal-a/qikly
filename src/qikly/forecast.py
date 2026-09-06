"""
What a run will probably cost, said before it starts rather than after.

qikly already reports what a run spent. That is the wrong end of the
transaction. The moment someone hesitates is the moment before they press
enter on a command that will call a paid API an unknown number of times, and
"about $0.007" afterwards does not help with the decision they were making.

Every agent tool that spends money on your behalf now shows a projection first,
and the ones that do not are the ones people run once on a demo task and never
point at anything real.

## Where the number comes from

Your own history, when you have any. Every run writes a summary carrying its
model call count and token totals, so a forecast is the median of what
comparable runs on this machine actually did. The median rather than the mean,
because a run that stalls and burns its whole budget is the long tail, and a
mean lets one of those dominate an estimate meant to describe the typical case.

With no history the estimate falls back to the shipped defaults, measured over
this project's own sweeps. That is a worse estimate and it is labelled as one.

## What it deliberately does not do

It does not block, and it does not ask for confirmation. A forecast that
interrupts every invocation becomes a keypress people learn to hit without
reading, at which point it has trained exactly the reflex it was meant to
prevent. `QIKLY_MAX_CALLS` already exists for a hard stop, and that is the
mechanism for people who want one.

It is also an estimate and says so every time. A convergence run is a loop with
a variable trip count, and a projection presented as a price would be a lie
with a decimal point on it.
"""
import glob
import json
import os
import statistics

# What a task costs when there is no local history to read. From this project's
# own measured sweeps on gemini-3.5-flash-lite: roughly 20 model calls and
# 80k in / 25k out tokens for a task that converges, more when it stalls.
DEFAULT_CALLS = 20
DEFAULT_TOKENS_IN = 80_000
DEFAULT_TOKENS_OUT = 25_000

RUN_SUMMARY_DIR = "outputs/reports/run_summary"
USAGE_DIR = "outputs/reports/usage"


def _history(task_id=None, limit=40):
    """
    Per-run (calls, tokens_in, tokens_out) from usage records on this machine.

    Scoped to the task when there is enough of it, because tasks differ by more
    than noise: the cheapest of this project's own tasks costs a third of what
    the dearest one does, and a pooled figure would misprice both.
    """
    records = []
    pattern = f"{task_id}_*.json" if task_id else "*.json"
    for path in sorted(glob.glob(os.path.join(USAGE_DIR, pattern)))[-limit:]:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        calls = data.get("calls")
        if not calls:
            continue
        # The writer's field names, not guessed ones. A forecast reading keys
        # that do not exist would silently fall back to shipped defaults
        # forever while looking like it had learned from your history.
        records.append((calls,
                        data.get("input_tokens") or 0,
                        data.get("output_tokens") or 0))
    return records


def estimate(task_ids, model, repeat=1):
    """
    A projection for this invocation.

    Returns a dict rather than a string so the same numbers can go into --json
    without being parsed back out of prose.
    """
    from qikly.agent_api.usage import PRICES

    per_task = []
    grounded = 0
    for task_id in task_ids:
        records = _history(task_id) or _history()
        if len(records) >= 3:
            grounded += 1
            calls = statistics.median(r[0] for r in records)
            tin = statistics.median(r[1] for r in records)
            tout = statistics.median(r[2] for r in records)
        else:
            calls, tin, tout = DEFAULT_CALLS, DEFAULT_TOKENS_IN, DEFAULT_TOKENS_OUT
        per_task.append((task_id, calls, tin, tout))

    calls = sum(p[1] for p in per_task) * repeat
    tokens_in = sum(p[2] for p in per_task) * repeat
    tokens_out = sum(p[3] for p in per_task) * repeat

    rate_in, rate_out = PRICES.get(model, (None, None))
    cost = None
    if rate_in is not None:
        cost = (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000

    return {
        "tasks": len(task_ids),
        "repeat": repeat,
        "model": model,
        "calls": int(round(calls)),
        "tokens_in": int(round(tokens_in)),
        "tokens_out": int(round(tokens_out)),
        "cost_usd": round(cost, 4) if cost is not None else None,
        # Says which of the two estimates this is, because they are not equally
        # good and a reader deserves to know which one they were handed.
        "basis": ("your own runs" if grounded == len(task_ids) and task_ids
                  else "shipped defaults" if grounded == 0
                  else "part history, part shipped defaults"),
        "priced": rate_in is not None,
    }


def render(projection):
    """One block, printed before the run starts."""
    lines = []
    scope = f"{projection['tasks']} task(s)"
    if projection["repeat"] > 1:
        scope += f" x {projection['repeat']} repetitions"
    lines.append(f"Estimated for {scope} on {projection['model']}:")
    lines.append(
        f"  about {projection['calls']:,} model call(s), "
        f"{projection['tokens_in']:,} in / {projection['tokens_out']:,} out tokens"
    )
    if projection["cost_usd"] is not None:
        lines.append(f"  about ${projection['cost_usd']:.2f}, "
                     f"from a static price table rather than your bill")
    else:
        lines.append(f"  no price on file for {projection['model']}, so no cost estimate")
    lines.append(f"  based on {projection['basis']}. A run is a loop with a "
                 f"variable trip count, so this is a projection, not a quote.")
    return "\n".join(lines)
