"""
A scaffolded task's tests must import the code the coding agent patches.

`--scaffold` used to write `interface.module` as the file's path relative to
the project, such as `billing`. A run installs the implementation into
outputs/agent_src/code/<task>/ and runs pytest from the project root, so the
tests imported the project's original file while every patch landed in the
copy. No fix could ever reach a test. Reproduced end to end before the fix:
the patched copy returned PATCHED and the test saw ORIGINAL.

This runs the same check: install the seed the way a run does, patch the copy,
and run pytest the way run_tests.py does, from the project root. No model call.
"""
import os
import subprocess
import sys

import yaml

from qikly import scaffold
from qikly.orchestrator.orchestrator import install_seed

ORIGINAL = 'def run_billing(input_paths, output_path):\n    return "ORIGINAL"\n'
PATCHED = 'def run_billing(input_paths, output_path):\n    return "PATCHED"\n'


def _run_like_a_run(project, module_rel):
    source = project / module_rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(ORIGINAL, encoding="utf-8")

    text, problem = scaffold.build_task(str(source), str(project), seed="existing")
    assert problem is None
    task = yaml.safe_load(text)
    task_id, module = task["task_id"], task["interface"]["module"]

    code_dir = project / "outputs" / "agent_src" / "code" / task_id
    installed = install_seed(str(source), str(code_dir))
    with open(installed[0], "w", encoding="utf-8") as handle:
        handle.write(PATCHED)                     # what the coding agent's PATCH does

    tests = project / "outputs" / "tests" / task_id / "integration"
    tests.mkdir(parents=True)
    (tests / "test_sees_the_patch.py").write_text(
        "import importlib\n"
        "def test_it():\n"
        "    assert importlib.import_module(%r).run_billing(None, None) == 'PATCHED'\n"
        % module, encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests), "-q", "-p", "no:cacheprovider",
         "-o", "addopts="],
        cwd=str(project), env=env, capture_output=True, text=True, timeout=120)
    return module, proc


def test_a_module_at_the_project_root_is_imported_from_the_installed_copy(tmp_path):
    module, proc = _run_like_a_run(tmp_path, "billing.py")
    assert module == "outputs.agent_src.code.BILLING_VERIFY.billing"
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_module_in_a_subfolder_is_imported_from_the_installed_copy(tmp_path):
    module, proc = _run_like_a_run(tmp_path, os.path.join("src", "billing.py"))
    assert module == "outputs.agent_src.code.BILLING_VERIFY.billing"
    assert proc.returncode == 0, proc.stdout + proc.stderr
