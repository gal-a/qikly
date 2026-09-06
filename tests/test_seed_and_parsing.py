"""
Seed installation, seed validation, and the parsers that read model output.

The seed guard exists because a seeded suite that collects nothing passes
vacuously: pytest reports "no tests ran", the loop reads that as success, and
the run converges against nothing at all. The parsers are pinned because a
regex that drops the last item in a list is invisible until you count.
"""
import os

import pytest

from qikly.agent_api import agent_interface as ai
from qikly.orchestrator import orchestrator as orch


# ----------------------------------------------------------------- seeds ----
def test_seeded_suite_with_no_test_function_is_rejected(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text("def helper():\n    return 1\n", encoding="utf-8")
    with pytest.raises(Exception):
        orch.validate_seed_tests("unit", [str(p)])


def test_seeded_suite_that_does_not_parse_is_rejected(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text("def test_a(:\n", encoding="utf-8")
    with pytest.raises(Exception):
        orch.validate_seed_tests("unit", [str(p)])


def test_seeded_suite_with_a_real_test_is_accepted(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    orch.validate_seed_tests("unit", [str(p)])


def test_helpers_alongside_a_test_file_are_allowed(tmp_path):
    """A seeded directory may legitimately split helpers out from tests."""
    (tmp_path / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    t = tmp_path / "test_x.py"
    t.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    orch.validate_seed_tests("unit", [str(tmp_path / "helpers.py"), str(t)])


def test_install_seed_copies_a_single_file(tmp_path):
    src = tmp_path / "calc.py"
    src.write_text("X = 1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    installed = orch.install_seed(str(src), str(dest))
    assert installed
    assert any(os.path.basename(p) == "calc.py" for p in installed)


def test_install_seed_copies_a_directory(tmp_path):
    src = tmp_path / "suite"
    src.mkdir()
    (src / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (src / "test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
    dest = tmp_path / "dest"
    installed = orch.install_seed(str(src), str(dest))
    assert len(installed) == 2


def test_install_seed_reports_a_missing_source(tmp_path):
    with pytest.raises(Exception):
        orch.install_seed(str(tmp_path / "nope.py"), str(tmp_path / "dest"))


# ---------------------------------------------------------------- parsing ---
def test_criteria_list_keeps_the_final_item():
    """The regression: a lookahead requiring a blank line dropped the last one."""
    text = '- "first criterion"\n- "second criterion"\n- "third and final criterion"'
    got = ai._extract_criteria_list(text)
    assert len(got) == 3
    assert "final" in got[-1]


def test_criteria_list_survives_a_trailing_newline():
    text = '- "one"\n- "two"\n'
    assert len(ai._extract_criteria_list(text)) == 2


def test_tagged_criteria_keep_their_category_and_final_item():
    text = ('- [parsing_looseness] accepts scientific notation\n'
            '- [silent_failure] skips a missing file\n'
            '- [internal_consistency] strips on accept but not on reject')
    got = ai._extract_tagged_criteria_list(text)
    assert len(got) == 3


def test_target_files_are_extracted_from_a_fix():
    fix = ("Root cause: rounding.\n"
           "target_files:\n"
           "  - outputs/agent_src/code/CALC_TAX/calc.py\n"
           "  - outputs/agent_src/code/CALC_TAX/util.py\n")
    got = ai._extract_target_files(fix)
    assert len(got) == 2
    assert all(g.endswith(".py") for g in got)


def test_absent_target_files_yields_nothing_rather_than_raising():
    """The loader falls back to the whole codebase; it must not crash first."""
    assert not ai._extract_target_files("Root cause: rounding. No file list here.")
