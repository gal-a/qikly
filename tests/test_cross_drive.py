"""
A module on a different drive from the project, on Windows.

os.path.relpath raises ValueError across drives instead of answering. That
broke `--scaffold` and the MCP `qikly_scaffold` tool for any module on another
drive, and it is how GitHub's Windows runners are laid out by default: the
checkout on D:, temporary directories on C:. The first sign was CI failing on
Windows only. Simulated here by making relpath raise, so it runs everywhere.
"""
import os

import yaml

from qikly import cli, scaffold

MODULE = "def run_billing(input_paths, output_path):\n    pass\n"


def _no_relative_path(*args, **kwargs):
    raise ValueError("path is on mount 'D:', start on mount 'C:'")


def test_scaffold_builds_a_task_for_a_module_on_another_drive(tmp_path, monkeypatch):
    module = tmp_path / "billing.py"
    module.write_text(MODULE, encoding="utf-8")
    monkeypatch.setattr(scaffold.os.path, "relpath", _no_relative_path)
    text, problem = scaffold.build_task(str(module), str(tmp_path / "project"),
                                        seed="existing")
    assert problem is None
    task = yaml.safe_load(text)
    assert task["interface"]["module"] == "billing", "named by its file"
    implementation = task["seed"]["implementation"]
    assert os.path.isabs(implementation), "a seed on another drive has to be absolute"
    assert implementation.endswith("billing.py")


def test_a_module_on_the_same_drive_keeps_its_relative_paths(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    module = project / "src" / "billing.py"
    module.write_text(MODULE, encoding="utf-8")
    task = yaml.safe_load(scaffold.build_task(str(module), str(project), seed="existing")[0])
    assert task["interface"]["module"] == "src.billing"
    assert task["seed"]["implementation"] == "src/billing.py"


def test_the_cli_prints_a_path_on_another_drive_rather_than_crashing(monkeypatch):
    monkeypatch.setattr(cli.os.path, "relpath", _no_relative_path)
    assert cli.shown("D:/work/billing.py", "C:/project") == "D:/work/billing.py"
