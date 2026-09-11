"""
Tests for the specification contradiction check.

Stall cause one in the write-up is a criterion that no implementation can
satisfy alongside the requirements: the loop then produces changes that fix
the test and break the spec, or the reverse, until the budget runs out. The
remedy was named in the article and never built until now.

Two properties are load bearing. The check must never raise, because it is
advice and the run is the work: a provider hiccup here must not stop a run
that would otherwise have gone ahead. And it must tolerate whatever shape the
model replies in, because a checker that dies on a fenced code block is a new
way for runs to fail rather than a way to stop them failing.
"""
import pytest

from qikly.orchestrator.tuning import check_criteria as cc


# ---------------------------------------------------------------- parsing ---

def test_a_plain_json_array_is_read():
    out = cc.parse_findings(
        '[{"criterion": "c", "conflicts_with": "r", "why": "w"}]')
    assert out == [{"criterion": "c", "conflicts_with": "r", "why": "w"}]


def test_a_fenced_block_is_read():
    out = cc.parse_findings('```json\n[{"criterion": "c"}]\n```')
    assert out and out[0]["criterion"] == "c"


def test_prose_around_the_array_is_tolerated():
    out = cc.parse_findings('Sure! Here you go:\n[{"criterion": "c"}]\nHope that helps.')
    assert out and out[0]["criterion"] == "c"


def test_an_empty_array_means_no_contradictions():
    assert cc.parse_findings("[]") == []


def test_unparseable_output_yields_nothing_rather_than_raising():
    """A malformed reply must not become a new way for a run to die."""
    for bad in ("", None, "not json at all", "{", "[oops]", "{\"a\": 1}"):
        assert cc.parse_findings(bad) == []


def test_entries_without_a_criterion_are_dropped():
    out = cc.parse_findings('[{"why": "no criterion named"}, {"criterion": "c"}]')
    assert len(out) == 1


def test_a_quoted_statement_does_not_carry_the_prompts_bullet():
    """
    The statements go in as "- <statement>", so a model quoting one back
    faithfully returns the bullet too, and it reads as part of the sentence.
    """
    out = cc.parse_findings(
        '[{"criterion": "- fail below 2.5 m", '
        '"conflicts_with": "- fail below 2 m", "why": "w"}]')
    assert out[0]["criterion"] == "fail below 2.5 m"
    assert out[0]["conflicts_with"] == "fail below 2 m"


# ----------------------------------------------------------------- prompt ---

def test_the_prompt_carries_both_halves():
    p = cc.build_prompt(["req one"], ["crit one"])
    assert "req one" in p and "crit one" in p


def test_the_prompt_rules_out_the_normal_relationship():
    """
    A criterion being stricter than a requirement is the intended design, not
    a fault. Without saying so the check reports every criterion in the task.
    """
    p = cc.build_prompt(["r"], ["c"])
    assert "qualitatively stricter" in p
    assert "NO possible implementation" in p


def test_empty_sections_still_produce_a_readable_prompt():
    assert "(none)" in cc.build_prompt([], [])


def test_the_prompt_asks_for_criterion_against_criterion():
    """
    Two criteria can be unsatisfiable together with no requirement involved,
    and the check looked only at criteria against requirements, so it could
    not represent that finding let alone report it.
    """
    p = cc.build_prompt(["r"], ["c"])
    assert "ANOTHER CRITERION" in p
    assert "OTHER CRITERION" in p, "the output schema has to allow it too"


def test_the_prompt_exempts_numeric_thresholds_from_the_stricter_rule():
    """
    The suppression that swallowed a real fault. "Fails below 2 m" against
    "fails below 2.5 m" reads as merely stricter and is a typo: the two
    disagree about every value in the band between them.
    """
    p = cc.build_prompt(["r"], ["c"])
    assert "NUMERIC THRESHOLDS" in p
    assert "SAME quantity" in p


def test_the_description_reaches_the_prompt():
    p = cc.build_prompt(["r"], ["c"], "what this task is for")
    assert "what this task is for" in p


def test_a_missing_description_does_not_break_the_prompt():
    assert "(none)" in cc.build_prompt(["r"], ["c"])
    assert "(none)" in cc.build_prompt(["r"], ["c"], None)


def test_check_passes_the_tasks_description_through(monkeypatch):
    """The description is read off the task file, not left behind in it."""
    seen = {}
    import qikly.agent_api.call_llm as m

    def capture(agent, prompt, **kwargs):
        seen["prompt"] = prompt
        return "[]"

    monkeypatch.setattr(m, "call_llm", capture)
    from qikly.paths import chdir_to_project_root
    chdir_to_project_root()
    cc.check("CALC_TAX")
    assert "DESCRIPTION:" in seen["prompt"]
    assert "line items" in seen["prompt"], "CALC_TAX's own description"


# ---------------------------------------------------------------- reporting -

def test_a_clean_spec_reports_nothing_found(capsys):
    n = cc.report("T", [])
    assert n == 0
    assert "no contradictions found" in capsys.readouterr().out


def test_findings_are_printed_with_both_sides_and_the_reason(capsys):
    n = cc.report("T", [{"criterion": "reject 0", "conflicts_with": "accept all",
                         "why": "cannot both"}])
    out = capsys.readouterr().out
    assert n == 1
    assert "reject 0" in out and "accept all" in out and "cannot both" in out


def test_the_report_says_it_is_advisory(capsys):
    """
    A model judging whether two English sentences can both hold is not
    reliable enough to be obeyed, so the output must not read like a verdict.
    """
    cc.report("T", [{"criterion": "c", "conflicts_with": "r", "why": "w"}])
    out = capsys.readouterr().out
    assert "advisory" in out and "nothing has been changed" in out


# ------------------------------------------------------------------ check ---

def test_a_provider_failure_returns_no_findings_rather_than_raising(monkeypatch):
    import qikly.agent_api.call_llm as m

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(m, "call_llm", boom)
    assert cc.check("CALC_TAX") == []


def test_a_task_with_no_criteria_is_skipped_without_a_call(monkeypatch):
    called = []
    import qikly.agent_api.call_llm as m
    monkeypatch.setattr(m, "call_llm", lambda *a, **k: called.append(1))
    assert cc.check("NO_SUCH_TASK_AT_ALL") == []
    assert called == []
