"""
A task file whose every question was answered "doesn't matter" has no
criterion a run could test, so a run must refuse it as it refuses all-TODO.
The guard used to read the raw YAML, where a bare `3` or `either` looks like
an answer, and let the run start (and spend money) on nothing.
"""
import pytest

from qikly import cli

DM = "doesn't matter, so no test for this"
OTHER = "other: write  N: <your sentence>, or just the sentence"


def _question(answer):
    return (
        "  #? Your tests pass whether f(2) is 2 or 3. What should f(2) do?\n"
        "  #?   1 = f(2) returns 2\n"
        "  #?   2 = f(2) returns 3\n"
        f"  #?   3 = {DM}\n"
        f"  #?   4 = {OTHER}\n"
        f"  - {answer}\n")


def _todo():
    return _question('"TODO: pick 1, 2, 3 or 4, or write your own"')


def _file(tmp_path, monkeypatch, *answers_or_blocks):
    path = tmp_path / "X_VERIFY.yaml"
    path.write_text("task_id: X_VERIFY\nacceptance_criteria:\n"
                    + "".join(answers_or_blocks), encoding="utf-8")
    from qikly.agent_api import agent_interface
    monkeypatch.setattr(agent_interface, "task_config_path", lambda task_id: str(path))
    return path


@pytest.mark.parametrize("answer", ["3", "either", "no preference", "it doesn't matter"])
def test_every_question_answered_doesnt_matter_is_all_todo(tmp_path, monkeypatch, answer):
    _file(tmp_path, monkeypatch, _question(answer), _question(answer))
    assert cli._all_todo(["X_VERIFY"]) == ["X_VERIFY"]


def test_one_doesnt_matter_among_todos_is_all_todo(tmp_path, monkeypatch):
    _file(tmp_path, monkeypatch, _question("3"), _todo(), _todo())
    assert cli._all_todo(["X_VERIFY"]) == ["X_VERIFY"]


def test_one_real_answer_is_not_all_todo(tmp_path, monkeypatch):
    _file(tmp_path, monkeypatch, _question("3"), _question("1"), _todo())
    assert cli._all_todo(["X_VERIFY"]) == []


def test_a_file_without_criteria_is_not_all_todo(tmp_path, monkeypatch):
    path = _file(tmp_path, monkeypatch)
    path.write_text("task_id: X_VERIFY\n", encoding="utf-8")
    assert cli._all_todo(["X_VERIFY"]) == []


@pytest.mark.parametrize("blocks", [
    (_question("3"), _question("either")),
    (_question("3"), _todo(), _todo()),
], ids=["all-doesnt-matter", "one-plus-todos"])
def test_the_run_is_refused_before_anything_is_spent(
        tmp_path, monkeypatch, capsys, blocks):
    _file(tmp_path, monkeypatch, *blocks)
    reached = []
    monkeypatch.setattr("qikly.agent_api.providers.router.validate_config",
                        lambda: reached.append("config"))
    monkeypatch.setattr("sys.argv", ["qikly", "--tasks", "X_VERIFY"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert not reached, "the run went on to its provider check"
    assert "X_VERIFY" in capsys.readouterr().err
