"""
`qikly --take-tests`: a run's tests, copied into the user's own tests and
rewritten to import the user's module rather than qikly's copy of it. Each
test below reproduces an audit finding from before 0.6.0.
"""
import os

import yaml

from qikly import take_tests

CODE = ("def apply_discount(price, rate):\n    if rate < 0 or rate > 100:\n"
        "        raise ValueError\n    return price * (1 - rate / 100)\n")
GEN = ("import pytest\nfrom outputs.agent_src.code.PRICING_VERIFY.pricing import apply_discount\n\n"
       "def test_ten():\n    assert apply_discount(100, 10) == 90\n\n"
       "def test_hundred():\n    \"\"\"# Criteria: 1\"\"\"\n    with pytest.raises(ValueError):\n"
       "        apply_discount(100, 100)\n\n"
       "def test_helper():\n    from outputs.agent_src.code.PRICING_VERIFY.pricing import _clamp\n"
       "    assert _clamp(5) == 5\n")


def _project(tmp_path, implementation="pricing.py", module=None, stage_files=None,
             own_test="from pricing import apply_discount\n\ndef test_a():\n"
                      "    assert apply_discount(100, 10) == 90\n"):
    code = tmp_path / implementation
    code.parent.mkdir(parents=True, exist_ok=True)
    if not implementation.endswith("/"):
        code.write_text(CODE)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_pricing.py").write_text(own_test)
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "PRICING_VERIFY.yaml").write_text(yaml.safe_dump({
        "task_id": "PRICING_VERIFY",
        "interface": {"module": module or "outputs.agent_src.code.PRICING_VERIFY.pricing"},
        "seed": {"implementation": implementation},
        "acceptance_criteria": ["apply_discount(100, 100) raises ValueError"]}))
    for rel, text in (stage_files or {"system/test_system.py": GEN}).items():
        path = tmp_path / "outputs" / "tests" / "PRICING_VERIFY" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def _take(tmp_path, folder="tests"):
    return take_tests.take(str(tmp_path), "PRICING_VERIFY", str(tmp_path / folder),
                           say=lambda *_: None)


def _copy(tmp_path, stage="system", name="test_system.py", folder="tests"):
    return (tmp_path / folder / "qikly_generated" / "pricing_verify" / stage / name)


def test_the_copy_imports_the_users_module_and_runs_on_it(tmp_path):
    _project(tmp_path)
    written, result = _take(tmp_path)
    text = _copy(tmp_path).read_text()
    assert text.startswith(take_tests.MARKER)
    assert "from pricing import apply_discount" in text
    assert "outputs.agent_src" not in text.split("\n", 3)[3]
    summary, disagree, missing, no_import, broken, unanswered = result
    assert "1 passed" in summary and "2 failed" in summary
    assert [n.split("::")[-1] for n in disagree] == ["test_hundred"]
    assert [n.split("::")[-1] for n in missing] == ["test_helper"]


def test_the_from_package_import_is_rewritten_too(tmp_path):
    """`from outputs.agent_src.code.T import pricing` kept testing qikly's copy."""
    gen = ("import pytest\nfrom outputs.agent_src.code.PRICING_VERIFY import pricing\n\n"
           "def test_hundred():\n    # Criteria: 1\n    with pytest.raises(ValueError):\n"
           "        pricing.apply_discount(100, 100)\n")
    _project(tmp_path, stage_files={"system/test_system.py": gen})
    written, result = _take(tmp_path)
    text = _copy(tmp_path).read_text()
    assert "import pricing as pricing" in text and "outputs.agent_src" not in text
    assert result[1], "it fails on the user's own code, as it should"


def test_the_users_import_is_never_taken_from_outputs(tmp_path):
    """With the tests folder at the root, the walk adopted qikly's own import."""
    _project(tmp_path, own_test="def test_nothing():\n    pass\n")
    module, ours = take_tests.own_import(
        str(tmp_path), take_tests.task_config(str(tmp_path), "PRICING_VERIFY"),
        str(tmp_path))
    assert not ours.startswith("outputs")


def test_a_users_from_package_import_is_followed(tmp_path):
    _project(tmp_path, implementation="app/pricing.py",
             own_test="from app import pricing\n\ndef test_a():\n"
                      "    assert pricing.apply_discount(100, 10) == 90\n")
    (tmp_path / "app" / "__init__.py").write_text("")
    _, ours = take_tests.own_import(
        str(tmp_path), take_tests.task_config(str(tmp_path), "PRICING_VERIFY"),
        str(tmp_path / "tests"))
    assert ours == "app.pricing"


def test_a_file_qikly_did_not_write_is_never_overwritten(tmp_path):
    _project(tmp_path)
    mine = _copy(tmp_path)
    mine.parent.mkdir(parents=True)
    mine.write_text("# mine\n")
    seen = []
    written, _ = take_tests.take(str(tmp_path), "PRICING_VERIFY",
                                 str(tmp_path / "tests"), say=seen.append)
    assert mine.read_text() == "# mine\n"
    assert any("left alone" in s for s in seen)


def test_a_conftest_beside_the_tests_keeps_its_name(tmp_path):
    files = {"system/conftest.py": "import pytest\n\n@pytest.fixture\ndef rate():\n    return 10\n",
             "system/test_system.py":
                 "from outputs.agent_src.code.PRICING_VERIFY.pricing import apply_discount\n\n"
                 "def test_r(rate):\n    assert apply_discount(100, rate) == 90\n"}
    _project(tmp_path, stage_files=files)
    written, result = _take(tmp_path)
    assert _copy(tmp_path, name="conftest.py").exists()
    assert "1 passed" in result[0], result


def test_a_module_whose_name_cannot_be_imported_is_said_so(tmp_path):
    _project(tmp_path, implementation="my-calc.py")
    written, reason = _take(tmp_path)
    assert written is None and "cannot be imported" in reason


def test_code_in_a_subfolder_is_importable_from_the_copies(tmp_path):
    """No tests of the user's to learn the import from, and the code in lib/."""
    _project(tmp_path, implementation="lib/pricing.py",
             own_test="def test_nothing():\n    pass\n")
    written, result = _take(tmp_path)
    summary, disagree, missing, no_import, broken, unanswered = result
    assert not no_import, result
    assert disagree, "the rate-100 test reaches the user's code"


def test_one_broken_file_does_not_stop_the_others(tmp_path):
    files = {"integration/test_integration.py": "this is not python\n",
             "system/test_system.py": GEN}
    _project(tmp_path, stage_files=files)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -x\n")
    written, result = _take(tmp_path)
    summary, disagree, missing, no_import, broken, unanswered = result
    assert broken and disagree, result


def test_a_rerun_removes_copies_it_no_longer_writes(tmp_path):
    _project(tmp_path, stage_files={"system/test_system.py": GEN,
                                    "unit/test_unit.py": GEN})
    _take(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "outputs" / "tests" / "PRICING_VERIFY" / "unit")
    _take(tmp_path)
    assert not _copy(tmp_path, stage="unit", name="test_unit.py").exists()


def test_the_folder_is_remembered_for_later(tmp_path):
    _project(tmp_path)
    (tmp_path / "test").mkdir()
    _take(tmp_path, folder="test")
    assert os.path.normcase(take_tests.remembered_folder(str(tmp_path), "PRICING_VERIFY")) \
        == os.path.normcase(str(tmp_path / "test"))


def test_an_unknown_task_creates_no_folder(tmp_path, capsys):
    assert take_tests.main("NOPE_VERIFY", str(tmp_path)) == 2
    assert not (tmp_path / "tests").exists()


def test_a_package_seed_keeps_its_own_import(tmp_path):
    _project(tmp_path, implementation="src/acme/", module="acme.scoring")
    assert take_tests.own_import(str(tmp_path), take_tests.task_config(
        str(tmp_path), "PRICING_VERIFY"), str(tmp_path / "tests")) == (None, None)


def test_a_task_without_generated_tests_says_so(tmp_path):
    _project(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "outputs")
    written, reason = _take(tmp_path)
    assert written is None and "run it first" in reason


def test_a_failing_test_no_answer_is_behind_is_never_called_a_disagreement(tmp_path):
    # semantic_version: two tests written from the requirements misused its
    # API, and the user was told to apply qikly's change to code that was right.
    gen = ("from outputs.agent_src.code.PRICING_VERIFY.pricing import apply_discount\n\n"
           "def test_guess():\n    \"\"\"# Criteria: none\"\"\"\n"
           "    assert apply_discount(100, 10) == 91\n")
    _project(tmp_path, stage_files={"integration/test_integration.py": gen})
    said = []
    written, result = take_tests.take(str(tmp_path), "PRICING_VERIFY", str(tmp_path / "tests"),
                                      say=said.append)
    summary, disagree, missing, no_import, broken, unanswered = result
    assert not disagree and [n.split("::")[-1] for n in unanswered] == ["test_guess"]
    take_tests.report(said.append, str(tmp_path), written, result, "PRICING_VERIFY")
    text = "\n".join(said)
    assert "not written from any of your answers" in text
    assert "apply the same fix" not in text
