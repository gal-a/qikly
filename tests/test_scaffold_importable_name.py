"""
A file whose name is not a Python name still produces a task that can run.

`--scaffold my-calc.py` wrote `module: "outputs.agent_src.code.MY_CALC_VERIFY.
my-calc"`, which no test can import: a dash is fine in a filename and not in
an import. The module path now uses an importable name, and a run copies the
seeded file in under that same name, so the path and the file agree. The
user's own file is never renamed.
"""
import importlib.util
import os

import pytest

from qikly.orchestrator.orchestrator import install_seed, seed_filename
from qikly.scaffold import importable, module_path


@pytest.mark.parametrize("stem, name", [
    ("my-calc", "my_calc"),
    ("my calc", "my_calc"),
    ("2fast", "_2fast"),
    ("class", "class_"),
    ("pricing", "pricing"),
])
def test_a_stem_becomes_a_name_python_can_import(stem, name):
    assert importable(stem) == name
    assert importable(stem).isidentifier()


def test_the_scaffolded_module_path_is_importable():
    path = module_path("/x/my-calc.py", "MY_CALC_VERIFY")
    assert path == "outputs.agent_src.code.MY_CALC_VERIFY.my_calc"
    assert all(part.isidentifier() for part in path.split("."))


def test_an_ordinary_name_is_left_alone(tmp_path):
    (tmp_path / "pricing.py").write_text("x = 1\n", encoding="utf-8")
    assert seed_filename(str(tmp_path / "pricing.py")) is None


def test_a_package_is_never_renamed(tmp_path):
    (tmp_path / "my-pkg").mkdir()
    assert seed_filename(str(tmp_path / "my-pkg")) is None


def test_the_seed_goes_in_under_the_name_the_module_path_uses(tmp_path):
    source = tmp_path / "my-calc.py"
    source.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    dest = tmp_path / "agent_src"
    installed = install_seed(str(source), str(dest),
                             filename=seed_filename(str(source)))
    assert [os.path.basename(p) for p in installed] == ["my_calc.py"]
    assert source.exists(), "the user's own file must keep its name"

    spec = importlib.util.spec_from_file_location("my_calc", installed[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.add(2, 3) == 5
