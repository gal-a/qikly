"""
The instrument for "did editing a prompt help?".

Two things are being guarded, and the second matters more than the first.

  1. The arithmetic: runs group by the prompts that produced them, and the
     numbers printed are the ones on disk.
  2. **The refusals.** This project has been wrong before by reading one run
     as a rate, so the report must decline to compare small arms, must not
     pool runs from before the arm was recorded, and must not call a
     difference smaller than its own noise a result. Those are asserted
     here as behaviour, not left as intentions in a docstring.

No run is ever started: `run_arms` takes an injected runner, which is the
only reason the alternation and the environment can be tested at all.
"""
import json
import os

import pytest

from qikly.orchestrator import compare_prompts as cp


def write(tmp_path, task, stamp, *, passed=True, attempts=4, seconds=600,
          overrides=None, schema=7):
    d = tmp_path / "outputs" / "reports" / "run_summary"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": schema,
        "task_id": task,
        "run_timestamp": stamp,
        "passed_overall": passed,
        "total_fix_attempts": attempts,
        "duration_seconds": seconds,
    }
    if schema >= 7:
        payload["prompt_overrides"] = overrides or {}
    (d / ("%s_%s.json" % (task, stamp))).write_text(
        json.dumps(payload), encoding="utf-8")


# ------------------------------------------------------------- arms --------

def test_a_stock_run_is_named_as_such():
    assert cp.arm_of({"prompt_overrides": {}}) == cp.STOCK


def test_an_overridden_run_names_the_files():
    arm = cp.arm_of({"prompt_overrides": {"fix_prompt.md": "abc12345"}})
    assert "fix_prompt.md@abc12345" in arm


def test_two_different_edits_are_two_different_arms():
    a = cp.arm_of({"prompt_overrides": {"fix_prompt.md": "aaaaaaaa"}})
    b = cp.arm_of({"prompt_overrides": {"fix_prompt.md": "bbbbbbbb"}})
    assert a != b


def test_an_old_summary_is_unknown_rather_than_stock():
    """
    The failure this prevents: pooling pre-schema-7 runs into the stock arm
    would mix in runs that may have been either, and the comparison would be
    of a bucket with itself.
    """
    assert cp.arm_of({"schema_version": 6}) is None


# ------------------------------------------------------------ loading ------

def test_runs_are_grouped_by_arm(tmp_path):
    write(tmp_path, "T", "001")
    write(tmp_path, "T", "002", overrides={"fix_prompt.md": "deadbeef"})
    by_arm = cp.group(cp.load("T", root=str(tmp_path)))
    assert sorted(len(v) for v in by_arm.values()) == [1, 1]


def test_another_task_is_not_pulled_in(tmp_path):
    write(tmp_path, "T", "001")
    write(tmp_path, "OTHER", "001")
    assert len(cp.load("T", root=str(tmp_path))) == 1


def test_a_corrupt_summary_is_skipped_and_announced(tmp_path, capsys):
    write(tmp_path, "T", "001")
    bad = tmp_path / "outputs" / "reports" / "run_summary" / "T_002.json"
    bad.write_text("{not json", encoding="utf-8")
    assert len(cp.load("T", root=str(tmp_path))) == 1
    assert "T_002.json" in capsys.readouterr().err


def test_stats_report_counts_and_the_spread(tmp_path):
    rows = [{"passed_overall": True, "total_fix_attempts": 2, "duration_seconds": 60},
            {"passed_overall": False, "total_fix_attempts": 8, "duration_seconds": 120},
            {"passed_overall": True, "total_fix_attempts": 4, "duration_seconds": 180}]
    s = cp.stats(rows)
    assert (s["n"], s["converged"]) == (3, 2)
    assert (s["attempts_median"], s["attempts_min"], s["attempts_max"]) == (4, 2, 8)
    assert s["attempts_iqr"] == 3


# ------------------------------------------------------- the refusals ------

def test_one_arm_alone_is_not_compared(tmp_path):
    for i in range(5):
        write(tmp_path, "T", "00%d" % i)
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "nothing to compare" in out.lower()


def test_two_runs_each_is_refused_as_a_rate(tmp_path):
    write(tmp_path, "T", "001", attempts=2)
    write(tmp_path, "T", "002", attempts=3)
    write(tmp_path, "T", "003", attempts=9, overrides={"f.md": "aaaaaaaa"})
    write(tmp_path, "T", "004", attempts=9, overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "artifact, not a rate" in out


def test_a_difference_inside_the_noise_is_not_called_a_result(tmp_path):
    for i, a in enumerate([2, 6, 10]):
        write(tmp_path, "T", "10%d" % i, attempts=a)
    for i, a in enumerate([3, 7, 11]):
        write(tmp_path, "T", "20%d" % i, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "smaller than the noise" in out
    assert "not evidence" in out


def test_one_outlying_run_does_not_veto_a_difference(tmp_path):
    """
    The reason the yardstick is the interquartile range. Under max minus min,
    the 30 below made the stock arm span 28, so a consistent six-attempt gap
    read as noise, and every run added could only widen the range further.
    """
    for i, a in enumerate([2, 2, 2, 2, 30]):
        write(tmp_path, "T", "10%d" % i, attempts=a)
    for i, a in enumerate([8, 8, 8, 9, 8]):
        write(tmp_path, "T", "20%d" % i, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "worth following up" in out


def test_a_difference_beyond_the_noise_is_still_not_a_measurement(tmp_path):
    for i, a in enumerate([2, 2, 3]):
        write(tmp_path, "T", "10%d" % i, attempts=a)
    for i, a in enumerate([20, 20, 21]):
        write(tmp_path, "T", "20%d" % i, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "worth following up" in out
    assert "not yet a measurement" in out


def test_a_task_with_a_shared_prefix_is_not_pulled_in(tmp_path):
    """Reproduced by an audit: PRICING also loaded every PRICING_V2 run."""
    write(tmp_path, "PRICING", "001")
    write(tmp_path, "PRICING_V2", "001", attempts=99)
    rows = cp.load("PRICING", root=str(tmp_path))
    assert [r["task_id"] for r in rows] == ["PRICING"]


def test_one_abandoned_arm_does_not_block_the_verdict(tmp_path):
    """
    Reproduced by an audit. Every edit makes a new arm, so trying one edit
    once and moving on used to leave a single-run arm that stopped that
    task's verdict for good.
    """
    for i, a in enumerate([2, 2, 3]):
        write(tmp_path, "T", "10%d" % i, attempts=a)
    for i, a in enumerate([20, 20, 21]):
        write(tmp_path, "T", "20%d" % i, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    write(tmp_path, "T", "300", attempts=5, overrides={"f.md": "bbbbbbbb"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "artifact, not a rate" not in out
    assert "worth following up" in out
    assert "1 other arm(s) on disk were left out" in out


def test_arms_on_different_models_are_refused(tmp_path):
    """Comparing last month on one model with today on another is not a
    prompt comparison, and aggregate_report already knows that."""
    for i in range(3):
        p = tmp_path / "outputs" / "reports" / "run_summary"
        write(tmp_path, "T", "10%d" % i)
        import json as _j
        f = p / ("T_10%d.json" % i)
        d = _j.loads(f.read_text(encoding="utf-8"))
        d["provenance"] = {"model": "model-a"}
        f.write_text(_j.dumps(d), encoding="utf-8")
    for i in range(3):
        write(tmp_path, "T", "20%d" % i, overrides={"f.md": "aaaaaaaa"})
        import json as _j
        f = tmp_path / "outputs" / "reports" / "run_summary" / ("T_20%d.json" % i)
        d = _j.loads(f.read_text(encoding="utf-8"))
        d["provenance"] = {"model": "model-b"}
        f.write_text(_j.dumps(d), encoding="utf-8")
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "differ in more than their prompts" in out
    assert "model" in out


def test_one_configuration_throughout_is_compared(tmp_path):
    """The commensurability guard must not refuse everything."""
    import json as _j
    for i, (stamp, a, ov) in enumerate(
            [("100", 2, None), ("101", 2, None), ("102", 3, None),
             ("200", 20, {"f.md": "a" * 8}), ("201", 20, {"f.md": "a" * 8}),
             ("202", 21, {"f.md": "a" * 8})]):
        write(tmp_path, "T", stamp, attempts=a, overrides=ov)
        f = tmp_path / "outputs" / "reports" / "run_summary" / ("T_%s.json" % stamp)
        d = _j.loads(f.read_text(encoding="utf-8"))
        d["provenance"] = {"model": "same-model", "provider": "gemini"}
        f.write_text(_j.dumps(d), encoding="utf-8")
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "differ in more than" not in out
    assert "worth following up" in out


def test_an_arm_that_fails_fast_is_not_called_faster(tmp_path):
    """
    Reproduced by an audit before this guard existed, and it is the worst
    thing this tool could do: stock converged 3 of 3 taking 6 to 7 attempts,
    the override converged 0 of 3 taking 2, and the verdict called the
    override "worth following up". Collapsing early is not speed.
    """
    for i, a in enumerate([6, 6, 7]):
        write(tmp_path, "T", "10%d" % i, passed=True, attempts=a)
    for i in range(3):
        write(tmp_path, "T", "20%d" % i, passed=False, attempts=2,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "did not converge equally" in out
    assert "0 of 3" in out and "3 of 3" in out
    assert "worth following up" not in out


def test_attempts_are_compared_when_both_arms_got_there(tmp_path):
    """The guard must not refuse everything: equal convergence still compares."""
    for i, a in enumerate([2, 2, 3]):
        write(tmp_path, "T", "10%d" % i, passed=True, attempts=a)
    for i, a in enumerate([20, 20, 21]):
        write(tmp_path, "T", "20%d" % i, passed=True, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path))))
    assert "did not converge" not in out
    assert "worth following up" in out


def test_a_partial_convergence_difference_also_refuses(tmp_path):
    """2 of 3 against 3 of 3 is still a difference in the thing that matters."""
    for i in range(3):
        write(tmp_path, "T", "10%d" % i, passed=True, attempts=5)
    for i in range(3):
        write(tmp_path, "T", "20%d" % i, passed=i < 2, attempts=5,
              overrides={"f.md": "aaaaaaaa"})
    assert "did not converge equally" in cp.verdict(
        cp.group(cp.load("T", root=str(tmp_path))))


def test_no_arm_is_ever_declared_the_winner(tmp_path):
    for i, a in enumerate([2, 2, 3]):
        write(tmp_path, "T", "10%d" % i, attempts=a)
    for i, a in enumerate([20, 20, 21]):
        write(tmp_path, "T", "20%d" % i, attempts=a,
              overrides={"f.md": "aaaaaaaa"})
    out = cp.verdict(cp.group(cp.load("T", root=str(tmp_path)))).lower()
    assert "better" not in out and "winner" not in out and "improve" not in out


def test_unassignable_runs_are_listed_and_not_pooled(tmp_path, capsys):
    write(tmp_path, "T", "001", schema=6)
    write(tmp_path, "T", "002")
    by_arm = cp.report("T", root=str(tmp_path))
    assert None in by_arm
    assert "cannot be assigned to an arm" in capsys.readouterr().out


def test_percentages_are_not_printed(tmp_path, capsys):
    """"3 of 5" survives being read quickly; "60%" does not."""
    for i in range(5):
        write(tmp_path, "T", "00%d" % i, passed=i < 3)
    cp.report("T", root=str(tmp_path))
    out = capsys.readouterr().out
    assert "%" not in out
    assert "3 of 5" in out


def test_an_empty_tree_says_so_rather_than_crashing(tmp_path, capsys):
    cp.report("T", root=str(tmp_path))
    assert "No run summaries" in capsys.readouterr().out


# ----------------------------------------------------------- running -------

def test_the_arms_alternate(tmp_path):
    seen = []
    order = cp.run_arms("T", 3, runner=lambda task, arm: seen.append(arm))
    assert seen == ["off", "on", "off", "on", "off", "on"]
    assert order == seen


def test_every_run_is_handed_the_task(tmp_path):
    seen = []
    cp.run_arms("MY_TASK", 2, runner=lambda task, arm: seen.append(task))
    assert seen == ["MY_TASK"] * 4


def test_zero_repeats_runs_nothing():
    seen = []
    cp.run_arms("T", 0, runner=lambda task, arm: seen.append(arm))
    assert seen == []


def test_the_stock_arm_sets_the_switch_and_the_other_clears_it(monkeypatch):
    """
    The arm has to reach the child process, and the override arm has to
    actively clear an inherited switch rather than assume it is absent.
    """
    calls = []
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda cmd, **kw: calls.append(kw["env"]))
    monkeypatch.setenv(cp.PROMPT_OVERRIDES_ENV, "off")
    cp._spawn("T", "off")
    cp._spawn("T", "on")
    assert calls[0][cp.PROMPT_OVERRIDES_ENV] == "off"
    assert cp.PROMPT_OVERRIDES_ENV not in calls[1]


def test_spawning_does_not_inherit_a_stdin(monkeypatch):
    """A long unattended sweep must not block on a prompt it cannot see."""
    import subprocess as sp

    calls = []
    monkeypatch.setattr(cp.subprocess, "run", lambda cmd, **kw: calls.append(kw))
    cp._spawn("T", "on")
    assert calls[0]["stdin"] == sp.DEVNULL
