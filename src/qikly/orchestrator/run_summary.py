"""
Writes one machine-readable summary of a run's convergence shape to
outputs/reports/run_summary/, at the end of every run.

This is a re-serialization, not a new measurement. It reuses the exact
computations orchestrator/reports/report.py and
orchestrator/reports/metrics_report.py already derive from a run's
transaction log -- pass/fail, per-stage iteration counts, FIX/PATCH outcome
buckets, regression-check counts, duration. The metrics report renders those
numbers as HTML for a person to read; this writes the same numbers as JSON so
they can be aggregated across runs by a script, which HTML can't be. If the
two ever disagree, the transaction log under outputs/logs/ is the source of
truth and both are wrong.

Nothing here transmits anything. This module writes a local file and stops:
there is no network call in it, and no collection endpoint exists.
"""
import json
import os

from qikly.orchestrator.reports.report import (
    _latest_transactions_path,
    _load_task_meta,
    _run_timestamp_from_path,
    build_blocks,
    compute_summary,
    group_by_stage,
    load_events,
)
from qikly.orchestrator.reports.metrics_report import (
    compute_duration,
    compute_patch_outcomes,
    compute_stage_details,
)

RUN_SUMMARY_DIR = "outputs/reports/run_summary"


def _provenance():
    """
    What produced these numbers: model, date, and the generation settings.

    A convergence rate is a property of a configuration as much as of a tool,
    and until now a summary recorded neither. When a sweep came back at 25%
    against a stored 59%, answering "what changed" meant diffing task specs,
    prompts and provider parameters against a two-week-old commit, twice,
    before finding a single line in a local override that had tripled every
    generated suite. All of that was a lookup that could not be looked up.

    Never raises. A run that produced real output must not fail while
    recording what produced it, so anything unavailable is simply absent.
    """
    import datetime
    import os

    out = {"recorded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        from qikly.orchestrator.orchestrator import criteria_per_batch, load_settings
        settings = load_settings() or {}
        agents = settings.get("agents") or {}
        default = agents.get("default") or {}
        # settings.yaml pairs a provider with a model, so the default model
        # belongs to the default provider. Overriding only LLM_PROVIDER used to
        # record e.g. provider=openai with model=gemini-3.5-flash-lite, which
        # is not a configuration that can exist. A rate belongs to a model as
        # much as to a tool, so a summary naming the wrong one is worse than
        # one naming none.
        env_provider = os.environ.get("LLM_PROVIDER")
        out["provider"] = env_provider or default.get("provider")
        model = os.environ.get("LLM_MODEL")
        if not model:
            switched = (env_provider and default.get("provider")
                        and env_provider != default.get("provider"))
            model = None if switched else default.get("model")
        if not model:
            from qikly.agent_api.providers.router import default_model_for
            model = default_model_for(out["provider"])
        out["model"] = model
        out["criteria_per_batch"] = criteria_per_batch()
        out["max_retries_per_stage"] = (settings.get("orchestrator") or {}).get(
            "max_retries_per_stage")
        # Only the agents that actually override the default are worth
        # recording; the rest are the default by definition.
        overrides = {name: cfg.get("model") for name, cfg in agents.items()
                     if name != "default" and isinstance(cfg, dict) and cfg.get("model")}
        if overrides:
            out["agent_model_overrides"] = overrides
    except Exception:
        pass
    try:
        from qikly import __version__
        out["qikly_version"] = __version__
    except Exception:
        pass
    return out


def build_payload(task_id, run_timestamp=None):
    """
    Raises FileNotFoundError if no transaction log exists yet for task_id
    (mirrors orchestrator/reports/metrics_report.py's generate_metrics_report).
    """
    if run_timestamp is None:
        path = _latest_transactions_path(task_id)
        run_timestamp = _run_timestamp_from_path(task_id, path)
    else:
        path = os.path.join("outputs/logs", f"transactions_{task_id}_{run_timestamp}.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No transaction log at {path}")

    events = load_events(path)
    blocks = build_blocks(events)
    summary = compute_summary(blocks)
    outcomes = compute_patch_outcomes(blocks)
    stage_groups = group_by_stage(blocks)
    stage_details = compute_stage_details(stage_groups)
    duration_td = compute_duration(events)
    task_meta = _load_task_meta(task_id)

    # schema_version is kept because these files are meant to be read back in
    # bulk by a later script; the fields below are free to change shape, and a
    # reader needs to know which shape it got.
    return {
        "schema_version": 4,
        "provenance": _provenance(),
        "task_id": task_id,
        "task_name": task_meta.get("task_name"),
        "run_timestamp": run_timestamp,
        "passed_overall": summary["passed_overall"],
        "total_fix_attempts": summary["total_fix_attempts"],
        "regression_fails": summary["regression_fails"],
        "apply_failed": summary["apply_failed"],
        "ineffective_patches": summary["ineffective_patches"],
        "stage_iterations": dict(summary["stage_iterations"]),
        "patch_outcomes": outcomes,
        "duration_seconds": int(duration_td.total_seconds()) if duration_td is not None else None,
        "stage_first_attempt_pass": {
            stage: d["first_attempt_pass"] for stage, d in stage_details.items()
        },
    }


def record(task_id, run_timestamp=None):
    """
    Writes this run's summary to outputs/reports/run_summary/ and returns the
    path, or None without writing anything if no transaction log exists yet
    for this task/run.
    """
    try:
        payload = build_payload(task_id, run_timestamp)
    except FileNotFoundError:
        return None

    os.makedirs(RUN_SUMMARY_DIR, exist_ok=True)
    out_path = os.path.join(
        RUN_SUMMARY_DIR, f"{payload['task_id']}_{payload['run_timestamp']}.json"
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
    return out_path
