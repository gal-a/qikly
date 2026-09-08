"""
Three integrations, and the seams that keep them testable.

Each of these reaches outside the project: Jira over HTTP, run history across
time, and a workflow that runs on somebody else's CI. All three are the kind of
feature that rots quietly, so each is built with the interesting behaviour in a
pure function and the fragile part reduced to as little as possible.

The Jira module is the clearest case. `parse_issue` is a dict in and criteria
out, so every case worth getting right is tested here with no network. What is
left to break when Atlassian changes something is one GET.
"""
import json
import os

import pytest

from qikly import jira, pr_comment
from qikly.orchestrator.reports import trend_report


# ================================================================ jira ======

def _issue(description=None, fields=None):
    payload = {"fields": {"description": description}}
    payload["fields"].update(fields or {})
    return payload


def test_a_plain_description_with_a_criteria_heading():
    criteria, where = jira.parse_issue(_issue(
        "Some background.\n\n## Acceptance Criteria\n- one\n- two\n"))
    assert criteria == ["one", "two"]
    assert where == "description"


def test_a_named_field_wins_over_the_description():
    """
    A dedicated field is unambiguous where it exists, so it is checked first.
    The description often contains background that reads like criteria.
    """
    criteria, where = jira.parse_issue(
        _issue("- background bullet", {"customfield_10038": "- the real rule"}),
        field_names={"customfield_10038": "Acceptance Criteria"})
    assert criteria == ["the real rule"]
    assert where == "Acceptance Criteria"


def test_a_custom_field_id_is_never_guessed_at():
    """
    Field ids differ per Jira instance, so a hardcoded customfield_10038 is
    wrong everywhere except where it was written. Without the name map, the
    field is ignored and the description is used, which is the safe fallback:
    the alternative is reading an arbitrary field into somebody's bar.
    """
    criteria, where = jira.parse_issue(
        _issue("- from the description", {"customfield_10038": "- from a field"}))
    assert criteria == ["from the description"]
    assert where == "description"


def test_a_field_with_a_different_name_is_not_treated_as_criteria():
    criteria, _ = jira.parse_issue(
        _issue("- real one", {"customfield_1": "- a QA note"}),
        field_names={"customfield_1": "QA Notes"})
    assert criteria == ["real one"]


def test_atlassian_document_format_becomes_text_the_parser_understands():
    """
    Modern Jira returns a nested JSON tree, not a string. The heading has to
    survive the flattening, because finding a criteria section is the whole
    reason the text is being rebuilt.
    """
    adf = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Acceptance Criteria"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "first rule"}]}]},
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "second rule"}]}]},
        ]},
    ]}
    text = jira.adf_to_text(adf)
    assert "Acceptance Criteria" in text
    criteria, _ = jira.parse_issue({"fields": {"description": adf}})
    assert criteria == ["first rule", "second rule"]


def test_an_issue_with_no_criteria_returns_nothing_rather_than_prose():
    """
    Same restraint as the file importer. A rule nobody wrote is the invented
    standard this project argues against, and a ticket description is mostly
    prose.
    """
    criteria, _ = jira.parse_issue(_issue(
        "This should merge the files correctly and handle errors sensibly."))
    assert criteria == []


def test_an_empty_or_malformed_payload_does_not_raise():
    assert jira.parse_issue(None) == ([], "description")
    assert jira.parse_issue({}) == ([], "description")
    assert jira.parse_issue({"fields": {}}) == ([], "description")


def test_missing_credentials_name_which_ones(monkeypatch):
    """
    The most common first failure. "401" would be true and useless; naming the
    variable that is unset is what a person can act on.
    """
    for name in (jira.ENV_BASE_URL, jira.ENV_EMAIL, jira.ENV_TOKEN):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError) as caught:
        jira.fetch_issue("PROJ-1")
    message = str(caught.value)
    assert jira.ENV_BASE_URL in message and jira.ENV_TOKEN in message


def test_only_one_function_here_opens_a_socket():
    """
    The seam this module exists around. If network code spreads beyond
    `_get`, the tested surface shrinks and the fragile surface grows.
    """
    import inspect

    source = inspect.getsource(jira)
    assert source.count("urlopen") == 1


def test_the_same_parser_serves_both_importers():
    """
    A ticket pasted into a file and the same ticket fetched over the API must
    produce identical criteria, or there are two behaviours to maintain and one
    of them is always the stale one.
    """
    import inspect

    assert "from qikly.criteria_import import parse_criteria" in inspect.getsource(jira)


# =============================================================== trends =====

def _summary(tmp_path, task, stamp, passed, model="m", batch=0):
    (tmp_path / f"{task}_{stamp}.json").write_text(json.dumps({
        "schema_version": 4, "task_id": task, "run_timestamp": stamp,
        "passed_overall": passed,
        "provenance": {"model": model, "criteria_per_batch": batch,
                       "max_retries_per_stage": 10},
    }), encoding="utf-8")


def test_runs_are_bucketed_in_time_order(tmp_path):
    _summary(tmp_path, "T", "20260101_000000", True)
    _summary(tmp_path, "T", "20260201_000000", False)
    rows = trend_report.collect(grain="month", summary_dir=str(tmp_path))["T"]
    assert [r["period"] for r in rows] == ["2026-01", "2026-02"]
    assert rows[0]["rate"] == 1.0 and rows[1]["rate"] == 0.0


def test_a_settings_change_is_marked_between_periods(tmp_path):
    """
    The most expensive mistake this project has made was reading a change in a
    rate as a change in the tool, when a stale criteria_per_batch had tripled
    every suite. A trend line invites that mistake more strongly than a single
    rate does, so a period where the configuration moved says so.
    """
    _summary(tmp_path, "T", "20260101_000000", True, batch=0)
    _summary(tmp_path, "T", "20260201_000000", False, batch=4)
    rows = trend_report.collect(grain="month", summary_dir=str(tmp_path))["T"]
    assert trend_report._config_changed(rows) == [False, True]
    assert "changed here" in trend_report.render({"T": rows}, "month")


def test_an_unchanged_configuration_is_not_marked(tmp_path):
    _summary(tmp_path, "T", "20260101_000000", True)
    _summary(tmp_path, "T", "20260201_000000", False)
    rows = trend_report.collect(grain="month", summary_dir=str(tmp_path))["T"]
    assert trend_report._config_changed(rows) == [False, False]


def test_no_trend_line_is_drawn(tmp_path):
    """
    A proportion from a small sample shows a slope whatever is happening, and
    printing a direction would manufacture a finding from noise. The intervals
    are printed instead.
    """
    for i, passed in enumerate([True, True, False, False]):
        _summary(tmp_path, "T", f"2026010{i+1}_000000", passed)
    text = trend_report.render(
        trend_report.collect(grain="day", summary_dir=str(tmp_path)), "day")
    for verdict in ("improving", "declining", "getting worse", "upward", "downward"):
        assert verdict not in text.lower()
    assert "no trend line is drawn" in text.lower()
    assert "intervals" in text


def test_every_period_carries_its_interval(tmp_path):
    _summary(tmp_path, "T", "20260101_000000", True)
    rows = trend_report.collect(grain="day", summary_dir=str(tmp_path))["T"]
    assert rows[0]["ci_low"] is not None and rows[0]["ci_high"] is not None


def test_no_history_says_so_rather_than_rendering_an_empty_table():
    assert "no history" in trend_report.render({}, "day").lower()


def test_an_unreadable_summary_is_skipped_not_fatal(tmp_path):
    _summary(tmp_path, "T", "20260101_000000", True)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert trend_report.collect(grain="day", summary_dir=str(tmp_path))["T"]


# =========================================================== pr comment =====

def _payload(task, passed, stages, model="gemini-3.5-flash-lite"):
    return {"schema_version": 4, "task_id": task, "run_timestamp": "20260101_000000",
            "passed_overall": passed, "stage_iterations": stages,
            "provenance": {"model": model, "criteria_per_batch": 0,
                           "qikly_version": "0.1.0"}}


def test_a_converged_run_says_so_in_the_first_line():
    body = pr_comment.render([_payload("T", True, {"integration": 2, "unit": 3})])
    assert body.splitlines()[2].startswith("**T converged.**")


def test_a_stall_names_the_stage_it_stopped_in():
    """The most useful fact in a failed run, and the reason to read further."""
    body = pr_comment.render([_payload("T", False, {"integration": 2, "system": 1})])
    assert "`system`" in body


def test_a_stall_is_framed_as_an_outcome_not_a_broken_build():
    body = pr_comment.render([_payload("T", False, {"integration": 9})])
    assert "normal outcome" in body


def test_several_tasks_render_as_a_table():
    body = pr_comment.render([_payload("A", True, {"unit": 1}),
                              _payload("B", False, {"integration": 4})])
    assert "1 of 2 task(s) converged" in body
    assert "| `A` |" in body and "| `B` |" in body


def test_the_model_and_settings_are_named():
    """A convergence result belongs to a configuration as much as to a tool."""
    body = pr_comment.render([_payload("T", True, {"unit": 1})])
    assert "gemini-3.5-flash-lite" in body
    assert "criteria_per_batch" in body


def test_the_cost_is_not_in_the_comment():
    """
    A dollar figure in a public PR comment on every push starts an argument
    that has nothing to do with the code. It is in the run summary.
    """
    body = pr_comment.render([_payload("T", True, {"unit": 1})])
    assert "$" not in body


def test_no_summary_produces_an_honest_line_rather_than_silence():
    assert "nothing" in pr_comment.render([]).lower()


def test_only_the_newest_run_per_task_is_reported(tmp_path):
    """
    A repository running this for months would otherwise produce a comment
    nobody could scroll.
    """
    for stamp, passed in (("20260101_000000", False), ("20260301_000000", True)):
        (tmp_path / f"T_{stamp}.json").write_text(
            json.dumps(_payload("T", passed, {"unit": 1})
                       | {"run_timestamp": stamp}), encoding="utf-8")
    runs = pr_comment.latest_runs(summary_dir=str(tmp_path))
    assert len(runs) == 1
    assert runs[0]["run_timestamp"] == "20260301_000000"


# ============================================== the PR workflow template ====

def test_the_pr_workflow_validates_before_it_spends():
    """
    --validate is free and catches a broken task file. Running the paid step
    first would bill for a run that could not have worked.
    """
    import yaml

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".github", "workflows", "qikly-pr-example.yml"),
              encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)

    steps = workflow["jobs"]["qikly"]["steps"]
    names = [s.get("name", "") + s.get("uses", "") + s.get("run", "") for s in steps]
    validate_at = next(i for i, n in enumerate(names) if "--validate" in n)
    from qikly.version_check import GITHUB_REPO

    run_at = next(i for i, n in enumerate(names) if f"{GITHUB_REPO}@" in n)
    assert validate_at < run_at, "the free check must come before the paid run"


def test_the_pr_workflow_updates_one_comment_rather_than_adding_many():
    """A pull request with fourteen bot comments is one nobody reads."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".github", "workflows", "qikly-pr-example.yml"),
              encoding="utf-8") as handle:
        text = handle.read()
    assert "updateComment" in text
    assert "qikly-run" in text, "the marker that finds the previous comment"


def test_the_pr_workflow_asks_for_the_least_permission_it_needs():
    import yaml

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".github", "workflows", "qikly-pr-example.yml"),
              encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "write"}
