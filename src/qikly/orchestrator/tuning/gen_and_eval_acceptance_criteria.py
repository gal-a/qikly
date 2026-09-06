import sys
"""
Compares auto-generated acceptance_criteria (agent_interface.py's
agent_generate_acceptance_criteria, generated from requirements alone)
against the real, hand-tuned ones already in a task file. This is the
evaluation harness for the auto-generation MVP, not a live orchestrator
integration -- it prints both lists side by side for human judgment and
never writes to the task file, since the real acceptance_criteria are the
ground truth this comparison depends on. Judging whether a generated
criterion is "as good as" a hand-tuned one needs a human read at this
stage, not a heuristic score.

Also writes everything to a timestamped log under
outputs/reports/acceptance_criteria/, same content as the console output --
so a run's results can be reviewed (including by reading the file directly)
without needing the terminal output pasted back in.

    python -m orchestrator.tuning.gen_and_eval_acceptance_criteria                    # every task under inputs/config/tasks/
    python -m orchestrator.tuning.gen_and_eval_acceptance_criteria --task ETL_ADDRESS
    python -m orchestrator.tuning.gen_and_eval_acceptance_criteria --task ETL_ADDRESS,ETL_EMAIL
"""
import argparse
import os
from datetime import datetime

import yaml

from qikly.paths import chdir_to_project_root

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/reports/acceptance_criteria"


def _out(f, line=""):
    print(line)
    f.write(line + "\n")


def run(task_id, f, seed=None):
    from qikly.agent_api.agent_interface import agent_generate_acceptance_criteria, _read_task

    # _read_task (not a raw open()) so a typoed task_id gets the same
    # "did you mean ...?" suggestion as agent_generate_acceptance_criteria
    # below, instead of a bare OS-level FileNotFoundError.
    real_criteria = (yaml.safe_load(_read_task(task_id)) or {}).get("acceptance_criteria", [])

    generated = agent_generate_acceptance_criteria(task_id, seed=seed)

    _out(f, f"=== {task_id}: auto-generated ({len(generated)}) ===")
    for c in generated:
        _out(f, f"  - {c}")
    _out(f, f"\n=== {task_id}: real, hand-tuned ({len(real_criteria)}) ===")
    for c in real_criteria:
        _out(f, f"  - {c}")


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Compare auto-generated acceptance criteria against a task's real, hand-tuned ones."
    )
    parser.add_argument(
        "--task", default=None,
        help="Comma-separated task_id(s), e.g. ETL_ADDRESS or ETL_ADDRESS,ETL_EMAIL "
             "(default: every task under inputs/config/tasks/)"
    )
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


def main():
    from qikly.orchestrator.orchestrator import discover_task_ids

    args = _parse_args()
    task_ids = [t.strip() for t in args.task.split(",")] if args.task else discover_task_ids()
    task_ids = [t for t in task_ids if t]

    os.makedirs(LOG_DIR, exist_ok=True)
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"gen_and_eval_{run_timestamp}.txt")

    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        for i, task_id in enumerate(task_ids):
            if i > 0:
                _out(f)
            try:
                run(task_id, f, seed=args.seed)
            except FileNotFoundError as e:
                _out(f, f"[{task_id}] skipped: {e}")

    print(f"\nLog written to {log_path}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
