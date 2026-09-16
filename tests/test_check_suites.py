"""
Tests for the check that generated suites can be passed at all.

Measured on a following-distance task, 2026-09-15: in seven of ten runs the
test-writing agent generated a test that warned at exactly 2.00 seconds of
headway, against a criterion saying it does not, and all seven runs failed.
The coding agent sees only failure output, so it cannot tell a wrong test from
a right one; the check has to happen between test generation and the first
line of code.

The properties pinned here are the ones that keep an advisory check from
becoming a new way for runs to fail: it never raises, it tolerates any reply
shape, it rewrites a suite at most once, and its guidance reaches test
generation and nothing else.
"""
import os

import pytest

from qikly.orchestrator.tuning import check_suites as cs


# ---------------------------------------------------------------- parsing ---

def test_a_plain_json_array_is_read():
    out = cs.parse_findings(
        '[{"suite": "integration", "test": "test_warn", "conflicts_with": "c", "why": "w"}]')
    assert out == [{"suite": "integration", "test": "test_warn", "conflicts_with": "c", "why": "w"}]


def test_a_fenced_block_and_surrounding_prose_are_tolerated():
    out = cs.parse_findings('Here:\n```json\n[{"test": "t"}]\n```\nDone.')
    assert out and out[0]["test"] == "t"


def test_an_empty_array_means_the_suites_agree():
    assert cs.parse_findings("[]") == []


def test_the_object_the_prompt_asks_for_is_read_from_its_findings():
    """The limits list comes first in the object and must not be taken for findings."""
    raw = ('{"limits": [{"limit": "2.00 s", "at_the_limit": "warning false"}], '
           '"findings": [{"suite": "system", "test": "test_warn", "why": "w"}]}')
    out = cs.parse_findings(raw)
    assert [f["test"] for f in out] == ["test_warn"]


def test_an_object_with_no_findings_means_the_suites_agree():
    assert cs.parse_findings('{"limits": [{"limit": "250 m"}], "findings": []}') == []
    assert cs.parse_findings('```json\n{"limits": []}\n```') == []


def test_the_prompt_asks_for_the_limits_before_the_tests():
    """
    Measured: asked only to look for contradictions, the check missed three of
    seven suites where every suite made the same boundary mistake.
    """
    p = cs.build_prompt(["r"], ["c"], [])
    assert p.index("STEP 1, THE LIMITS") < p.index("STEP 2, THE TESTS")
    assert "agreement between suites proves nothing" in p


def test_unparseable_output_yields_nothing_rather_than_raising():
    for bad in ("", None, "no json here", "[oops]", '{"test": "t"}', 12):
        assert cs.parse_findings(bad) == []


def test_entries_without_a_test_are_dropped():
    assert len(cs.parse_findings('[{"why": "no test"}, {"test": "t"}]')) == 1


def test_a_test_named_as_suite_and_name_is_split():
    out = cs.parse_findings('[{"test": "system::test_two_second_rule"}]')
    assert out[0]["suite"] == "system" and out[0]["test"] == "test_two_second_rule"


def test_a_quoted_criterion_does_not_carry_the_prompts_bullet():
    out = cs.parse_findings('[{"test": "t", "conflicts_with": "- exactly 2.00 gives false"}]')
    assert out[0]["conflicts_with"] == "exactly 2.00 gives false"


# ----------------------------------------------------------------- prompt ---

SUITE = ("integration", "test_integration.py",
         "def test_warn():\n    rows = {'a': 1}\n    assert f'{rows}'\n")


def test_the_prompt_carries_the_spec_and_every_suite():
    p = cs.build_prompt(["req one"], ["crit one"], [SUITE], "what it is for")
    assert "req one" in p and "crit one" in p and "what it is for" in p
    assert "=== integration: test_integration.py ===" in p
    assert "def test_warn" in p


def test_braces_in_test_source_do_not_break_the_prompt():
    """Generated tests are full of dict literals and f-strings."""
    assert "{rows}" in cs.build_prompt(["r"], ["c"], [SUITE])


def test_the_prompt_makes_boundaries_explicit():
    """
    The measured failures were all at a stated limit: `<` against `<=`. Without
    naming that, a reviewer reads the comparison as a detail.
    """
    p = cs.build_prompt(["r"], ["c"], [SUITE])
    assert "BOUNDARIES" in p and "`<` against `<=`" in p
    assert "exactly at" in p


def test_the_prompt_asks_for_test_against_test():
    p = cs.build_prompt(["r"], ["c"], [SUITE])
    assert "DIFFERENT RESULTS FOR THE SAME INPUT" in p


def test_the_prompt_rules_out_coverage_complaints():
    """A checker that reports missing tests would fire on every suite."""
    p = cs.build_prompt(["r"], ["c"], [SUITE])
    assert "missing tests" in p and "NO correct implementation" in p


def test_empty_sections_still_produce_a_readable_prompt():
    assert "(none)" in cs.build_prompt([], [], [])


# ---------------------------------------------------------------- sources ---

def _write_suite(tests_dir, stage, name="test_x.py", source="def test_a():\n    assert True\n"):
    d = os.path.join(tests_dir, stage)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as handle:
        handle.write(source)


def test_suite_sources_reads_only_python_files_for_the_stages_asked(tmp_path):
    _write_suite(str(tmp_path), "integration")
    _write_suite(str(tmp_path), "system", "test_s.py")
    _write_suite(str(tmp_path), "unit", "test_u.py")
    (tmp_path / "integration" / "notes.txt").write_text("not a test")
    found = cs.suite_sources(str(tmp_path), ("integration", "system"))
    assert [(stage, name) for stage, name, _ in found] == [
        ("integration", "test_x.py"), ("system", "test_s.py")]


# ------------------------------------------------------------------ check ---

@pytest.fixture
def project_root():
    from qikly.paths import chdir_to_project_root
    chdir_to_project_root()


def test_check_sends_the_suites_under_their_own_mode(monkeypatch, tmp_path, project_root):
    seen = {}
    import qikly.agent_api.call_llm as m

    def capture(mode, prompt, **kwargs):
        seen["mode"], seen["prompt"] = mode, prompt
        return '[{"suite": "integration", "test": "test_a", "why": "w"}]'

    monkeypatch.setattr(m, "call_llm", capture)
    _write_suite(str(tmp_path), "integration")
    out = cs.check("CALC_TAX", str(tmp_path))
    assert seen["mode"] == "suite_consistency"
    assert "def test_a" in seen["prompt"]
    assert "line items" in seen["prompt"], "CALC_TAX's own description"
    assert out[0]["test"] == "test_a"


def test_a_provider_failure_returns_no_findings_rather_than_raising(monkeypatch, tmp_path, project_root):
    import qikly.agent_api.call_llm as m

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(m, "call_llm", boom)
    _write_suite(str(tmp_path), "integration")
    assert cs.check("CALC_TAX", str(tmp_path)) == []


def test_no_suites_on_disk_means_no_call(monkeypatch, tmp_path, project_root):
    called = []
    import qikly.agent_api.call_llm as m
    monkeypatch.setattr(m, "call_llm", lambda *a, **k: called.append(1))
    assert cs.check("CALC_TAX", str(tmp_path)) == []
    assert called == []


def test_a_task_with_no_criteria_is_skipped_without_a_call(monkeypatch, tmp_path):
    called = []
    import qikly.agent_api.call_llm as m
    monkeypatch.setattr(m, "call_llm", lambda *a, **k: called.append(1))
    _write_suite(str(tmp_path), "integration")
    assert cs.check("NO_SUCH_TASK_AT_ALL", str(tmp_path)) == []
    assert called == []


# ---------------------------------------------------- reporting, guidance ---

FINDING = {"suite": "integration", "test": "test_integration_pipeline_flow",
           "conflicts_with": "A time headway of exactly 2.00 seconds gives warning false",
           "why": "a 2.00 s headway is asserted to warn"}


def test_the_report_names_the_test_the_conflict_and_the_reason(capsys):
    assert cs.report("T", [FINDING]) == 1
    out = capsys.readouterr().out
    assert "integration::test_integration_pipeline_flow" in out
    assert "exactly 2.00 seconds" in out and "asserted to warn" in out
    assert "advisory" in out


def test_a_clean_report_says_the_suites_agree(capsys):
    assert cs.report("T", []) == 0
    assert "agree" in capsys.readouterr().out


def test_guidance_names_the_test_and_the_boundary_rule():
    g = cs.guidance_for("integration", [FINDING])
    assert "test_integration_pipeline_flow" in g
    assert "exactly 2.00 seconds" in g
    assert "exactly at a stated limit" in g


def test_guidance_for_a_suite_leaves_out_another_suites_findings():
    other = dict(FINDING, suite="system", test="test_other")
    g = cs.guidance_for("integration", [FINDING, other])
    assert "test_integration_pipeline_flow" in g and "test_other" not in g


# ---------------------------------------------------- orchestrator wiring ---

import qikly.orchestrator.orchestrator as orch


@pytest.fixture
def no_log(monkeypatch):
    monkeypatch.setattr(orch, "SAVE_TRANSACTIONS", False)


def test_agreeing_suites_cost_one_check_and_no_rewrite(no_log):
    calls, rewrites = [], []
    remaining = orch.check_and_repair_suites(
        "T", "tests", ["integration", "system"],
        checker=lambda *a, **k: calls.append(1) or [],
        regenerate=lambda *a, **k: rewrites.append(a),
        printer=lambda *a: None)
    assert remaining == [] and len(calls) == 1 and rewrites == []


def test_a_finding_rewrites_only_the_suite_named_with_guidance_then_checks_once_more(no_log):
    results = [[FINDING], []]
    rewrites = []

    def regenerate(stage, tests_dir, task_id, seed=None, guidance=None):
        rewrites.append((stage, seed, guidance))

    remaining = orch.check_and_repair_suites(
        "T", "tests", ["integration", "system"], seed=42,
        checker=lambda *a, **k: results.pop(0),
        regenerate=regenerate, printer=lambda *a: None)
    assert remaining == [] and results == []
    assert [stage for stage, _, _ in rewrites] == ["integration"]
    stage, seed, guidance = rewrites[0]
    assert seed == 42 + orch.REGENERATION_SEED_OFFSET, "a same-seed rewrite repeats the file"
    assert "test_integration_pipeline_flow" in guidance


def test_a_finding_that_names_no_suite_rewrites_every_generated_suite(no_log):
    results = [[dict(FINDING, suite="")], []]
    rewrites = []
    orch.check_and_repair_suites(
        "T", "tests", ["integration", "system"],
        checker=lambda *a, **k: results.pop(0),
        regenerate=lambda stage, *a, **k: rewrites.append(stage), printer=lambda *a: None)
    assert rewrites == ["integration", "system"]


def test_a_persisting_finding_is_reported_and_the_run_continues(no_log):
    """At most one rewrite, and never an exception: the check is advice."""
    rewrites, lines = [], []
    remaining = orch.check_and_repair_suites(
        "T", "tests", ["integration"],
        checker=lambda *a, **k: [FINDING],
        regenerate=lambda stage, *a, **k: rewrites.append(stage), printer=lines.append)
    assert remaining == [FINDING]
    assert rewrites == ["integration"]
    assert any("still disagree" in line for line in lines)


def test_the_check_is_off_unless_settings_turn_it_on():
    """
    Off on measurement: a ten-run sweep with it on converged 4 in 10 against 3
    without, and one wrong finding led a correct suite to be rewritten wrong.
    """
    assert orch.suite_check_enabled({}) is False
    assert orch.suite_check_enabled({"test_generation": {"check_suites": True}}) is True
    assert orch.suite_check_enabled(orch.load_settings()) is False, "the bundled default"


def test_guidance_is_passed_to_a_generator_only_when_there_is_some(tmp_path, no_log, monkeypatch):
    """Stand-in generators written without a guidance parameter keep working."""
    seen = []

    def old_style(task_id, seed=None, criteria=None):
        seen.append("old")
        return "def test_a():\n    assert True\n"

    def new_style(task_id, seed=None, criteria=None, guidance=None):
        seen.append(guidance)
        return "def test_a():\n    assert True\n"

    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (old_style, "test_integration.py")})
    orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1)
    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (new_style, "test_integration.py")})
    orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1, guidance="fix it")
    assert seen == ["old", "fix it"]


def test_guidance_reaches_the_test_generation_prompt_and_its_mode(monkeypatch):
    import qikly.agent_api.agent_interface as ai
    seen = {}

    def capture(mode, prompt, seed=None):
        seen["mode"], seen["prompt"] = mode, prompt
        return "def test_a():\n    assert True\n"

    monkeypatch.setattr(ai, "call_llm", capture)
    from qikly.paths import chdir_to_project_root
    chdir_to_project_root()
    ai.agent_generate_integration_tests("CALC_TAX", guidance="GUIDANCE-MARKER")
    assert seen["mode"] == "test_integration"
    assert seen["prompt"].endswith("GUIDANCE-MARKER")


# ------------------------------------------------------- the stop message ---

def test_alternating_tests_in_two_suites_are_named_in_the_hint():
    trail = [("system", ("test_two_second_rule",)),
             ("integration", ("test_pipeline_flow",)),
             ("system", ("test_two_second_rule",))]
    hint = orch._disagreement_hint(trail)
    assert "test_two_second_rule" in hint and "test_pipeline_flow" in hint
    assert "'system' and 'integration' suites" in hint
    assert "two generated tests expect different results" in hint


def test_alternating_tests_in_one_suite_are_named_too():
    trail = [("integration", ("a",)), ("integration", ("b",)), ("integration", ("a",))]
    assert "in the 'integration' suite" in orch._disagreement_hint(trail)


def test_the_same_failure_repeating_is_not_a_disagreement():
    """That is a hard case or a decision in the criteria, not two tests at odds."""
    trail = [("integration", ("a",))] * 3
    assert orch._disagreement_hint(trail) is None


def test_too_short_or_empty_trails_give_no_hint():
    assert orch._disagreement_hint([("s", ("a",)), ("s", ("b",))]) is None
    assert orch._disagreement_hint([("s", ()), ("s", ("b",)), ("s", ())]) is None


def test_the_router_sends_the_check_to_the_review_agent():
    from qikly.agent_api.providers import router as R
    assert R._MODE_ROLE["suite_consistency"] == "review"
