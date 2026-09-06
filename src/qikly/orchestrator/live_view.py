import sys
"""
A live terminal view of one or more V&V tasks' currently-running (or most
recent) run, tailing their transactions_<task_id>_*.jsonl logs as run.py
writes them. No IPC with run.py's worker processes -- every event is
already durably appended (and flushed, see orchestrator.log_transaction) to
that file as it happens, so this just polls and re-renders. Run it in a
second terminal alongside `python run.py`:

    python -m orchestrator.live_view
    python -m orchestrator.live_view --tasks ETL_ADDRESS,ETL_EMAIL
"""
import argparse
import glob
import json
import os
import time

from rich.console import Console
from rich.live import Live
from rich.table import Table

from qikly.paths import chdir_to_project_root

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/logs"
POLL_INTERVAL = 0.5
IDLE_WARN_SECONDS = 20
# Matches orchestrator.DEFAULT_STAGE_ORDER -- unit always runs last, but that
# doesn't affect display order here since we always show all three.
STAGE_ORDER = ["integration", "system", "unit"]


def _blank_stage_state():
    return {"iteration": None, "last_result": None, "passed": False, "fix_attempts": 0}


class TaskWatcher:
    """
    Tracks one task's current run: which transactions_*.jsonl file to tail,
    how far into it we've already read (a true byte offset -- binary mode,
    to avoid text-mode tell()/getsize() mismatches from newline translation
    on Windows), and per-stage state derived from events seen so far, so the
    view can show all three stages at once rather than just whichever one is
    currently active.
    """

    def __init__(self, task_id):
        self.task_id = task_id
        self.path = None
        self.offset = 0
        self.last_growth = time.monotonic()
        self.stages = {s: _blank_stage_state() for s in STAGE_ORDER}
        self.passed = False

    def _latest_path(self):
        """
        Restricted to digit-only timestamp suffixes ([0-9]*, not a bare *)
        so that e.g. task_id="ETL_ADDRESS" doesn't also match
        transactions_ETL_ADDRESS_DRAFT_<ts>.jsonl (the scratch task
        orchestrator/tuning/refine_acceptance_criteria.py runs under a
        "<task_id>_DRAFT" task_id) -- see the same fix in
        orchestrator/reports/report.py's _latest_transactions_path(). Without
        this, "DRAFT" sorts after digit-only timestamps and would
        permanently shadow this task's real, fresh runs.
        """
        pattern = os.path.join(LOG_DIR, f"transactions_{self.task_id}_[0-9]*.jsonl")
        matches = sorted(glob.glob(pattern))
        return matches[-1] if matches else None

    def poll(self):
        """
        Switch to a newer log file if one appeared (a fresh run.py
        invocation started after this watcher did) -- resetting all
        progress state -- then read and apply any bytes appended since the
        last poll of whichever file we're currently watching.
        """
        latest = self._latest_path()
        if latest and latest != self.path:
            self.path = latest
            self.offset = 0
            self.stages = {s: _blank_stage_state() for s in STAGE_ORDER}
            self.passed = False

        if not self.path or not os.path.exists(self.path):
            return

        size = os.path.getsize(self.path)
        if size < self.offset:
            self.offset = 0  # file was truncated/replaced out from under us
        if size > self.offset:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                new_bytes = f.read()
                self.offset = f.tell()
            for line in new_bytes.decode("utf-8").splitlines():
                line = line.strip()
                if line:
                    self._apply(json.loads(line))
            self.last_growth = time.monotonic()

    def _apply(self, event):
        action = event.get("action")
        if action == "test_run" and not event.get("is_regression_check"):
            stage = event.get("stage")
            info = self.stages.get(stage)
            if info is not None:
                counts = event.get("counts") or {}
                info["iteration"] = event.get("iteration")
                info["last_result"] = f"{counts.get('passed', 0)}/{counts.get('total', 0)} passed"
                info["passed"] = event.get("status") == "pass"
        elif action == "agent_fix_requested":
            # A bootstrap fix cycle is logged with stage="bootstrap" (see
            # orchestrator.orchestrate()) -- it's really the first stage's
            # first attempt, so it counts against that stage's total.
            stage = event.get("stage")
            stage = STAGE_ORDER[0] if stage == "bootstrap" else stage
            info = self.stages.get(stage)
            if info is not None:
                info["fix_attempts"] += 1
        elif action == "all_tests_passed":
            self.passed = True

    def stage_rows(self):
        """
        One dict per stage in STAGE_ORDER, each with its own display text
        and rich style. "Stalled" is a guess, not a fact -- the log has no
        explicit failure event (a raised RuntimeError just ends the process
        without one more line logged) -- applied only to the frontier stage
        (the first one not yet passed) when the file has gone idle, since
        that's the one that was actually in flight.
        """
        frontier = next(
            (i for i, s in enumerate(STAGE_ORDER) if not self.stages[s]["passed"]), None
        )
        idle = time.monotonic() - self.last_growth

        rows = []
        for i, stage in enumerate(STAGE_ORDER):
            info = self.stages[stage]
            if info["passed"]:
                text, style = "passed", "bold green"
            elif frontier is not None and i == frontier and info["iteration"] is not None:
                if self.path is not None and idle > IDLE_WARN_SECONDS:
                    text, style = f"stalled ({int(idle)}s idle)", "yellow"
                else:
                    text, style = "iterating", "cyan"
            else:
                text, style = "not started", "dim"
            rows.append({
                "stage": stage,
                "iteration": info["iteration"],
                "last_result": info["last_result"],
                "fix_attempts": info["fix_attempts"],
                "status_text": text,
                "status_style": style,
            })
        return rows


def render(watchers):
    table = Table(title="qikly live progress", expand=True)
    table.add_column("Task")
    table.add_column("Stage")
    table.add_column("Iteration")
    table.add_column("Last result")
    table.add_column("FIX/PATCH attempts", justify="right")
    table.add_column("Status")

    for w in watchers:
        rows = w.stage_rows()
        for i, r in enumerate(rows):
            table.add_row(
                w.task_id if i == 0 else "",
                r["stage"],
                str(r["iteration"]) if r["iteration"] is not None else "n/a",
                r["last_result"] or "n/a",
                str(r["fix_attempts"]),
                f"[{r['status_style']}]{r['status_text']}[/{r['status_style']}]",
                end_section=(i == len(rows) - 1),
            )
    return table


def _parse_args():
    parser = argparse.ArgumentParser(description="Live terminal view of V&V task runs.")
    parser.add_argument(
        "--tasks", default=None,
        help="Comma-separated task_ids to watch (default: every task under inputs/config/tasks/)"
    )
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL, help="Poll interval in seconds")
    return parser.parse_args()


def main():
    from qikly.orchestrator.orchestrator import discover_task_ids

    args = _parse_args()
    task_ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_task_ids()
    task_ids = [t for t in task_ids if t]
    if not task_ids:
        print("No tasks found under inputs/config/tasks/ (and none given via --tasks).")
        return

    watchers = [TaskWatcher(t) for t in task_ids]
    console = Console()

    with Live(render(watchers), console=console, refresh_per_second=4) as live:
        try:
            while True:
                for w in watchers:
                    w.poll()
                live.update(render(watchers))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
