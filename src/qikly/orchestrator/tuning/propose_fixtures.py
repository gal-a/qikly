"""
Fixture rows for criteria that nothing can currently trigger.

A criterion no input row reaches produces a test that passes whatever the code
does. In this project's own measurements roughly two thirds of deliberately
planted faults were caught by neither arm for exactly that reason: the bar was
not wrong, it was unmeasurable. Adding rows by hand afterwards barely helped,
because the suites had already been generated against the original data.

So this asks a separate agent which criteria are unreachable and what row
would reach each one, and **writes the answer to a proposal file**. It never
edits a fixture.

## Why a proposal file and not the fixtures

Two reasons, and neither is about the model being untrustworthy.

A row is harder to review than a criterion. `TXN-1099,1e2,2026-01-05` is only
right or wrong relative to the criterion it was proposed for, so it has to be
read next to that criterion, which is how the file below is laid out.

And a fixture set that grows in whatever direction a model finds interesting
stops resembling the data you actually process. Every convergence rate
measured on it then describes a world that does not exist, and the drift is
invisible in any single row. Appending by hand keeps that decision yours, and
the file reports how much of your data came from a machine so the drift is
visible in aggregate.

    python -m qikly.orchestrator.tuning.propose_fixtures --tasks MERGE_STOCK

Writes outputs/reports/fixture_proposals/<task>_<timestamp>.md. Nothing else
changes.
"""
import argparse
import os
import sys
from datetime import datetime

import yaml

from qikly.agent_api.agent_interface import agent_propose_fixture_rows, task_config_path
from qikly.paths import chdir_to_project_root

OUT_DIR = "outputs/reports/fixture_proposals"

# A cap per round, because the failure mode here is volume rather than any one
# bad row: a loop left running appends until the fixtures are mostly machine
# written, and every individual row looks reasonable on the way.
MAX_PROPOSALS = 8


def _criteria(task_id):
    with open(task_config_path(task_id), encoding="utf-8") as handle:
        return (yaml.safe_load(handle) or {}).get("acceptance_criteria") or []


ACCEPTED_FILE = ".accepted_proposals"


def _machine_share(task_id):
    """
    How much of this task's fixture data came from a proposal.

    Recorded in a sidecar file next to the data, one accepted row per line,
    NOT as a marker inside the row. An inline comment would land inside a
    field: `TXN-1012,0.00,2026-01-10  # proposed` parses with a date of
    "2026-01-10  # proposed", so the convention that was supposed to keep the
    count honest would have silently corrupted the fixture it counted.

    A sidecar also works for JSON and JSONL inputs, which have nowhere to put
    a trailing comment at all.
    """
    try:
        with open(task_config_path(task_id), encoding="utf-8") as handle:
            paths = (yaml.safe_load(handle) or {}).get("inputs") or []
    except (OSError, yaml.YAMLError):
        # A share that cannot be computed is a missing line in the report, not
        # a reason to fail: the proposals themselves are the point, and this
        # is the one part of the file that reads other files.
        return 0, 0

    accepted = set()
    for directory in {os.path.dirname(p) for p in paths}:
        try:
            with open(os.path.join(directory, ACCEPTED_FILE),
                      encoding="utf-8") as handle:
                accepted |= {l.strip() for l in handle if l.strip()}
        except OSError:
            pass

    total = machine = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                rows = [r.strip() for r in handle.read().splitlines()[1:] if r.strip()]
        except OSError:
            continue
        total += len(rows)
        machine += sum(1 for r in rows if r in accepted)
    return machine, total


def render(task_id, criteria, proposals):
    """The proposal file: each row directly under the criterion it is for."""
    machine, total = _machine_share(task_id)
    lines = [
        f"# Fixture proposals for {task_id}",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        "Nothing here has been applied.",
        "",
        "A criterion no row can trigger produces a test that passes whatever the",
        "code does. Each proposal below names the criterion it exists to make",
        "reachable, so you can judge the row against the rule rather than on its",
        "own.",
        "",
        f"This task declares **{len(criteria)} criteria**, numbered 1 to "
        f"{len(criteria)} in the order they appear in the task file. Only the "
        "unreachable ones get a section below, so the numbers skip; every "
        "criterion not shown is listed as already reachable at the end, and "
        "the two together account for all of them.",
        "",
        "**To accept one:** paste the row into the named file, and add the same",
        f"line to `{ACCEPTED_FILE}` in that directory so the share below stays",
        "honest. **To reject one:** do nothing.",
        "",
    ]
    if total:
        lines += [f"Your fixtures are currently **{machine} of {total} rows** "
                  f"machine-proposed ({100 * machine / total:.0f}%). Data that "
                  "drifts toward whatever a model finds interesting stops "
                  "describing what you actually process.", ""]

    unreachable = [p for p in proposals if not p.get("covered")]
    covered = [p for p in proposals if p.get("covered")]

    if not unreachable:
        lines += ["Nothing to propose: every criterion already has data that "
                  "reaches it.", ""]
    for p in unreachable[:MAX_PROPOSALS]:
        i = p["criterion"]
        lines += [
            f"## Criterion {i}",
            "",
            f"> {criteria[i - 1] if i <= len(criteria) else '(out of range)'}",
            "",
            f"Add to `{p['file']}`:",
            "",
            "```",
            f"{p['row']}",
            "```",
            "",
            f"Expected: {p['outcome']}",
            "",
        ]
    if len(unreachable) > MAX_PROPOSALS:
        lines += [f"{len(unreachable) - MAX_PROPOSALS} further proposal(s) were "
                  f"withheld: {MAX_PROPOSALS} is the cap for one round, so the "
                  "fixtures cannot be rewritten in a single sitting.", ""]
    if covered:
        lines += ["## Already reachable", "",
                  "No row needed for criteria: "
                  + ", ".join(str(p["criterion"]) for p in sorted(
                      covered, key=lambda x: x["criterion"])), ""]
    return "\n".join(lines)


def propose(task_id, seed=None):
    criteria = _criteria(task_id)
    if not criteria:
        print(f"[{task_id}] no acceptance_criteria to check.")
        return None
    proposals = agent_propose_fixture_rows(task_id, criteria, seed=seed)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(
        OUT_DIR, f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(task_id, criteria, proposals))
    unreachable = sum(1 for p in proposals if not p.get("covered"))
    print(f"[{task_id}] {unreachable} of {len(criteria)} criteria have no data "
          f"that reaches them. Proposals written to {path}, and nothing else "
          f"was changed.")
    return path


def main():
    from qikly.console import use_utf8

    use_utf8()

    chdir_to_project_root()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--tasks", help="Comma separated task_ids (default: all)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    from qikly.orchestrator.orchestrator import discover_task_ids
    ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_task_ids()
    for task_id in ids:
        try:
            propose(task_id, seed=args.seed)
        except Exception as e:
            print(f"[{task_id}] failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
