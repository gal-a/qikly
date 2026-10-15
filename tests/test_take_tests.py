"""
`qikly --take-tests`: a run's tests, copied into the user's own tests and
rewritten to import the user's module rather than qikly's copy of it.
"""
import os

import yaml

from qikly import take_tests

CODE = "def apply_discount(price, rate):\n    if rate < 0 or rate > 100:\n        raise ValueError\n    return price * (1 - rate / 100)\n"


def _project(tmp_path, implementation="pricing.py", module=None):
    (tmp_path / "pricing.py").write_text(CODE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text(
        "from pricing import apply_discount\n\ndef test_a():\n"
        "    assert apply_discount(100, 10) == 90\n")
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "PRICING_VERIFY.yaml").write_text(yaml.safe_dump({
        "task_id": "PRICING_VERIFY",
        "interface": {"module": module or "outputs.agent_src.code.PRICING_VERIFY.pricing"},
        "seed": {"implementation": implementation}}))
    stage = tmp_path / "outputs" / "tests" / "PRICING_VERIFY" / "system"
    stage.mkdir(parents=True)
    (stage / "test_system.py").write_text(
        "import pytest\nfrom outputs.agent_src.code.PRICING_VERIFY.pricing import apply_discount\n\n"
        "def test_ten():\n    assert apply_discount(100, 10) == 90\n\n"
        "def test_hundred():\n    with pytest.raises(ValueError):\n        apply_discount(100, 100)\n\n"
        "def test_helper():\n    from outputs.agent_src.code.PRICING_VERIFY.pricing import _clamp\n"
        "    assert _clamp(5) == 5\n")
    return tmp_path


def test_the_copy_imports_the_users_module_and_runs_on_it(tmp_path):
    _project(tmp_path)
    written, result = take_tests.take(str(tmp_path), "PRICING_VERIFY",
                                      str(tmp_path / "tests"), say=lambda *_: None)
    copied = (tmp_path / "tests" / "qikly_generated" / "test_pricing_verify_system.py")
    assert [os.path.normcase(p) for p in written] == [os.path.normcase(str(copied))]
    text = copied.read_text()
    assert text.startswith(take_tests.MARKER)
    assert "from pricing import apply_discount" in text
    assert "outputs.agent_src" not in text.split("\n", 3)[3]
    summary, disagree, missing = result
    assert "1 passed" in summary and "2 failed" in summary
    assert [n.split("::")[-1] for n in disagree] == ["test_hundred"]
    assert [n.split("::")[-1] for n in missing] == ["test_helper"]


def test_a_file_qikly_did_not_write_is_never_overwritten(tmp_path):
    _project(tmp_path)
    mine = tmp_path / "tests" / "qikly_generated"
    mine.mkdir()
    (mine / "test_pricing_verify_system.py").write_text("# mine\n")
    seen = []
    written, _ = take_tests.take(str(tmp_path), "PRICING_VERIFY",
                                 str(tmp_path / "tests"), say=seen.append)
    assert written == [] and (mine / "test_pricing_verify_system.py").read_text() == "# mine\n"
    assert any("left alone" in s for s in seen)


def test_a_package_seed_keeps_its_own_import(tmp_path):
    _project(tmp_path, implementation="src/acme", module="acme.scoring")
    assert take_tests.own_import(str(tmp_path), take_tests.task_config(
        str(tmp_path), "PRICING_VERIFY"), str(tmp_path / "tests")) == (None, None)


def test_a_task_without_generated_tests_says_so(tmp_path):
    _project(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "outputs")
    written, reason = take_tests.take(str(tmp_path), "PRICING_VERIFY",
                                      str(tmp_path / "tests"))
    assert written is None and "run it first" in reason
