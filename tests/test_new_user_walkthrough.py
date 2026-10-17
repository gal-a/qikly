"""
Messages fixed after a new-user walkthrough of the landing page's three steps
on 2026-10-15, each at a point where the user's obvious next move went wrong.
"""
import os

import pytest

from qikly import cli
import qikly.mutation_score as ms


def test_scaffold_on_an_unscored_folder_says_to_score_it(tmp_path, monkeypatch, capsys):
    """
    `--scaffold` on a folder writes a task per module its score asked about;
    with no score yet it says so, and names a module to scaffold instead.
    """
    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "__init__.py").write_text("", encoding="utf-8")
    (shop / "shipping.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("shop", None) == 2
    out = capsys.readouterr().out
    assert "no such file" not in out
    assert "is a folder" in out and "shipping.py" in out
    assert "__init__.py" not in out


def test_scoring_a_generated_suite_against_your_file_points_at_score_suite(tmp_path):
    """
    The suite qikly wrote imports its own copy of the code, so scoring it
    against the user's file never runs that file. The message blamed an
    installed package, which is not what happened.
    """
    (tmp_path / "shipping.py").write_text("def f(x):\n    return x + 1\n",
                                          encoding="utf-8")
    tests = tmp_path / "outputs" / "tests" / "SHIPPING_VERIFY" / "system"
    tests.mkdir(parents=True)
    copy = tmp_path / "outputs" / "agent_src" / "code" / "SHIPPING_VERIFY"
    copy.mkdir(parents=True)
    for d in ("outputs", "outputs/agent_src", "outputs/agent_src/code",
              "outputs/agent_src/code/SHIPPING_VERIFY"):
        (tmp_path / d / "__init__.py").write_text("", encoding="utf-8")
    (copy / "shipping.py").write_text("def f(x):\n    return x + 1\n",
                                      encoding="utf-8")
    (tests / "test_system.py").write_text(
        "from outputs.agent_src.code.SHIPPING_VERIFY.shipping import f\n\n"
        "def test_f():\n    assert f(1) == 2\n", encoding="utf-8")
    target = ms.from_paths(str(tmp_path / "shipping.py"),
                           str(tmp_path / "outputs" / "tests" / "SHIPPING_VERIFY"))
    with pytest.raises(ms.NeverRan) as raised:
        ms.score(target, mutants=3, seed=1)
    message = str(raised.value)
    assert "qikly --score-suite --tasks SHIPPING_VERIFY" in message
    assert "installed copy" not in message


def test_a_folder_score_says_the_faults_were_shared(tmp_path, monkeypatch, capsys):
    target = ms.Target("shop", [("a.py", "a.py"), ("b.py", "b.py")], ["tests"],
                       str(tmp_path))
    result = {"task": "shop", "baseline": True, "caught": [], "missed": [],
              "unscorable": 0, "total": 12, "generated": False,
              "site_files": 2, "sites": 30}
    monkeypatch.setattr(ms, "score", lambda *a, **k: result)
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: [])
    ms.run(target, invoked_from=str(tmp_path))
    out = capsys.readouterr().out
    assert "spread at random over 2 files" in out
    assert "--score-mutants 30" in out, "capped at the sites there are"


def test_a_single_file_score_says_nothing_about_sharing(tmp_path, monkeypatch, capsys):
    target = ms.Target("a.py", [("a.py", "a.py")], ["tests"], str(tmp_path))
    result = {"task": "a.py", "baseline": True, "caught": [], "missed": [],
              "unscorable": 0, "total": 12, "generated": False}
    monkeypatch.setattr(ms, "score", lambda *a, **k: result)
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: [])
    ms.run(target, invoked_from=str(tmp_path))
    assert "spread at random" not in capsys.readouterr().out


# ------------------------------------------- found by the audit, 2026-10-15 --

def test_the_folder_note_counts_files_with_sites_and_offers_more_only_if_left(
        tmp_path, monkeypatch, capsys):
    """
    The note is for a sample: with every site planted, as `--score` now
    does unless the suite is slow, nothing was spread and nothing is left.
    """
    target = ms.Target("lib", [("a.py", "a.py"), ("b.py", "b.py"),
                               ("c.py", "c.py")], ["tests"], str(tmp_path))
    result = {"task": "lib", "baseline": True, "caught": [], "missed": [],
              "unscorable": 0, "total": 3, "generated": False,
              "site_files": 1, "sites": 3}
    monkeypatch.setattr(ms, "score", lambda *a, **k: result)
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: [])
    ms.run(target, invoked_from=str(tmp_path))
    assert "spread at random" not in capsys.readouterr().out
    result.update(site_files=2)
    ms.run(target, invoked_from=str(tmp_path))
    assert "spread at random" not in capsys.readouterr().out
    result.update(site_files=2, sites=10)
    ms.run(target, invoked_from=str(tmp_path))
    out = capsys.readouterr().out
    assert "over 2 files" in out and "--score-mutants" in out


def test_a_comment_naming_the_generated_path_is_not_an_import(tmp_path):
    suite = tmp_path / "tests"
    suite.mkdir()
    (suite / "test_x.py").write_text(
        "# like outputs.agent_src.code.OLD_TASK.pricing tests\n"
        "def test_x():\n    assert True\n", encoding="utf-8")
    target = ms.Target("x", [], ["tests"], str(tmp_path))
    assert ms._generated_suite_task(target) is None
    (suite / "test_x.py").write_text(
        "from outputs.agent_src.code.NEW_TASK.pricing import f\n",
        encoding="utf-8")
    assert ms._generated_suite_task(target) == "NEW_TASK"


def test_percentages_round_and_the_two_report_lines_sum_to_100():
    assert ms.headline(2, 3) == "1 of 3 planted faults missed (33%), 2 caught"
    assert ms.headline(7, 12) == "5 of 12 planted faults missed (42%), 7 caught"
    result = {"task": "T", "baseline": True, "unscorable": 0, "total": 3,
              "caught": [{"file": "a.py", "family": "f", "change": "c"}] * 2,
              "missed": [{"file": "a.py", "family": "f", "change": "m"}]}
    text = ms.render(result, [])
    assert "(67%).**" in text and "(33%).**" in text


def test_the_folder_hint_skips_tests_and_quotes_a_spaced_path(
        tmp_path, monkeypatch, capsys):
    code = tmp_path / "my code" / "pkg"
    code.mkdir(parents=True)
    for name in ("conftest.py", "test_pricing.py", "setup.py", "pricing.py"):
        (code / name).write_text("def f(x):\n    return x\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("my code", None) == 2
    out = capsys.readouterr().out
    assert 'qikly --scaffold "' in out and "pricing.py" in out
    for name in ("conftest.py", "test_pricing.py", "setup.py"):
        assert name not in out


def test_new_tests_are_named_only_for_a_task_on_your_own_code(
        monkeypatch, capsys):
    from qikly.orchestrator import orchestrator
    monkeypatch.setattr(orchestrator, "load_seed_spec",
                        lambda task_id: (None, {}))
    cli._say_where_the_new_tests_are("CALC_TAX")
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(orchestrator, "load_seed_spec",
                        lambda task_id: ("shipping.py", {}))
    monkeypatch.setattr(cli, "inside_a_demo", lambda where=None: None)
    cli._say_where_the_new_tests_are("SHIPPING_VERIFY")
    out = capsys.readouterr().out
    assert "Your new tests:" in out
    assert "qikly --score-suite --tasks SHIPPING_VERIFY" in out
    assert "integration and system" in out
    monkeypatch.setattr(cli, "inside_a_demo", lambda where=None: "demo/x")
    cli._say_where_the_new_tests_are("SHIPPING_VERIFY")
    assert capsys.readouterr().out == ""
