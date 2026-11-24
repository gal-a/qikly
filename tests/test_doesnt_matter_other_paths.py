"""
A file whose questions are answered "doesn't matter" must read the same on
every path, not as raw YAML where a bare `3` looks like a criterion:
--criteria-from, --explain and --generate-criteria.
"""
import os

import pytest

from qikly import cli, explain
from qikly.agent_api import agent_interface

DM = "doesn't matter, so no test for this"
OTHER = "other: write  N: <your sentence>, or just the sentence"


def _question(answer):
    return ("  #? What should f(2) do?\n"
            "  #?   1 = f(2) returns 2\n  #?   2 = f(2) returns 3\n"
            f"  #?   3 = {DM}\n  #?   4 = {OTHER}\n"
            f"  - {answer}\n")


def _write(root, *answers):
    path = root / "inputs_private" / "config" / "tasks" / "X_VERIFY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'task_id: "X_VERIFY"\ntask_name: "f"\ndescription: "f"\n'
        'requirements: "f returns its input"\n'
        'interface:\n  integration_functions: ["f"]\n'
        "acceptance_criteria:\n" + "".join(_question(a) for a in answers),
        encoding="utf-8")
    return path


def _write_bare(root):
    """A task file with no acceptance_criteria at all."""
    path = _write(root)
    text = path.read_text(encoding="utf-8")
    path.write_text(text[:text.index("acceptance_criteria:")], encoding="utf-8")
    return path


@pytest.fixture
def task(tmp_path, monkeypatch):
    from qikly.orchestrator import orchestrator

    def where(task_id):
        return str(tmp_path / "inputs_private" / "config" / "tasks" / (task_id + ".yaml"))
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    # The orchestrator imported its own reference to the function.
    monkeypatch.setattr(agent_interface, "task_config_path", where)
    monkeypatch.setattr(orchestrator, "task_config_path", where)
    return tmp_path


def test_criteria_from_names_the_decisions_not_a_bar_already_there(task, capsys):
    path = _write(task, "3")
    before = path.read_text(encoding="utf-8")
    assert cli._append_criteria_to_task("X_VERIFY", ["f(2) returns 2"]) == 2
    err = capsys.readouterr().err
    assert "already has acceptance_criteria" not in err
    assert "doesn't matter" in err
    assert path.read_text(encoding="utf-8") == before


def test_criteria_from_still_refuses_a_real_bar(task, capsys):
    _write(task, "1", "3")
    assert cli._append_criteria_to_task("X_VERIFY", ["x"]) == 2
    assert "already has acceptance_criteria" in capsys.readouterr().err


def test_explain_says_everything_is_decided_not_that_nothing_is_declared(task):
    _write(task, "3", "either")
    facts = explain.build("X_VERIFY")
    assert facts["criteria_count"] == 0 and facts["decided"] == 2
    text = explain.render(facts)
    assert "declares no acceptance_criteria" not in text
    assert "doesn't matter" in text


def test_explain_of_a_file_with_no_questions_is_unchanged(task):
    path = _write_bare(task)
    text = explain.render(explain.build("X_VERIFY"))
    assert "declares no acceptance_criteria" in text


def test_generate_criteria_never_writes_over_the_decisions(task, monkeypatch, capsys):
    from qikly.orchestrator import orchestrator
    path = _write(task, "3", "either")
    before = path.read_text(encoding="utf-8")

    def _no_call(*a, **k):
        raise AssertionError("a model would have been called")
    monkeypatch.setattr(agent_interface, "agent_generate_acceptance_criteria", _no_call)
    assert orchestrator.generate_and_write_acceptance_criteria_if_missing("X_VERIFY") is False
    assert path.read_text(encoding="utf-8") == before
    assert "nothing was generated" in capsys.readouterr().out


def test_generate_criteria_still_drafts_for_a_file_with_none(task, monkeypatch):
    from qikly.orchestrator import orchestrator
    path = _write_bare(task)
    monkeypatch.setattr(agent_interface, "agent_generate_acceptance_criteria",
                        lambda task_id, seed=None: ["f(1) returns 1"])
    monkeypatch.setattr(orchestrator, "private_input_path", lambda rel: str(path))
    assert orchestrator.generate_and_write_acceptance_criteria_if_missing("X_VERIFY") is True


def test_a_generating_run_of_an_all_decided_file_is_refused(task, monkeypatch, capsys):
    _write(task, "3", "3")
    monkeypatch.setattr("sys.argv", ["qikly", "--tasks", "X_VERIFY", "--generate-criteria"])
    monkeypatch.setattr("qikly.agent_api.providers.router.validate_config",
                        lambda: pytest.fail("the run went on"))
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2


def _write_value_question(root, *answers):
    """Two TODO items and then the given answers under a value question, the
    shape --scaffold writes for MAX_DISCOUNT_RATE."""
    path = root / "inputs_private" / "config" / "tasks" / "X_VERIFY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    todo = '  - "TODO: pick 1, 2, 3 or 4, or write your own"\n'
    path.write_text(
        'task_id: "X_VERIFY"\ntask_name: "f"\ndescription: "f"\n'
        'requirements: "f returns its input"\n'
        'interface:\n  integration_functions: ["f"]\n'
        "acceptance_criteria:\n" + todo + todo
        + "  #? Your tests pass whether this number is 100 or 101. What should it be?\n"
        "  #? Write a sentence that names the value, or the words  doesn't matter  "
        "to skip it.\n" + "".join(f"  - {a}\n" for a in answers),
        encoding="utf-8")
    return path


def test_criteria_from_never_overwrites_an_answer_that_was_refused(task, capsys):
    path = _write_value_question(task, "1")
    before = path.read_bytes()
    assert cli._append_criteria_to_task("X_VERIFY", ["a ticket criterion"]) == 2
    err = capsys.readouterr().err
    assert "could not be read" in err and "doesn't matter" in err
    assert path.read_bytes() == before


def test_criteria_from_still_replaces_a_file_of_only_todos(task, capsys):
    path = _write_value_question(task)
    path.write_text(path.read_text(encoding="utf-8").split("  #? Your tests")[0],
                    encoding="utf-8")
    assert cli._append_criteria_to_task("X_VERIFY", ["a ticket criterion"]) == 0
    assert "a ticket criterion" in path.read_text(encoding="utf-8")


def _write_mixed(root, answers):
    """Two questions: the given answers, in order, under the same options."""
    return _write(root, *answers)


def test_explain_of_a_mixed_file_does_not_say_every_question_is_doesnt_matter(task):
    _write_mixed(task, ["3", '"TODO: pick 1, 2, 3 or 4, or write your own"'])
    facts = explain.build("X_VERIFY")
    assert facts["criteria_count"] == 0 and facts["decided"] == 1
    text = explain.render(facts)
    assert "Every question" not in text
    assert "TODO" in text and "doesn't matter" in text
    assert "nothing to show" in text


def test_explain_of_an_all_decided_file_still_says_so(task):
    _write_mixed(task, ["3", "either"])
    text = explain.render(explain.build("X_VERIFY"))
    assert "Every question in X_VERIFY is answered" in text


def test_explain_reads_a_task_file_saved_in_the_old_local_encoding(task, monkeypatch):
    import locale
    path = _write(task, "3")
    text = path.read_text(encoding="utf-8").replace(
        "  #? What should f(2) do?", "  #? What should f(2) do for caf\u00e9?", 1)
    path.write_bytes(text.encode("cp1252"))
    monkeypatch.setattr(locale, "getpreferredencoding", lambda *a, **k: "cp1252")
    facts = explain.build("X_VERIFY")
    assert facts["decided"] == 1
    assert "Every question" in explain.render(facts)
