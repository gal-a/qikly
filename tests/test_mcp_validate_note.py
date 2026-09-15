"""
The qikly_validate reply says what it did not check.

Found 2026-09-15 by watching a real host: asked to run qikly_validate on
CALC_TAX in VS Code, GitHub Copilot relayed the right counts, valid true, 0
errors, 2 warnings, and then summarised them as "no contradictions", which that
tool never looks for. The tool description already said so, but a host
summarises the reply it received, not the description it read at startup, so
the disclaimer has to travel in the reply.
"""
from qikly import mcp_tools


def test_the_validate_reply_names_the_contradiction_check():
    note = mcp_tools.qikly_validate("CALC_TAX")["note"]
    assert "does not look for contradictions" in note
    assert "--check-criteria" in note


def test_the_note_still_quotes_no_criterion():
    import yaml
    from qikly.agent_api.agent_interface import task_config_path

    with open(task_config_path("CALC_TAX"), encoding="utf-8") as handle:
        criteria = (yaml.safe_load(handle) or {}).get("acceptance_criteria") or []
    note = mcp_tools.qikly_validate("CALC_TAX")["note"]
    assert criteria, "CALC_TAX should declare criteria for this check to mean anything"
    for criterion in criteria:
        assert criterion not in note
