"""
Scoring a suite by breaking the code it judges.

The thing worth testing here is not that pytest runs. It is that the number
means what the report says it means: a control that refuses to score a suite
already failing, a caveat when the fixtures cannot reach the criteria, and a
miss reported as a question rather than a verdict.
"""
import io
import os

import pytest

from qikly import mutation_score as ms
from qikly.mutation import count_sites, make_mutant


SOURCE = (
    "def transform(rows):\n"
    "    out = []\n"
    "    for row in rows:\n"
    "        if float(row['gap_m']) < 0:\n"
    "            raise ValueError('negative')\n"
    "        out.append(row['gap_m'].strip())\n"
    "    return out\n"
)


def test_both_families_find_sites():
    """
    Arithmetic perturbs the logic, validation perturbs the strictness.

    They answer different questions and a score built on one alone would miss
    the fault class the other covers, which is why the shipped operators keep
    both rather than the classic set only.
    """
    assert count_sites(SOURCE, "arithmetic") >= 1
    assert count_sites(SOURCE, "validation") >= 2


def test_a_planted_fault_changes_the_source():
    mutant, described = make_mutant(SOURCE, 0, "validation")
    assert mutant is not None and mutant != SOURCE
    assert described


def test_sites_reports_family_and_description():
    found = ms.sites(SOURCE)
    assert found, "no mutation sites in a function with a guard and a compare"
    families = {family for family, _index, _described in found}
    # Both families have to be productive on this source, not merely allowed:
    # asserting the set is a subset of FAMILIES cannot fail, because `sites`
    # only ever iterates FAMILIES.
    assert families == {"arithmetic", "validation"}
    assert all(described for _f, _i, described in found)


def test_nothing_to_score_without_an_implementation(tmp_path):
    assert ms.score("NOPE", code_root=str(tmp_path)) is None


def test_a_suite_that_already_fails_is_not_scored(monkeypatch, tmp_path):
    """
    The control, and the reason the report has a `baseline` field.

    If the suite fails on the untouched code, every mutant "fails" too, for
    the reason the original does. Reporting 100% caught there would be the
    most flattering possible lie.
    """
    code = tmp_path / "T"
    code.mkdir()
    io.open(str(code / "impl.py"), "w", encoding="utf-8").write(SOURCE)

    monkeypatch.setattr(ms, "suite_dirs", lambda task_id, root=None: ["tests"])
    monkeypatch.setattr(ms, "_workspace", lambda *a, **k: str(tmp_path / "ws"))
    monkeypatch.setattr(ms, "_suite_passes", lambda *a, **k: False)
    monkeypatch.setattr(ms.shutil, "copy2", lambda *a, **k: None)

    result = ms.score("T", code_root=str(tmp_path))
    assert result["baseline"] is False
    assert result["caught"] == [] and result["missed"] == []
    assert "Not scored" in ms.render(result, [])


def test_a_suite_that_notices_everything_scores_full(monkeypatch, tmp_path):
    code = tmp_path / "T"
    code.mkdir()
    io.open(str(code / "impl.py"), "w", encoding="utf-8").write(SOURCE)

    calls = {"n": 0}

    def passes(*_a, **_k):
        # The first call is the control on untouched code; every later call is
        # a mutant, and a suite doing its job fails on those.
        calls["n"] += 1
        return calls["n"] == 1

    # A real workspace directory: mutants are written into it by a path
    # relative to the project, which is what stops them reaching the original.
    (tmp_path / "ws" / ms.CODE_ROOT / "T").mkdir(parents=True)

    monkeypatch.setattr(ms, "suite_dirs", lambda task_id, root=None: ["tests"])
    monkeypatch.setattr(ms, "_workspace", lambda *a, **k: str(tmp_path / "ws"))
    monkeypatch.setattr(ms, "_suite_passes", passes)
    monkeypatch.setattr(ms, "_suite_verdict",
                        lambda *a, **k: "pass" if passes() else "fail")
    monkeypatch.setattr(ms.shutil, "copy2", lambda *a, **k: None)
    monkeypatch.setattr(ms, "open", io.open, raising=False)

    result = ms.score("T", mutants=3, seed=1, code_root=str(tmp_path))
    assert result["baseline"] is True
    assert result["missed"] == []
    assert len(result["caught"]) == result["total"] >= 1
    total = result["total"]
    assert f"{total} of {total} planted faults caught (100%)" in ms.render(result, [])


def test_a_miss_is_named_in_the_report():
    result = {"task": "T", "baseline": True, "unscorable": 0, "total": 2,
              "caught": [{"file": "impl.py", "family": "arithmetic",
                          "change": "Lt -> LtE"}],
              "missed": [{"file": "impl.py", "family": "validation",
                          "change": "guard disabled"}]}
    text = ms.render(result, [])
    assert "1 of 2 planted faults caught (50%)" in text
    assert "guard disabled" in text
    assert "cannot be caught by any test" in text, "the equivalent-mutant caveat"


def test_unreachable_criteria_are_stated_above_the_score():
    """
    The dependency this feature was held behind, enforced in the report.

    Run this on fixtures that never exercise half the criteria and it returns
    roughly the two thirds missed that six experiments already returned. A
    reader would blame their suite for what belongs to their data, so the
    caveat goes above the number, not in a footnote.
    """
    result = {"task": "ADAS", "baseline": True, "unscorable": 0, "total": 4,
              "caught": [], "missed": []}
    gaps = [(2, "A gap_m of exactly 0 is rejected", ["0"], ["gap_m"])]
    text = ms.render(result, gaps)

    # Above the sections, not in a footnote: a reader who stops after the
    # number has still been told what the number does not mean.
    assert "## " not in text or text.index("never holds") < text.index("## ")
    assert "propose-fixtures --tasks ADAS" in text
    assert "about your fixtures, not your tests" in text


def test_an_unknown_reachability_is_said_rather_than_assumed():
    result = {"task": "T", "baseline": True, "unscorable": 0, "total": 1,
              "caught": [], "missed": []}
    text = ms.render(result, None)
    assert "could not be checked" in text


def test_the_report_says_nothing_of_yours_was_modified():
    result = {"task": "T", "baseline": True, "unscorable": 0, "total": 1,
              "caught": [], "missed": []}
    assert "nothing of yours was modified" in ms.render(result, [])


@pytest.mark.parametrize("stage", ["integration", "system"])
def test_suite_dirs_finds_each_stage(tmp_path, stage):
    root = tmp_path / "T" / stage
    root.mkdir(parents=True)
    found = ms.suite_dirs("T", root=str(tmp_path))
    assert any(stage in path for path in found)


def test_implementation_skips_dunder_files(tmp_path):
    code = tmp_path / "T"
    code.mkdir()
    for name in ("impl.py", "__init__.py", "notes.txt"):
        io.open(str(code / name), "w", encoding="utf-8").write("x = 1\n")
    found = ms.implementation("T", root=str(tmp_path))
    assert [os.path.basename(real) for real, _relative in found] == ["impl.py"]


# -------------------- what the audit found, kept from returning -------------

def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def test_a_mutant_never_reaches_the_real_file(tmp_path, monkeypatch):
    """
    The one that would have destroyed somebody's work.

    `implementation` used to return one path, and `score` wrote the mutant to
    `os.path.join(workspace, path)`. `os.path.join` discards everything before
    an absolute path, so with an absolute code root the mutant, and then its
    own restore, both landed on the user's real implementation. The module
    promises in two places that nothing of yours is modified.
    """
    code = tmp_path / "T"
    code.mkdir()
    real = code / "impl.py"
    io.open(str(real), "w", encoding="utf-8", newline="\n").write(SOURCE)

    workspace = tmp_path / "ws"
    (workspace / ms.CODE_ROOT / "T").mkdir(parents=True)

    monkeypatch.setattr(ms, "suite_dirs", lambda task_id, root=None: ["tests"])
    monkeypatch.setattr(ms, "_workspace", lambda *a, **k: str(workspace))
    monkeypatch.setattr(ms, "_suite_verdict", lambda *a, **k: "fail")
    monkeypatch.setattr(ms, "_suite_passes", lambda *a, **k: True)

    ms.score("T", mutants=4, seed=3, code_root=str(tmp_path))

    assert _read(str(real)) == SOURCE, "the user's own file was rewritten"
    assert (workspace / ms.CODE_ROOT / "T" / "impl.py").exists(), (
        "the mutant went somewhere other than the workspace")


def test_a_suite_that_cannot_run_is_not_credited_with_catching_anything(
        tmp_path, monkeypatch):
    """
    pytest returns 2 when it cannot collect, and that is not a catch.

    Reading every non-zero return code as "the suite noticed" credits a mutant
    that broke collection as a fault caught, when no assertion ever ran. It is
    the same situation as a mutant that fails to build, which was already
    counted as unscorable.
    """
    code = tmp_path / "T"
    code.mkdir()
    io.open(str(code / "impl.py"), "w", encoding="utf-8").write(SOURCE)

    (tmp_path / "ws" / ms.CODE_ROOT / "T").mkdir(parents=True)

    monkeypatch.setattr(ms, "suite_dirs", lambda task_id, root=None: ["tests"])
    monkeypatch.setattr(ms, "_workspace", lambda *a, **k: str(tmp_path / "ws"))
    # The baseline passes on untouched code; every mutant then makes pytest
    # fail to collect at all, which is the case under test.
    monkeypatch.setattr(ms, "_suite_passes", lambda *a, **k: True)
    monkeypatch.setattr(ms, "_suite_verdict", lambda *a, **k: "error")
    monkeypatch.setattr(ms.shutil, "copy2", lambda *a, **k: None)
    monkeypatch.setattr(ms, "open", io.open, raising=False)

    result = ms.score("T", mutants=3, seed=5, code_root=str(tmp_path))

    assert result["caught"] == [] and result["missed"] == []
    assert result["unscorable"] >= 1


def test_the_real_suite_runner_reads_pytest_s_three_outcomes(tmp_path, monkeypatch):
    """
    The subprocess path itself, which nothing else here exercises.

    Every other test replaces `_suite_verdict`, so without this the part that
    actually decides every score is never run.
    """
    workspace = tmp_path / "ws"
    stage = workspace / ms.TEST_ROOT / "T" / "integration"
    stage.mkdir(parents=True)
    relative = os.path.join(ms.TEST_ROOT, "T", "integration")
    # A Target rather than a task id: the module now carries what to run in
    # the object, so that one suite of checks serves both a qikly task and a
    # suite qikly never wrote.
    target = ms.Target(label="T", files=[], suites=[relative],
                       root=str(tmp_path), task_id="T")

    io.open(str(stage / "test_ok.py"), "w", encoding="utf-8").write(
        "def test_ok():\n    assert True\n")
    assert ms._suite_verdict(str(workspace), target) == "pass"

    io.open(str(stage / "test_ok.py"), "w", encoding="utf-8").write(
        "def test_ok():\n    assert False\n")
    assert ms._suite_verdict(str(workspace), target) == "fail"

    io.open(str(stage / "test_ok.py"), "w", encoding="utf-8").write(
        "import a_module_that_does_not_exist_anywhere\n")
    assert ms._suite_verdict(str(workspace), target) == "error"


def test_the_console_says_when_reachability_is_unknown(monkeypatch, capsys):
    """
    The caveat that vanished exactly when it mattered.

    The report explains an unknown reachability; the console printed nothing,
    so a user reading only the summary saw a clean percentage with no hint
    that the caveat could not be checked. The same silence follows any
    exception inside the reachability check, which swallows them by design.
    """
    monkeypatch.setattr(ms, "score", lambda *a, **k: {
        "task": "T", "baseline": True, "unscorable": 0, "total": 1,
        "caught": [{"file": "i.py", "family": "arithmetic", "change": "x"}],
        "missed": []})
    monkeypatch.setattr(ms, "unreachable_criteria", lambda task_id: None)
    monkeypatch.setattr(ms, "write", lambda *a, **k: "report.md")

    ms.run("T")

    assert "reachability could not be checked" in capsys.readouterr().out


def test_every_flag_the_score_handler_reads_exists_on_the_parser():
    """
    The bug two audits missed and one run found in a second.

    The dispatch read `args.seed`, no `--seed` flag existed, and
    `qikly --score-suite` died with AttributeError on its first line. Nothing
    caught it because every test called `score()` and `run()` directly and
    never the CLI path. This reads the dispatch with `ast`, collects every
    attribute it takes off `args`, and checks the parser defines each one.
    """
    import argparse
    import ast

    from qikly import cli

    tree = ast.parse(io.open(cli.__file__, encoding="utf-8").read())
    wanted = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_do_score_suite"):
            for argument in node.args:
                if (isinstance(argument, ast.Attribute)
                        and isinstance(argument.value, ast.Name)
                        and argument.value.id == "args"):
                    wanted.add(argument.attr)
    assert wanted, "found no call to _do_score_suite passing args attributes"

    captured = {}

    def grab(self, *a, **k):
        captured["parser"] = self
        raise SystemExit(0)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(argparse.ArgumentParser, "parse_args", grab)
        with pytest.raises(SystemExit):
            cli._parse_args()
    finally:
        monkey.undo()

    defined = {action.dest for action in captured["parser"]._actions}
    missing = sorted(name for name in wanted if name not in defined)
    assert not missing, (
        "--score-suite reads %s off args and the parser defines no such flag"
        % ", ".join(missing))
