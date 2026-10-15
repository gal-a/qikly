"""
Messages fixed after a new-user walkthrough of the landing page's three steps
on 2026-10-15, each at a point where the user's obvious next move went wrong.
"""
import os

import pytest

from qikly import cli
import qikly.mutation_score as ms


def test_scaffold_on_a_folder_says_it_takes_one_file(tmp_path, monkeypatch, capsys):
    """`--score-code` takes a folder, so `--scaffold` on it is the next try."""
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
              "unscorable": 0, "total": 12, "generated": False}
    monkeypatch.setattr(ms, "score", lambda *a, **k: result)
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: [])
    ms.run(target, invoked_from=str(tmp_path))
    out = capsys.readouterr().out
    assert "spread at random over 2 files" in out
    assert "--score-mutants 48" in out


def test_a_single_file_score_says_nothing_about_sharing(tmp_path, monkeypatch, capsys):
    target = ms.Target("a.py", [("a.py", "a.py")], ["tests"], str(tmp_path))
    result = {"task": "a.py", "baseline": True, "caught": [], "missed": [],
              "unscorable": 0, "total": 12, "generated": False}
    monkeypatch.setattr(ms, "score", lambda *a, **k: result)
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: [])
    ms.run(target, invoked_from=str(tmp_path))
    assert "spread at random" not in capsys.readouterr().out
