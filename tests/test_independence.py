"""
The independence check answers one question: were the criteria settled before
the supplied code existed?

Every test here builds a real git repository in a temporary directory and
commits with fixed dates, because the thing under test is a claim about
history, and a fake history object would only prove that the fake was read
correctly.

The check must never raise. A run that has already produced code and a passing
suite cannot be failed by a note about itself, so the error paths are tested as
carefully as the happy one.
"""
import os
import subprocess

import pytest

from qikly import independence


def _git(args, cwd, when=None, who="t@example.com"):
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.run(
        ["git", "-c", "user.email=%s" % who, "-c", "user.name=T"] + args,
        cwd=str(cwd), env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    return path


def _commit(repo, name, text, when, who="t@example.com"):
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(["add", name], repo)
    _git(["commit", "-q", "-m", "add %s" % name], repo, when=when, who=who)
    return target


def test_criteria_committed_before_the_code_are_evidenced(tmp_path):
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "tasks/T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    code = _commit(repo, "src/calc.py", "def f():\n    return 1\n",
                   "2026-02-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(code))

    assert out["verdict"] == independence.CRITERIA_FIRST
    assert "2026-01-05" in out["detail"]
    assert "2026-02-05" in out["detail"]
    assert out["criteria_commit"] and out["implementation_commit"]
    assert out["criteria_last_changed"].startswith("2026-01-05")
    assert out["implementation_first_committed"].startswith("2026-02-05")


def test_code_that_came_first_is_not_evidenced(tmp_path):
    repo = _repo(tmp_path / "project")
    code = _commit(repo, "src/calc.py", "def f():\n    return 1\n",
                   "2026-01-05T09:00:00+00:00")
    criteria = _commit(repo, "tasks/T.yaml", "acceptance_criteria: []\n",
                       "2026-02-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(code))

    assert out["verdict"] == independence.NOT_EVIDENCED
    assert "with the code in view" in out["detail"]


def test_criteria_edited_after_the_code_lose_the_claim(tmp_path):
    """
    The conservative rule that matters most. The criteria were there first, but
    somebody changed the task file once the code existed, and from the outside
    there is no way to tell whether the change was shaped by what the code did.
    """
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "tasks/T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    code = _commit(repo, "src/calc.py", "def f():\n    return 1\n",
                   "2026-02-05T09:00:00+00:00")
    criteria.write_text("acceptance_criteria: [one]\n", encoding="utf-8")
    _git(["add", "tasks/T.yaml"], repo)
    _git(["commit", "-q", "-m", "revise"], repo, when="2026-03-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(code))

    assert out["verdict"] == independence.NOT_EVIDENCED
    assert "2026-03-05" in out["detail"]


def test_the_two_files_may_live_in_different_repositories(tmp_path):
    """A task kept beside the spec, code kept in the product repository."""
    specs = _repo(tmp_path / "specs")
    product = _repo(tmp_path / "product")
    criteria = _commit(specs, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    code = _commit(product, "calc.py", "def f():\n    return 1\n",
                   "2026-02-05T09:00:00+00:00")

    assert independence.check(str(criteria), str(code))["verdict"] == \
        independence.CRITERIA_FIRST


def test_a_directory_seed_is_dated_by_its_earliest_commit(tmp_path):
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    _commit(repo, "pkg/a.py", "a = 1\n", "2026-02-05T09:00:00+00:00")
    _commit(repo, "pkg/b.py", "b = 2\n", "2026-04-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(repo / "pkg"))

    assert out["verdict"] == independence.CRITERIA_FIRST
    assert out["implementation_first_committed"].startswith("2026-02-05")


def test_an_untracked_file_evidences_nothing(tmp_path):
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    loose = repo / "loose.py"
    loose.write_text("x = 1\n", encoding="utf-8")

    out = independence.check(str(criteria), str(loose))

    assert out["verdict"] == independence.NO_HISTORY
    assert "loose.py" in out["detail"]


def test_outside_a_repository_evidences_nothing(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    criteria = plain / "T.yaml"
    criteria.write_text("acceptance_criteria: []\n", encoding="utf-8")
    code = plain / "calc.py"
    code.write_text("x = 1\n", encoding="utf-8")

    out = independence.check(str(criteria), str(code))

    assert out["verdict"] == independence.NO_HISTORY
    assert "not inside a git repository" in out["detail"]


def test_an_unseeded_run_says_so_rather_than_claiming_nothing_is_known():
    """
    A run that generated its own code has the full guarantee, so "no history"
    here must not read as a shortfall. The sentence says which case it is.
    """
    out = independence.check("tasks/T.yaml", None)

    assert out["verdict"] == independence.NO_HISTORY
    assert "generated its own implementation" in out["detail"]


@pytest.mark.parametrize("criteria, code", [
    (None, None),
    ("", ""),
    ("no/such/file.yaml", "no/such/code.py"),
    ("\x00bad", "\x00bad"),
])
def test_it_never_raises(criteria, code):
    out = independence.check(criteria, code)
    assert out["verdict"] in independence.VERDICTS
    assert out["detail"]


def test_the_order_never_claims_the_author_had_not_read_them(tmp_path):
    """
    The correction that matters most. Criteria committed first rules out one
    failure (a bar written to fit code that already existed) and is the exact
    precondition of the other (a developer reading the criteria, then coding to
    them). A run that let the first be read as proof of withholding would be
    lying, so the limit travels with the finding.
    """
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00")
    code = _commit(repo, "calc.py", "x = 1\n", "2026-02-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(code))

    assert out["verdict"] == independence.CRITERIA_FIRST
    assert "do not show whether the code's author read them" in out["limit"]
    # The other half: a commit date is not a writing date. Code can have been
    # sitting in a working tree while the criteria were being written against
    # it, so this verdict narrows that threat rather than closing it.
    assert "exist uncommitted" in out["limit"]


def test_one_person_on_both_sides_is_reported_as_such(tmp_path):
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00", who="one@example.com")
    code = _commit(repo, "calc.py", "x = 1\n",
                   "2026-02-05T09:00:00+00:00", who="one@example.com")

    out = independence.check(str(criteria), str(code))

    assert out["same_author"] is True
    assert out["criteria_author"] == "one@example.com"
    assert "rests on your process" in out["limit"]


def test_two_people_are_reported_as_the_separation_the_method_asks_for(tmp_path):
    repo = _repo(tmp_path / "project")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-01-05T09:00:00+00:00", who="spec@example.com")
    code = _commit(repo, "calc.py", "x = 1\n",
                   "2026-02-05T09:00:00+00:00", who="dev@example.com")

    out = independence.check(str(criteria), str(code))

    assert out["same_author"] is False
    assert out["implementation_author"] == "dev@example.com"
    assert "different people" in out["limit"]


def test_an_unevidenced_order_also_carries_its_limit(tmp_path):
    repo = _repo(tmp_path / "project")
    code = _commit(repo, "calc.py", "x = 1\n", "2026-01-05T09:00:00+00:00")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-02-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(code))

    assert out["limit"]


def test_a_renamed_implementation_is_dated_from_before_its_rename(tmp_path):
    """
    The failure this nearly shipped with. `git log -- path` stops at a rename,
    so a module moved into src/ long after it was written reports the move as
    its first commit. Criteria written in between would then read as settled
    first, which is the reassuring verdict taken from the wrong history.
    """
    repo = _repo(tmp_path / "project")
    _commit(repo, "calc.py", "x = 1\n", "2026-01-05T09:00:00+00:00")
    criteria = _commit(repo, "T.yaml", "acceptance_criteria: []\n",
                       "2026-02-05T09:00:00+00:00")
    (repo / "src").mkdir()
    _git(["mv", "calc.py", "src/calc.py"], repo)
    _git(["commit", "-q", "-m", "move into src"], repo,
         when="2026-03-05T09:00:00+00:00")

    out = independence.check(str(criteria), str(repo / "src" / "calc.py"))

    assert out["implementation_first_committed"].startswith("2026-01-05")
    assert out["verdict"] == independence.NOT_EVIDENCED


def test_the_console_puts_the_limit_on_its_own_line():
    """
    The bounds must not be reachable only by opening the HTML report, since
    the console is where the run is actually read.
    """
    lines = independence.console_lines("T", EVENT)

    assert len(lines) == 2
    assert lines[0].startswith("[T] Criteria committed before this implementation:")
    assert "do not show whether the code's author read them" in lines[1]


def test_the_console_says_one_line_when_there_is_nothing_to_bound():
    out = independence.check("tasks/T.yaml", None)
    assert len(independence.console_lines("T", out)) == 1


def test_the_scaffolded_task_file_makes_the_narrow_claim(tmp_path):
    """
    The text a user reads in their own task file is the one place this claim
    can quietly widen, because nothing else in the codebase quotes it. It
    drifted once already, saying the criteria "cannot have been fitted to the
    code" with no mention of what git actually witnesses.
    """
    from qikly import scaffold

    text = scaffold.SEED_EXISTING

    assert "already in the repository" in text
    assert "uncommitted" in text
    assert "cannot have been fitted to the code" not in text


def test_only_a_seeded_implementation_triggers_the_check():
    """
    Seeding just the tests leaves qikly writing the implementation, where the
    separation is enforced and there is nothing to evidence.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator)
    assert source.count("check_independence(") == 1
    assert source.index("if seed_implementation:") < source.index("check_independence(")


def test_every_verdict_has_a_headline():
    for verdict in independence.VERDICTS:
        assert independence.HEADLINES[verdict]


def test_a_missing_git_is_reported_as_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(independence, "_git", lambda args, cwd: None)
    out = independence.check(str(tmp_path / "T.yaml"), str(tmp_path / "c.py"))
    assert out["verdict"] == independence.UNAVAILABLE


# --------------------------------------------------------------------------
# Wiring: a verdict is worth nothing in a variable. These pin the path from
# the run's log to the two places a person actually reads.
# --------------------------------------------------------------------------

EVENT = {
    "ts": "2026-09-16T10:00:00",
    "action": "criteria_independence",
    "verdict": "criteria_first",
    "headline": "Criteria committed before this implementation",
    "detail": "the criteria were last changed on 2026-01-05, before this "
              "implementation's first commit on 2026-02-05, so they were not "
              "written against code that was already in the repository",
    "limit": "it evidences the order of two commits, not of two acts: code can "
             "exist uncommitted long before its first commit, and criteria "
             "committed first do not show whether the code's author read them. "
             "The two sides were committed by different people "
             "(spec@example.com and dev@example.com), which is the separation "
             "the method asks for.",
    "criteria_file": "config/tasks/T.yaml",
    "implementation": "src/calc.py",
    "criteria_last_changed": "2026-01-05T09:00:00+00:00",
    "criteria_commit": "abc1234",
    "criteria_author": "spec@example.com",
    "implementation_first_committed": "2026-02-05T09:00:00+00:00",
    "implementation_commit": "def5678",
    "implementation_author": "dev@example.com",
    "same_author": False,
}


def test_the_event_reaches_the_summary_without_its_log_plumbing():
    from qikly.orchestrator.reports.report import build_blocks, compute_summary

    summary = compute_summary(build_blocks([EVENT]))
    carried = summary["criteria_independence"]

    assert carried["verdict"] == "criteria_first"
    # "ts" and "action" belong to the log, not to the finding.
    assert "ts" not in carried and "action" not in carried and "type" not in carried


def test_an_unseeded_run_carries_nothing():
    from qikly.orchestrator.reports.report import build_blocks, compute_summary

    summary = compute_summary(build_blocks([
        {"action": "test_run", "stage": "integration", "status": "pass"}]))

    assert summary["criteria_independence"] is None


def test_the_report_shows_the_sentence_and_marks_it_settled():
    from qikly.orchestrator.reports.report import build_blocks, compute_summary, _summary_html

    summary = compute_summary(build_blocks([EVENT]))
    html_text = _summary_html("T", "20260916_100000", summary, {})

    assert "Criteria committed before this implementation" in html_text
    assert "2026-01-05" in html_text
    assert "evidence-ok" in html_text
    # The claim must not be rendered without its bounds.
    assert "evidence-limit" in html_text
    assert "do not show whether the code's author read them" in html_text


def test_the_report_marks_an_unevidenced_order_differently():
    from qikly.orchestrator.reports.report import build_blocks, compute_summary, _summary_html

    event = dict(EVENT, verdict="not_evidenced", headline="Order not evidenced")
    summary = compute_summary(build_blocks([event]))
    html_text = _summary_html("T", "20260916_100000", summary, {})

    assert "evidence-open" in html_text
    assert "evidence-ok" not in html_text


def test_a_run_that_generated_its_own_code_says_nothing_in_the_report():
    from qikly.orchestrator.reports.report import build_blocks, compute_summary, _summary_html

    summary = compute_summary(build_blocks([]))
    html_text = _summary_html("T", "20260916_100000", summary, {})

    assert "independence" not in html_text


def test_the_run_summary_json_records_it(tmp_path, monkeypatch):
    """
    The JSON is what a sweep reads back months later, so the evidence has to
    survive into it rather than living only in HTML a person has to open.
    """
    import json

    from qikly.orchestrator import run_summary

    monkeypatch.chdir(tmp_path)
    logs = tmp_path / "outputs" / "logs"
    logs.mkdir(parents=True)
    (logs / "transactions_T_20260916_100000.jsonl").write_text(
        json.dumps(EVENT) + "\n" + json.dumps({"action": "all_tests_passed"}) + "\n",
        encoding="utf-8")

    payload = run_summary.build_payload("T", "20260916_100000")

    assert payload["schema_version"] == 6
    assert payload["criteria_independence"]["verdict"] == "criteria_first"
    assert payload["criteria_independence"]["criteria_commit"] == "abc1234"


def test_the_orchestrator_asks_only_when_the_implementation_was_supplied():
    """
    An unseeded run enforces the separation rather than evidencing it, so the
    check must sit inside the seeded branch. Pinned at the source, because the
    alternative is a live run with a provider key.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator)
    where = source.index("if seed_implementation:")
    nearby = source[where:where + 700]
    assert "check_independence" in nearby
    assert "criteria_independence" in nearby
