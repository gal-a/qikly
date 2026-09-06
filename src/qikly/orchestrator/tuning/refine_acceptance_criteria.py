import sys
"""
Iteratively refines auto-generated acceptance_criteria by actually running
convergence against them and asking the model to adversarially review the
resulting real implementation for gaps a naive-but-plausible implementation
could still get away with (see
inputs/agent_defs/acceptance_criteria_review_prompt.md). This mirrors the
real, iterative human-tuning history behind ETL_ADDRESS/ETL_EMAIL's actual
acceptance_criteria far more closely than the one-shot MVP
(orchestrator/tuning/gen_and_eval_acceptance_criteria.py) can -- one-shot generation
only has the spec text to reason from; this loop gets to react to a real
implementation choice each round.

Each round runs a full convergence (orchestrator.orchestrate(), unchanged,
as a black box) against a scratch task file
(inputs/config/tasks/<task_id>_DRAFT.yaml), rewritten so its own generated
code and output live under <task_id>_DRAFT's directories -- never the real
task's outputs/agent_src/code/<task_id>/ or outputs/data/<task_id>/ -- while
still reading the real task's input fixtures unchanged (those paths are
read-only). The scratch file is always deleted when the round ends, success
or failure -- it must never linger and get picked up by discover_task_ids().

One of --task or --all is REQUIRED (unlike gen_and_eval_acceptance_criteria.py's
default-to-all): each round is a full multi-iteration convergence run, not
a single cheap LLM call, so running this against every task must be an
explicit choice, never an implicit default. Comma-separated task_ids ARE
accepted for --task -- that's still an explicit, bounded list; each one
just runs sequentially and gets its own section in the log (or its own log
entirely, see main()). --all runs every task discover_task_ids() finds
(minus any stray *_DRAFT leftovers) -- same sequential execution, just a
longer list; it does not change how any individual task is refined.

    python -m orchestrator.tuning.refine_acceptance_criteria --task ETL_ADDRESS
    python -m orchestrator.tuning.refine_acceptance_criteria --task ETL_ADDRESS --rounds 5 --seed 0
    python -m orchestrator.tuning.refine_acceptance_criteria --task CALC_TAX,CALC_DISCOUNT
    python -m orchestrator.tuning.refine_acceptance_criteria --all --rounds 2
"""
import argparse
import os
from datetime import datetime

import yaml

from qikly.paths import chdir_to_project_root, private_input_path

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/reports/acceptance_criteria"
DEFAULT_ROUNDS = 3


def _out(f, line=""):
    print(line)
    f.write(line + "\n")


def _draft_task_id(task_id):
    return f"{task_id}_DRAFT"


def _write_draft_task(task_id, criteria):
    """
    Rewrites the real task file as text (not a yaml parse/dump round-trip,
    which would lose comments and reflow the multi-line requirement
    strings) -- substituting every literal occurrence of this task's own
    generated-code paths (outputs.agent_src.code.<task_id>. and
    outputs/data/<task_id>/) for the draft's, so this round's coding agent
    writes to outputs/agent_src/code/<task_id>_DRAFT/ and
    outputs/data/<task_id>_DRAFT/ -- never the real task's own directories.
    inputs_private/data/<task_id>/ is deliberately left untouched: those fixtures
    are read-only and reusing them is the point. Replaces the
    acceptance_criteria: section with the criteria accumulated so far.
    """
    from qikly.agent_api.agent_interface import task_config_path, _ACCEPTANCE_CRITERIA_RE, _format_criteria_block

    draft_id = _draft_task_id(task_id)
    with open(task_config_path(task_id), encoding="utf-8") as fh:
        text = fh.read()

    text = text.replace(f'task_id: "{task_id}"', f'task_id: "{draft_id}"')
    text = text.replace(f"outputs/data/{task_id}/", f"outputs/data/{draft_id}/")
    text = text.replace(f"outputs.agent_src.code.{task_id}.", f"outputs.agent_src.code.{draft_id}.")

    criteria_block = _format_criteria_block(criteria)
    text = _ACCEPTANCE_CRITERIA_RE.sub(lambda m: criteria_block, text.rstrip() + "\n")

    # Scratch DRAFT task, written into inputs_private/ rather than wherever
    # the source task resolved from -- that may be inside the installed
    # package. See paths.private_input_path().
    draft_path = private_input_path(f"config/tasks/{draft_id}.yaml")
    with open(draft_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return draft_path


def refine(task_id, rounds, f, seed=None):
    from qikly.agent_api.agent_interface import (
        agent_generate_acceptance_criteria,
        agent_generate_acceptance_criteria_review,
        agent_src_code_path,
    )
    from qikly.agent_api.code_loader.code_loader import load_codebase
    from qikly.orchestrator.orchestrator import criteria_batching_disabled, orchestrate

    draft_id = _draft_task_id(task_id)
    criteria = agent_generate_acceptance_criteria(task_id, seed=seed)
    _out(f, f"=== {task_id}: round 0 (initial one-shot) -- {len(criteria)} criteria ===")
    for c in criteria:
        _out(f, f"  - {c}")

    category_totals = {}

    for round_num in range(1, rounds + 1):
        draft_path = _write_draft_task(task_id, criteria)
        try:
            _out(f, f"\n--- round {round_num}: converging against {len(criteria)} criteria ---")
            try:
                # This convergence exists only to produce an implementation
                # for the reviewer to read. The suite that gets it there is
                # discarded, so paying for a batched one buys nothing and
                # costs the round: with batching on, these convergences failed
                # often enough that refinement returned no new criteria on 14
                # of 24 attempts, against 3 of 16 with it off.
                with criteria_batching_disabled():
                    orchestrate(draft_id, seed=seed)
            except RuntimeError as e:
                _out(f, f"  convergence failed: {e}")
                _out(f, "  stopping refinement -- can't review an implementation that never converged")
                break

            implementation_code = load_codebase(agent_src_code_path(draft_id))
            new_findings = agent_generate_acceptance_criteria_review(
                task_id, criteria, implementation_code, seed=seed
            )
        finally:
            if os.path.exists(draft_path):
                os.remove(draft_path)

        if not new_findings:
            _out(f, f"  round {round_num}: no new gaps found -- stopping")
            break

        _out(f, f"  round {round_num}: {len(new_findings)} new criteria found:")
        round_counts = {}
        for category, text in new_findings:
            _out(f, f"    - [{category}] {text}")
            round_counts[category] = round_counts.get(category, 0) + 1
            category_totals[category] = category_totals.get(category, 0) + 1
        _out(f, "    categories this round: " + ", ".join(
            f"{cat}={n}" for cat, n in sorted(round_counts.items())
        ))
        criteria = criteria + [text for _category, text in new_findings]
    else:
        _out(f, f"\nReached round limit ({rounds}) without the model reporting a clean pass")

    if category_totals:
        _out(f, f"\n=== {task_id}: findings by category (all rounds) ===")
        for cat, n in sorted(category_totals.items(), key=lambda kv: -kv[1]):
            _out(f, f"  {cat}: {n}")

    return criteria, category_totals


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Iteratively refine auto-generated acceptance criteria by actually converging against them."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--task", default=None,
        help="Comma-separated task_id(s), e.g. ETL_ADDRESS or ETL_ADDRESS,ETL_EMAIL"
    )
    group.add_argument(
        "--all", action="store_true",
        help="Run against every task discovered under inputs/config/tasks/. Explicit "
             "opt-in only -- there is no implicit default-to-all, since each task is "
             "--rounds full multi-iteration convergence runs, not a single cheap call."
    )
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


def main():
    from qikly.agent_api.agent_interface import task_config_path, task_type

    args = _parse_args()
    if args.all:
        from qikly.orchestrator.orchestrator import discover_task_ids
        # Defensive filter: a *_DRAFT.yaml should never linger (see
        # _write_draft_task's finally-block cleanup), but --all iterates
        # over whatever's discovered rather than a hand-typed list, so an
        # interrupted prior run's leftover scratch file won't silently get
        # treated as a real task to refine.
        task_ids = [t for t in discover_task_ids() if not t.endswith("_DRAFT")]
    else:
        task_ids = [t.strip() for t in args.task.split(",")]
    task_ids = [t for t in task_ids if t]

    # Each round runs under a "<task_id>_DRAFT" task_id, not the real one
    # (see _write_draft_task) -- so orchestrator/live_view.py watching the
    # real task_ids will never see any of this activity; the transactions
    # logs it's tailing simply never get written under those names. Print
    # the actual command up front rather than let that be a silent,
    # confusing "nothing's happening" watch session.
    draft_ids = [_draft_task_id(t) for t in task_ids]
    print(
        f"To watch this live in a second terminal:\n"
        f"  python -m orchestrator.live_view --tasks {','.join(draft_ids)}\n"
        f"(each task converges under its own _DRAFT task_id, one at a time -- "
        f"other rows will show \"not started\" until it's their turn)\n"
    )

    os.makedirs(LOG_DIR, exist_ok=True)
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Single task keeps the original <task_id>-in-the-filename convention;
    # multiple explicit tasks share one combined log, same as
    # gen_and_eval_acceptance_criteria.py's multi-task naming.
    if len(task_ids) == 1:
        log_path = os.path.join(LOG_DIR, f"refine_{task_ids[0]}_{run_timestamp}.txt")
    else:
        log_path = os.path.join(LOG_DIR, f"refine_{run_timestamp}.txt")

    # {task_type: {category: count}}, accumulated across every task in this
    # run -- lets a multi-task (--task a,b,c or --all) run show which kinds
    # of gaps recur within a domain family, not just per individual task.
    by_task_type = {}

    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        for i, task_id in enumerate(task_ids):
            if i > 0:
                _out(f)
            try:
                final_criteria, category_totals = refine(task_id, args.rounds, f, seed=args.seed)
            except Exception as e:
                # A crash on one task (e.g. generated tests failing syntax
                # validation twice in a row -- see orchestrator.py's
                # generate_and_write_tests) must not abort every other
                # task's sweep. Mirrors run_all.py's "a stage failing
                # doesn't stop the sweep" resilience, applied one level
                # deeper, per task within this single stage.
                _out(f, f"\n=== {task_id}: crashed, skipping -- {e} ===")
                continue

            t_type = task_type(task_id)
            type_counts = by_task_type.setdefault(t_type, {})
            for cat, n in category_totals.items():
                type_counts[cat] = type_counts.get(cat, 0) + n

            with open(task_config_path(task_id), encoding="utf-8") as fh:
                real_criteria = (yaml.safe_load(fh) or {}).get("acceptance_criteria", [])

            _out(f, f"\n=== {task_id}: final refined ({len(final_criteria)}) ===")
            for c in final_criteria:
                _out(f, f"  - {c}")
            _out(f, f"\n=== {task_id}: real, hand-tuned ({len(real_criteria)}) ===")
            for c in real_criteria:
                _out(f, f"  - {c}")

        if len(task_ids) > 1 and any(by_task_type.values()):
            _out(f, "\n=== Findings by task type (all tasks in this run) ===")
            for t_type in sorted(by_task_type):
                counts = by_task_type[t_type]
                if not counts:
                    continue
                total = sum(counts.values())
                breakdown = ", ".join(f"{cat}={n}" for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]))
                _out(f, f"  {t_type} ({total} total): {breakdown}")

    print(f"\nLog written to {log_path}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
