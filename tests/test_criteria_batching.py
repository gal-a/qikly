"""
Tests for batched test generation.

Batching exists because the suite was measured not to grow with the bar: 54%
more criteria produced a 6% smaller suite. Splitting the criteria across
several generation calls is the fix, and it introduces two failure modes that
are silent rather than loud, which is why they are pinned here.

The first is losing criteria at the split. A batching bug that drops the last
partial batch removes part of the bar from test generation entirely, and the
run still passes: fewer tests, all green.

The second is losing tests at the merge. Concatenating generated modules into
one file looks tidier and silently discards duplicates, since two batches that
both define test_rejects_empty_row leave only the second and nothing reports
it. One file per batch is the reason that cannot happen, so the file naming is
tested too.

Default is off, and that matters: every published number was measured with one
call carrying the whole bar, so batching must not switch itself on.
"""
import os

import pytest

from qikly.agent_api import agent_interface as ai
from qikly.orchestrator import orchestrator as orch


# --------------------------------------------------------- the setting ----

def test_batching_is_off_in_the_shipped_defaults():
    """
    Read the bundled file, not the effective value: criteria_per_batch() also
    sees inputs_private/, so a developer running the experiment with batching
    on would make this test pass or fail depending on their own machine. It
    already did exactly that, which is how the setting reached the shipped
    defaults by accident.

    Off in the shipped file matters because turning it on multiplies
    generation cost for every user and invalidates comparison with every
    number this project has published.
    """
    import yaml

    from qikly.paths import PUBLIC_INPUTS_DIR

    path = os.path.join(PUBLIC_INPUTS_DIR, "config", "settings.yaml")
    with open(path, encoding="utf-8") as handle:
        bundled = yaml.safe_load(handle) or {}
    assert (bundled.get("test_generation") or {}).get("criteria_per_batch") == 0


def test_a_malformed_setting_falls_back_to_off(monkeypatch):
    """A typo in settings.yaml must not silently reshape every run."""
    for bad in ("", None, "many", [], {}):
        monkeypatch.setattr(orch, "load_settings",
                            lambda b=bad: {"test_generation": {"criteria_per_batch": b}})
        assert orch.criteria_per_batch() == 0


def test_a_missing_section_falls_back_to_off(monkeypatch):
    monkeypatch.setattr(orch, "load_settings", lambda: {})
    assert orch.criteria_per_batch() == 0
    monkeypatch.setattr(orch, "load_settings", lambda: {"test_generation": None})
    assert orch.criteria_per_batch() == 0


def test_a_positive_setting_is_read(monkeypatch):
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 4}})
    assert orch.criteria_per_batch() == 4


# ------------------------------------------------------------ batching ----

def test_batching_off_means_one_call_with_the_whole_bar():
    """None is the signal for "show the config untouched", not "show nothing"."""
    assert ai.criteria_batches("CALC_TAX", 0) == [None]
    assert ai.criteria_batches("CALC_TAX", None) == [None]


def test_a_batch_larger_than_the_bar_stays_a_single_call():
    """Splitting into one batch would cost a rewrite of the config for nothing."""
    n = len(ai.read_acceptance_criteria("CALC_TAX"))
    assert ai.criteria_batches("CALC_TAX", n) == [None]
    assert ai.criteria_batches("CALC_TAX", n + 5) == [None]


def test_every_criterion_survives_the_split():
    """
    The failure that matters: a dropped tail removes part of the bar from test
    generation and the run still goes green, just with fewer tests.
    """
    criteria = ai.read_acceptance_criteria("CALC_TAX")
    assert len(criteria) > 4, "this task should have a real bar to split"
    for size in (1, 2, 3, 5, 7):
        batches = ai.criteria_batches("CALC_TAX", size)
        flat = [c for b in batches for c in b]
        assert flat == criteria, f"criteria lost or reordered at batch size {size}"


def test_batches_are_the_requested_size_with_a_partial_tail():
    criteria = ai.read_acceptance_criteria("CALC_TAX")
    batches = ai.criteria_batches("CALC_TAX", 4)
    assert all(len(b) == 4 for b in batches[:-1])
    assert 1 <= len(batches[-1]) <= 4
    assert sum(len(b) for b in batches) == len(criteria)


def test_more_criteria_means_more_calls():
    """The entire point: a longer bar must cost more generation, not the same."""
    short = ai.criteria_batches("CALC_TAX", 3)
    assert len(short) > 1
    assert len(ai.criteria_batches("CALC_TAX", 2)) >= len(short)


# --------------------------------------------- the task text handed over ----

def test_the_whole_config_is_passed_through_when_criteria_is_none():
    raw = ai._read_task("CALC_TAX")
    assert ai._task_with_criteria("CALC_TAX", None) == raw


def test_only_the_named_criteria_reach_the_prompt():
    import yaml

    criteria = ai.read_acceptance_criteria("CALC_TAX")
    subset = criteria[:2]
    text = ai._task_with_criteria("CALC_TAX", subset)
    data = yaml.safe_load(text)
    assert data["acceptance_criteria"] == subset
    assert data["task_id"] == "CALC_TAX", "the rest of the spec must survive"
    assert data.get("requirements"), "requirements are what the tests are written from"


def test_awkward_criteria_text_still_produces_valid_yaml():
    """
    re.sub treats a string replacement as a template, so the backslash escapes
    json.dumps emits get reinterpreted: either a re.error or a real tab
    injected into the YAML. That accounted for 15 of 22 convergence failures
    on one run, all surfacing as a parser error with no hint of the cause.
    """
    import yaml

    nasty = [
        "rejects a value matching ^\\d{2,}$",
        'quotes: "double" and \'single\'',
        "a tab\there and a newline\nthere",
        "trailing backslash \\",
        "unicode: éü中",
        "- a leading dash",
        "colon: in the middle",
    ]
    text = ai._task_with_criteria("CALC_TAX", nasty)
    assert yaml.safe_load(text)["acceptance_criteria"] == nasty


def test_a_task_with_no_criteria_yields_no_batches_to_split():
    """Batching must not invent a bar where the task has none."""
    assert ai.criteria_batches("CALC_TAX", 0) == [None]


# ------------------------------------------------------- file per batch ----

def test_each_batch_is_written_to_its_own_file(tmp_path, monkeypatch):
    """
    Merging into one file silently drops same-named tests from later batches.
    Separate files are what make that impossible, so the naming is the
    behaviour under test.
    """
    calls = []

    def fake_generator(task_id, seed=None, criteria=None):
        calls.append(criteria)
        n = len(calls)
        return f"def test_generated_{n}():\n    assert True\n"

    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (fake_generator, "test_integration.py")})
    monkeypatch.setattr(orch, "criteria_per_batch", lambda: 3)
    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)

    orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1)

    written = sorted(os.listdir(tmp_path / "integration"))
    assert len(written) == len(calls) > 1
    assert written[0] == "test_integration_1.py"
    assert all(name.startswith("test_integration_") for name in written)


def test_a_single_batch_keeps_the_plain_filename(tmp_path, monkeypatch):
    """Batching off must leave the on-disk layout exactly as it was."""
    def fake_generator(task_id, seed=None, criteria=None):
        assert criteria is None, "the whole bar goes in one call when batching is off"
        return "def test_x():\n    assert True\n"

    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (fake_generator, "test_integration.py")})
    monkeypatch.setattr(orch, "criteria_per_batch", lambda: 0)
    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)

    orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1)
    assert os.listdir(tmp_path / "integration") == ["test_integration.py"]


def test_batches_do_not_all_get_the_same_seed(tmp_path, monkeypatch):
    """
    Generation is near-deterministic with a seed set. Handing every batch the
    same one invites the same file back several times over, which would look
    like the suite growing while covering nothing new.
    """
    seeds = []

    def fake_generator(task_id, seed=None, criteria=None):
        seeds.append(seed)
        return "def test_x():\n    assert True\n"

    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (fake_generator, "test_integration.py")})
    monkeypatch.setattr(orch, "criteria_per_batch", lambda: 3)
    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)

    orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=42)
    assert len(seeds) == len(set(seeds)), f"batches shared a seed: {seeds}"


def test_an_invalid_batch_still_raises_rather_than_writing_junk(tmp_path, monkeypatch):
    def broken(task_id, seed=None, criteria=None):
        return "def test_x(:\n    pass\n"

    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (broken, "test_integration.py")})
    monkeypatch.setattr(orch, "criteria_per_batch", lambda: 3)
    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="failed validation"):
        orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1)


# ------------------------------------------- disabling batching locally ----

def test_batching_can_be_disabled_for_one_convergence(monkeypatch):
    """
    A convergence whose only purpose is to produce code for a reviewer to read
    gains nothing from a bigger suite and can lose the whole round to the
    attempt budget. That is what happened to the refinement loop: with
    batching on it returned no new criteria on 14 of 24 attempts, against 3 of
    16 with it off.
    """
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 4}})
    assert orch.criteria_per_batch() == 4
    with orch.criteria_batching_disabled():
        assert orch.criteria_per_batch() == 0
    assert orch.criteria_per_batch() == 4, "the override must not leak"


def test_the_override_is_restored_even_if_the_body_raises(monkeypatch):
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 4}})
    with pytest.raises(RuntimeError):
        with orch.criteria_batching_disabled():
            raise RuntimeError("convergence failed")
    assert orch.criteria_per_batch() == 4


def test_nesting_restores_the_outer_value(monkeypatch):
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 6}})
    with orch.criteria_batching_disabled():
        with orch.criteria_batching_disabled():
            assert orch.criteria_per_batch() == 0
        assert orch.criteria_per_batch() == 0
    assert orch.criteria_per_batch() == 6


def test_the_refinement_loop_disables_batching_for_its_draft():
    """
    Guards the wiring, not just the mechanism. If this call site loses the
    context manager, refinement silently gets expensive and unreliable again
    and nothing fails.
    """
    import inspect

    from qikly.orchestrator.tuning import refine_acceptance_criteria as raf

    source = inspect.getsource(raf.refine)
    assert "criteria_batching_disabled()" in source
    assert "orchestrate(draft_id" in source


def test_a_batch_size_can_be_forced_for_one_arm(monkeypatch):
    """
    Holding suite size constant is the control that separates a stricter bar
    from a larger suite. It needs the two arms to run at different batch
    sizes, so the override has to take a value rather than only turning
    batching off.
    """
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 4}})
    with orch.criteria_batching(2):
        assert orch.criteria_per_batch() == 2
    assert orch.criteria_per_batch() == 4


def test_forcing_zero_is_the_same_as_disabling(monkeypatch):
    monkeypatch.setattr(orch, "load_settings",
                        lambda: {"test_generation": {"criteria_per_batch": 4}})
    with orch.criteria_batching(0):
        assert orch.criteria_per_batch() == 0
    assert orch.criteria_per_batch() == 4
