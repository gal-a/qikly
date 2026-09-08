"""
Tests for what the demo tells a first-time user.

Most of cli.py is printing, and printing does not usually deserve tests. These
lines do, because they are the only place the tool makes empirical claims to
someone who has not read the documentation and has no way to check them. Three
things have to hold.

The measured rates must stay attached to the tasks they were measured on. They
came from a specific set of 427 runs over ten tasks. A task renamed or added
without a matching measurement silently drops its rate line, and a task whose
rate is copied from a neighbour is worse than no rate at all.

The "one run is an artifact, not a rate" caveat must survive. A single demo run
converging is the single most misleading thing this tool can show, and that
sentence is the only thing standing between the demo and an overclaim.

A run that did not converge must say that nothing shipped. The central promise
is that the tool does not report success on code its own tests reject.
"""
import os

import pytest

from qikly import cli
from qikly.paths import resolve_input


# The research scripts write throwaway variant configs into this same
# directory and delete them when the run ends, so a task list read while an
# experiment is in flight contains CALC_TAX_EFI and friends. They are not
# bundled tasks and have no measured rate, so they are filtered here rather
# than making the suite fail whenever a sweep happens to be running.
_VARIANT_SUFFIXES = ("_EFI", "_EFR", "_CONV", "_ARMI", "_ARMR", "_BASE")


def _bundled_task_ids():
    d = os.path.dirname(resolve_input("config/tasks/CALC_TAX.yaml"))
    return sorted(n[:-5] for n in os.listdir(d)
                  if n.endswith(".yaml")
                  and not n[:-5].endswith(_VARIANT_SUFFIXES))


# ------------------------------------------------------ measured rates ----

def test_the_bundled_tasks_are_discoverable():
    """Guards the guard: an empty list makes everything below vacuous."""
    assert len(_bundled_task_ids()) == 10


def test_the_historical_rates_are_kept_but_never_read():
    """
    The demo used to print a stored convergence rate. It no longer does,
    because a settings override left on from an experiment tripled the suite
    sizes and took CALC_TAX from 91% to 30% without one word of its
    specification changing. A number printed from a table is a claim about a
    configuration as much as about a tool, and the table could not say which
    configuration produced it.

    The table stays as history so the two measurements can be compared. What
    must not come back is any code reading it.
    """
    import inspect

    from qikly import cli

    assert hasattr(cli, "_MEASURED_RATES_2026_08_14"), "the history was deleted"
    assert not hasattr(cli, "_MEASURED_RATES"), (
        "the old name is back, which is how it would get read again"
    )
    source = inspect.getsource(cli)
    uses = [line for line in source.splitlines()
            if "_MEASURED_RATES_2026_08_14" in line and not line.strip().startswith("#")]
    assert len(uses) == 1, (
        "the historical table is being read somewhere: " + "; ".join(uses)
    )


def test_the_historical_rates_still_name_real_tasks():
    """History is only useful if it can be lined up against a re-measurement."""
    from qikly import cli
    from qikly.orchestrator.orchestrator import discover_task_ids

    known = set(discover_task_ids())
    unknown = set(cli._MEASURED_RATES_2026_08_14) - known
    assert not unknown, f"historical rates name tasks that no longer exist: {unknown}"


def test_the_demo_says_one_run_is_not_a_rate(capsys):
    """
    The single most misleading thing the tool can show is one converged run.
    This sentence is what stops the demo from being read as a success rate.
    """
    cli._print_demo_note(["CALC_TAX"], converged=True)
    out = capsys.readouterr().out
    assert "One run is an artifact, not a rate" in out
    assert "run_all --repeat" in out


def test_the_demo_quotes_no_stored_rate(capsys):
    """
    Whatever number were printed here would be a claim about a model on a
    date, made by a tool that cannot know either. The demo says so instead.
    """
    from qikly import cli

    cli._print_demo_note(["CALC_TAX"], True)
    out = capsys.readouterr().out
    # The old format attached a rate to the task that just ran. Two numbers do
    # still appear, but as the drift story rather than as this task's rate,
    # which is the distinction that matters.
    assert "CALC_TAX 91%" not in out
    assert "across 427" not in out
    assert "measure your own" in out.lower()


def test_the_demo_explains_why_it_quotes_no_rate(capsys):
    """
    Silence would read as an omission. The reason is the interesting part: a
    rate belongs to a tool, a model and a configuration together, and one
    local setting moved the same task from 91% to 30% with its specification
    untouched.
    """
    from qikly import cli

    cli._print_demo_note(["CALC_TAX"], True)
    out = capsys.readouterr().out
    assert "configuration" in out.lower()
    assert "settings" in out.lower() or "generation call" in out.lower()


def test_a_run_that_did_not_converge_says_nothing_shipped(capsys):
    """The central promise: no success is reported on code the tests reject."""
    cli._print_demo_note(["CALC_TAX"], converged=False)
    out = capsys.readouterr().out
    assert "nothing shipped" in out
    assert "non-zero" in out


def test_a_converged_run_does_not_print_the_failure_notice(capsys):
    cli._print_demo_note(["CALC_TAX"], converged=True)
    assert "nothing shipped" not in capsys.readouterr().out


def test_the_demo_states_the_withholding(capsys):
    """
    The claim the whole project rests on, in the one place a new user reads.
    If this goes, the demo is just a wall of passing tests.

    It is made twice, in two registers, and both halves are checked here. The
    demo opens with --explain, which shows the criteria being removed from a
    named file; the closing note then says what that meant for the failures the
    reader just watched. The note used to restate the mechanism itself, which
    was the same paragraph twice on one screen.
    """
    from qikly import explain
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    shown = explain.render(explain.build(cli.DEMO_TASK))
    assert "acceptance_criteria" in shown
    assert "THE CODING AGENT" in shown and "REMOVED" in shown

    cli._print_demo_note([cli.DEMO_TASK], converged=True)
    out = capsys.readouterr().out
    assert "never been shown the rule" in out


# ------------------------------------------------------------- parsing ----

def test_the_demo_task_is_a_real_bundled_task():
    assert cli.DEMO_TASK in _bundled_task_ids()


def test_generate_criteria_is_opt_in(monkeypatch):
    """
    This flag writes into a task's config file. Defaulting it on would edit a
    user's inputs without being asked.
    """
    monkeypatch.setattr("sys.argv", ["qikly"])
    args = cli._parse_args()
    assert args.generate_criteria is False
    assert args.demo is False
    assert args.tasks is None


def test_tasks_are_taken_as_given(monkeypatch):
    monkeypatch.setattr("sys.argv", ["qikly", "--tasks", "CALC_TAX,ETL_EMAIL", "--demo"])
    args = cli._parse_args()
    assert args.tasks == "CALC_TAX,ETL_EMAIL"
    assert args.demo is True


# ------------------------------------------------ where the demo writes -----

def test_the_demo_writes_where_you_are_standing_not_where_the_package_lives(
        tmp_path, monkeypatch):
    """
    `cd somewhere-else && qikly --demo` used to write into the qikly checkout,
    because the root resolver walks up looking for inputs_private/ and falls
    back to the source tree when it finds none. --init had the same bug.
    """
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    root = cli._demo_root()
    assert str(tmp_path) in root
    assert root.startswith(os.path.join(str(tmp_path), cli.DEMO_DIR))


def test_an_absolute_demo_dir_is_used_as_given(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path / "elsewhere"))
    chosen = tmp_path / "recordings"
    root = cli._demo_root(str(chosen))
    assert root.startswith(str(chosen))


def test_a_relative_demo_dir_is_taken_from_where_you_are_standing(tmp_path, monkeypatch):
    """
    Consistent with the default. Resolving it against the project root instead
    would put it somewhere the user is not looking.
    """
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    root = cli._demo_root("gifs")
    assert root.startswith(os.path.join(str(tmp_path), "gifs"))


def test_every_demo_run_gets_its_own_timestamped_folder(tmp_path, monkeypatch):
    """
    Two demos must never share a directory: the second would resume the
    first's outputs and the run would not be from scratch.
    """
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    leaf = os.path.basename(cli._demo_root("out"))
    assert len(leaf) == 15 and leaf[8] == "_", leaf


def test_the_flag_reaches_the_runner():
    """A flag the demo never reads would be worse than no flag."""
    import inspect

    source = inspect.getsource(cli.main)
    assert "args.demo_dir" in source
    assert "where" in inspect.signature(cli._run_demo).parameters
