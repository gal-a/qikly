"""
Tests for the sweep driver.

Two functions here carry more weight than their size suggests.

_subprocess_env exists because of a first-run failure that only appears from a
clone. Stages after the first are launched as `python -m qikly...`, and
the src layout deliberately keeps the package off sys.path, so stage 1 worked
and every later stage died with ModuleNotFoundError. That is the worst shape
of bug for an open source project: it never reproduces for the author, who has
it installed.

_run_timestamps_from is how a sweep works out which runs belong to it. It
reads each summary's own run_timestamp rather than parsing the filename,
because both task_id and timestamp contain underscores and filename splitting
is ambiguous the moment a task_id gains a part.
"""
import json
import os

import pytest

from qikly.orchestrator import run_all


# --------------------------------------------------------- child env ----

def test_the_package_parent_is_on_the_child_path():
    """Without this a clone fails on every stage after the first."""
    import qikly
    expected = os.path.dirname(os.path.dirname(os.path.abspath(qikly.__file__)))
    env = run_all._subprocess_env()
    assert env["PYTHONPATH"].split(os.pathsep)[0] == expected


def test_an_existing_pythonpath_is_kept_not_replaced(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.path.join("some", "other", "place"))
    parts = run_all._subprocess_env()["PYTHONPATH"].split(os.pathsep)
    assert parts[-1] == os.path.join("some", "other", "place")
    assert len(parts) == 2


def test_extra_variables_are_merged_in(monkeypatch):
    env = run_all._subprocess_env({"QIKLY_TRACEBACK": "1"})
    assert env["QIKLY_TRACEBACK"] == "1"
    assert "PYTHONPATH" in env


def test_extra_variables_win_over_the_inherited_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    env = run_all._subprocess_env({"LLM_PROVIDER": "openai"})
    assert env["LLM_PROVIDER"] == "openai"


def test_the_parent_environment_is_not_mutated(monkeypatch):
    """A sweep runs many stages; leaking PYTHONPATH into this process would
    change the behaviour of every later one."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    run_all._subprocess_env({"SOMETHING_NEW": "1"})
    assert "PYTHONPATH" not in os.environ
    assert "SOMETHING_NEW" not in os.environ


# ------------------------------------------------------- timestamps ----

def _summary(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def test_timestamps_come_from_the_file_contents_not_the_name(tmp_path):
    """
    ETL_NAME_SPLIT has two underscores of its own. Splitting the filename
    would recover the wrong field, and silently: the result is still a
    plausible looking string.
    """
    paths = [
        _summary(tmp_path, "ETL_NAME_SPLIT_20260826_120000.json",
                 {"run_timestamp": "20260826_120000"}),
        _summary(tmp_path, "CALC_TAX_20260826_130000.json",
                 {"run_timestamp": "20260826_130000"}),
    ]
    assert run_all._run_timestamps_from(paths) == {"20260826_120000", "20260826_130000"}


def test_repeats_of_one_run_collapse_to_one_timestamp(tmp_path):
    """One sweep writes one summary per task, all sharing a timestamp."""
    paths = [
        _summary(tmp_path, "A.json", {"run_timestamp": "20260826_120000"}),
        _summary(tmp_path, "B.json", {"run_timestamp": "20260826_120000"}),
    ]
    assert run_all._run_timestamps_from(paths) == {"20260826_120000"}


def test_a_corrupt_summary_is_skipped_not_fatal(tmp_path):
    """
    A summary can be truncated if a run was killed mid-write. One unreadable
    file must not discard the rest of the sweep's results.
    """
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    good = _summary(tmp_path, "good.json", {"run_timestamp": "20260826_120000"})
    assert run_all._run_timestamps_from([str(bad), good]) == {"20260826_120000"}


def test_a_missing_file_is_skipped(tmp_path):
    good = _summary(tmp_path, "good.json", {"run_timestamp": "20260826_120000"})
    missing = str(tmp_path / "gone.json")
    assert run_all._run_timestamps_from([missing, good]) == {"20260826_120000"}


def test_a_summary_without_a_timestamp_contributes_nothing(tmp_path):
    p = _summary(tmp_path, "old_schema.json", {"task_id": "CALC_TAX"})
    assert run_all._run_timestamps_from([p]) == set()


def test_no_files_is_an_empty_set(tmp_path):
    assert run_all._run_timestamps_from([]) == set()


# ------------------------------------------------------------ stages ----

def test_a_failing_stage_reports_its_code_and_does_not_raise(capsys):
    """
    A sweep runs reporting stages after the run stages. If a failure in one
    aborted the sweep, a single bad task would cost every other task's report.
    """
    import sys
    code = run_all._run_stage("probe", [sys.executable, "-c", "raise SystemExit(3)"])
    assert code == 3
    assert "exited with code 3" in capsys.readouterr().out


def test_a_passing_stage_returns_zero_quietly(capsys):
    import sys
    code = run_all._run_stage("probe", [sys.executable, "-c", "pass"])
    assert code == 0
    assert "exited with code" not in capsys.readouterr().out


# ------------------------------------------- a stage that cannot progress ----

def test_three_identical_patches_is_stuck():
    """
    A model that has run out of ideas proposes the diff it already tried.
    Every attempt after that costs a call and cannot succeed. One observed
    demo run burned nine identical iterations on the same failing test before
    the attempt budget stopped it.
    """
    from qikly.orchestrator.orchestrator import _stuck_reason

    assert "identical" in _stuck_reason(["x", "a", "a", "a"])


def test_alternating_between_two_patches_is_stuck():
    from qikly.orchestrator.orchestrator import _stuck_reason

    assert "alternated" in _stuck_reason(["x", "a", "b", "a"])


def test_two_repeats_are_not_enough_to_call_it_stuck():
    """
    Three applied patches before either pattern can fire, so a model
    legitimately refining the same area twice is not cut off mid-repair.
    """
    from qikly.orchestrator.orchestrator import _stuck_reason

    assert _stuck_reason(["a", "a"]) is None


def test_a_stage_still_making_progress_is_left_alone():
    from qikly.orchestrator.orchestrator import _stuck_reason

    assert _stuck_reason(["a", "b", "c"]) is None
    assert _stuck_reason(["a", "a", "b"]) is None, "recovering, not stuck"


def test_the_demo_reports_one_model_call_count_not_two():
    """
    A real demo printed "16 model calls" from the transaction log directly
    above a usage line saying 29. The log count tallies three specific actions
    and undercounts; the usage counter counts what the providers were actually
    asked. Only one of them may appear.
    """
    import inspect

    from qikly import cli

    # Match the interpolation, not the words: the comment explaining why this
    # was removed necessarily quotes the old wording, and a guard that trips
    # on its own explanation is the same mistake in a different place.
    source = inspect.getsource(cli._print_demo_facts)
    assert "f['calls']" not in source and 'f["calls"]' not in source, (
        "the demo facts block is reporting its own call count again, which "
        "contradicts the usage line printed just below it"
    )


def test_a_repeated_failure_never_aborts_a_stage():
    """
    This was an abort for about four minutes, stopping a stage after three
    patches that left the same tests failing. The next recorded run disproved
    it: unit iterations 2 through 7 all reported 11/12 with the identical
    failure signature, and iteration 8 passed. Aborting at three would have
    discarded a run that converged in 44 seconds.

    A model grinding at one failing test for six attempts is indistinguishable
    from working on a hard case. Only a byte-identical diff proves nothing can
    change. The counter may narrate; it may not stop the run.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator.orchestrate)
    for line in source.splitlines():
        if "ineffective_streak" in line and (">=" in line or ">" in line):
            assert "raise" not in source.split(line, 1)[1][:400], (
                "a repeated failure signature must not end the stage: " + line.strip()
            )
    assert "ineffective_patches" not in source, (
        "the abort that this test exists to prevent has been reintroduced"
    )


def test_the_generation_progress_lines_do_not_prefix_the_task_twice():
    """
    _run_task_process wraps print() to prefix every line with [task_id].
    Adding one by hand produced "[CALC_TAX] [CALC_TAX] generating ..." in a
    recorded demo.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator.orchestrate)
    for line in source.splitlines():
        if "tests from the spec" in line or "tests written" in line:
            assert "[{task_id}]" not in line, (
                "print() is already prefixed with the task id: " + line.strip()
            )


# ------------------------------------------- what produced these numbers ----

def test_a_run_summary_records_what_produced_it():
    """
    A convergence rate is a property of a configuration as much as of a tool.
    A sweep once came back at 25% against a stored 59%, and answering "what
    changed" meant diffing task specs, prompts and provider parameters against
    a two-week-old commit, twice, before finding one line in a local override
    that had tripled every generated suite. All of that was a lookup that could
    not be looked up.
    """
    from qikly.orchestrator.run_summary import _provenance

    p = _provenance()
    for key in ("recorded_at", "model", "criteria_per_batch", "qikly_version"):
        assert key in p, f"a summary would not record {key}"


def test_the_generation_setting_is_recorded_because_it_moves_the_rate():
    """
    criteria_per_batch decides how many tests get generated. At 4 the suites
    came out roughly three times the size of those at 0, and convergence fell
    by more than half. Any rate quoted without it is ambiguous.
    """
    from qikly.orchestrator.run_summary import _provenance

    assert isinstance(_provenance()["criteria_per_batch"], int)


def test_recording_provenance_never_costs_the_run(monkeypatch):
    """
    A run that produced real output must not fail while recording what
    produced it.
    """
    from qikly.orchestrator import run_summary

    monkeypatch.setattr(
        "qikly.orchestrator.orchestrator.load_settings",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("settings unreadable")))
    p = run_summary._provenance()
    assert "recorded_at" in p, "the timestamp survives even when settings do not"


def test_the_schema_version_moved_with_the_new_field():
    """
    These files are read back in bulk. A reader that meets a summary without
    provenance has to know it is an older shape rather than assume the field
    was lost.
    """
    import inspect

    from qikly.orchestrator import run_summary

    source = inspect.getsource(run_summary.build_payload)
    assert '"schema_version": 4' in source
