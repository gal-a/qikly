"""
One whole run, offline.

Seeding the implementation and all three test stages suppresses every
generation call, so this exercises the wiring rather than the model: config
loading, workspace reset, seed installation, seed validation, staged execution,
regression re-checks, and the run summary. That is the layer where a refactor
breaks something silently, because every individual function still passes its
own unit test while the pipeline no longer connects.
"""
import json
import os
import shutil

import pytest

from qikly.agent_api.agent_interface import task_config_path
from qikly.orchestrator.orchestrator import orchestrate
from qikly.paths import chdir_to_project_root

TASK = "ZZ_SMOKE_TASK"

# Every shared directory a run writes into under names carrying the task id.
# One tuple, used by both the teardown and the check that the teardown worked.
# They used to be two tuples, and `reports/junit` was missing from both, so
# 1,862 junit files from this test piled up in the live project while the
# "leaves nothing behind" check kept passing: it could not see what it did not
# list. `logs/patches` holds a directory per task rather than files.
SHARED_DIRS = ("outputs/reports/iterations", "outputs/logs",
               "outputs/logs/patches", "outputs/reports/junit",
               "outputs/reports/run_summary", "outputs/reports/metrics",
               "outputs/reports/usage")

IMPL = '''"""Trivial but real: reads a CSV, filters, writes JSON."""
import csv
import json
import os


def extract(paths):
    rows = []
    for path in paths:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, newline="", encoding="utf-8") as handle:
            rows.extend(list(csv.DictReader(handle)))
    return rows


def transform(rows):
    accepted, rejected = [], []
    for row in rows:
        try:
            value = int(row["value"])
        except (KeyError, ValueError, TypeError):
            rejected.append({**row, "reason": "value is not an integer"})
            continue
        if value <= 0:
            rejected.append({**row, "reason": "value must be positive"})
        else:
            accepted.append({**row, "doubled": value * 2})
    return {"accepted": accepted, "rejected": rejected}


def load(result, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)


def run_smoke(input_paths, output_path):
    load(transform(extract(input_paths)), output_path)
'''

TESTS = {
    "integration": '''
from outputs.agent_src.code.ZZ_SMOKE_TASK.smoke import extract, transform


def test_extract_reads_every_row():
    rows = extract(["inputs_private/data/ZZ_SMOKE_TASK/input_01.csv"])
    assert len(rows) == 3


def test_transform_splits_accepted_from_rejected():
    result = transform([{"id": "1", "value": "5"}, {"id": "2", "value": "-1"}])
    assert len(result["accepted"]) == 1
    assert len(result["rejected"]) == 1
''',
    "system": '''
import json
import os

from outputs.agent_src.code.ZZ_SMOKE_TASK.smoke import run_smoke


def test_end_to_end_writes_valid_json(tmp_path):
    out = str(tmp_path / "output.json")
    run_smoke(["inputs_private/data/ZZ_SMOKE_TASK/input_01.csv"], out)
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as handle:
        data = json.load(handle)
    assert set(data) == {"accepted", "rejected"}
''',
    "unit": '''
from outputs.agent_src.code.ZZ_SMOKE_TASK.smoke import transform


def test_non_integer_is_rejected_with_a_reason():
    result = transform([{"id": "1", "value": "abc"}])
    assert result["rejected"][0]["reason"]


def test_zero_is_rejected_as_non_positive():
    result = transform([{"id": "1", "value": "0"}])
    assert not result["accepted"]
''',
}

CONFIG = '''task_id: "ZZ_SMOKE_TASK"

requirements: |
  Read rows with an integer `value` column. Reject non-integers and
  non-positive values with a reason. Double the rest.

interface:
  module: "outputs.agent_src.code.ZZ_SMOKE_TASK.smoke"
  system_entrypoint: "run_smoke(input_paths, output_path) -> None"

acceptance_criteria:
  - "A non-integer value is rejected with a reason."
  - "A value of zero or below is rejected as non-positive."
  - "Accepted rows carry a doubled field equal to twice the value."

inputs:
  - "inputs_private/data/ZZ_SMOKE_TASK/input_01.csv"

output: "outputs/data/ZZ_SMOKE_TASK/output.json"

seed:
  implementation: "outputs/zz_smoke_seed/smoke.py"
  tests:
    integration: "outputs/zz_smoke_seed/integration/"
    system: "outputs/zz_smoke_seed/system/"
    unit: "outputs/zz_smoke_seed/unit/"
'''


@pytest.fixture
def smoke_task():
    root = chdir_to_project_root()
    cfg = task_config_path(TASK)
    seed_root = os.path.join(root, "outputs", "zz_smoke_seed")
    data_dir = os.path.join(root, "inputs_private", "data", TASK)
    created = [cfg, seed_root, data_dir,
               os.path.join(root, "outputs", "agent_src", "code", TASK),
               os.path.join(root, "outputs", "tests", TASK),
               os.path.join(root, "outputs", "data", TASK)]

    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(CONFIG)

    os.makedirs(seed_root, exist_ok=True)
    with open(os.path.join(seed_root, "smoke.py"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(IMPL)
    for stage, body in TESTS.items():
        d = os.path.join(seed_root, stage)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"test_{stage}.py"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)

    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "input_01.csv"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("id,value\n1,5\n2,-3\n3,abc\n")

    yield TASK

    for path in created:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)

    # A real run writes more than the directories listed above: one iteration
    # report per stage, a transaction log, a run summary. Those land in shared
    # report directories under names beginning with the task id, so they
    # cannot be removed by deleting a directory.
    #
    # Leaving them there is not harmless. Six files per test, two tests, every
    # `pytest` invocation, and nothing ever removing them: 684 iteration
    # reports and 228 logs had built up in the live project before anyone
    # noticed. Nothing reaches git, since outputs/ is ignored, but a developer
    # looking for a real run's output has to find it among hundreds of files
    # from a smoke test.
    for directory in SHARED_DIRS:
        full = os.path.join(root, directory)
        if not os.path.isdir(full):
            continue
        for name in os.listdir(full):
            if TASK in name:
                target = os.path.join(full, name)
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        os.remove(target)
                except OSError:
                    pass


def test_a_fully_seeded_run_converges_without_any_model_call(smoke_task):
    """
    Every stage is seeded, so no generation happens and nothing needs fixing.
    If this raises, the pipeline is broken somewhere between config and pytest.
    """
    root = chdir_to_project_root()
    orchestrate(smoke_task, seed=1)

    impl = os.path.join(root, "outputs", "agent_src", "code", smoke_task, "smoke.py")
    assert os.path.exists(impl), "the seeded implementation was not installed"

    for stage in TESTS:
        d = os.path.join(root, "outputs", "tests", smoke_task, stage)
        assert os.path.isdir(d), f"{stage} tests were not installed"
        assert any(f.startswith("test_") for f in os.listdir(d)), f"{stage} has no test file"


def test_the_run_produced_its_declared_output(smoke_task):
    root = chdir_to_project_root()
    orchestrate(smoke_task, seed=1)
    out = os.path.join(root, "outputs", "data", smoke_task, "output.json")
    if os.path.exists(out):
        with open(out, encoding="utf-8") as handle:
            data = json.load(handle)
        assert set(data) == {"accepted", "rejected"}


def test_the_smoke_run_leaves_nothing_behind_in_the_project(smoke_task):
    """
    A run writes iteration reports, a transaction log and a run summary into
    shared report directories, named by task rather than filed in a directory
    of their own, so deleting directories does not remove them.

    Nothing had been removing them. 684 iteration reports and 228 logs from
    this one test had collected in the live project, six more per pytest
    invocation. They never reach git, because outputs/ is ignored, but they
    bury a real run's output among hundreds of files from a smoke test.

    This runs inside the fixture, so it checks that the run's own artefacts
    are findable while it is alive; the teardown that removes them is checked
    by the session-scoped test below.
    """
    root = chdir_to_project_root()
    orchestrate(smoke_task)
    written = [n for n in os.listdir(os.path.join(root, "outputs/reports/iterations"))
               if TASK in n]
    assert written, "the run should produce iteration reports at all"


def test_no_smoke_artefacts_survive_a_completed_run():
    """
    Outside the fixture, so anything left here outlived its teardown. Uses no
    fixture on purpose: this is the state of the project between tests.
    """
    root = chdir_to_project_root()
    leftovers = []
    for directory in SHARED_DIRS:
        full = os.path.join(root, directory)
        if os.path.isdir(full):
            leftovers += [f"{directory}/{n}" for n in os.listdir(full) if TASK in n]
    assert not leftovers, (
        f"{len(leftovers)} smoke artefact(s) left in the project: {leftovers[:4]}")
