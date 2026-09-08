"""
The central claim.

Everything else this project asserts rests on one property: the agent that
writes the code never receives the acceptance criteria it will be judged
against. If that leaks, a passing run stops being evidence of anything, because
the same model that wrote the bug also read the answer key.

Nothing guarded that property until these tests existed. It is one regex and
four call sites, and any of them could be changed by someone who did not know
what the regex was load-bearing for.
"""
import re

import pytest

from qikly.agent_api import agent_interface as ai
from qikly.agent_api.prompts.fix_prompt import build_fix_prompt
from qikly.agent_api.prompts.patch_prompt import build_patch_prompt

SENTINEL_A = "ZZSENTINELCRITERIONALPHA"
SENTINEL_B = "ZZSENTINELCRITERIONBRAVO"

TASK_YAML = f"""task_id: "SENTINEL_TASK"

requirements: |
  Read rows from the input CSVs and write results to the output path.
  This line must survive stripping.

interface:
  module: "outputs.agent_src.code.SENTINEL_TASK.calc"
  system_entrypoint: "run(input_paths, output_path) -> None"

acceptance_criteria:
  - "{SENTINEL_A} must be rejected with a reason."
  - "{SENTINEL_B} must be rounded to two decimal places."

inputs:
  - "inputs_private/data/SENTINEL_TASK/input_01.csv"
"""


@pytest.fixture
def stub_task(monkeypatch):
    monkeypatch.setattr(ai, "_read_task", lambda task_id: TASK_YAML)
    return "SENTINEL_TASK"


def test_criteria_are_removed_from_the_coding_agents_view(stub_task):
    stripped = ai._task_without_acceptance_criteria(stub_task)
    assert SENTINEL_A not in stripped
    assert SENTINEL_B not in stripped
    assert "acceptance_criteria" not in stripped


def test_everything_else_survives_stripping(stub_task):
    """A strip that ate the requirements would also pass the test above."""
    stripped = ai._task_without_acceptance_criteria(stub_task)
    assert "This line must survive stripping." in stripped
    assert "SENTINEL_TASK" in stripped
    assert "system_entrypoint" in stripped
    assert "input_01.csv" in stripped


def test_fix_prompt_contains_no_criterion(stub_task):
    task = ai._task_without_acceptance_criteria(stub_task)
    prompt = build_fix_prompt("AGENT_MD_STUB", task,
                              "test_x failed: expected 3 got 4")
    assert SENTINEL_A not in prompt
    assert SENTINEL_B not in prompt


def test_patch_prompt_contains_no_criterion(stub_task):
    task = ai._task_without_acceptance_criteria(stub_task)
    prompt = build_patch_prompt("AGENT_MD_STUB", task, "FIX: change the rounding",
                                "def run(): pass")
    assert SENTINEL_A not in prompt
    assert SENTINEL_B not in prompt


@pytest.mark.parametrize("yaml_shape", [
    # trailing key after the block
    f'acceptance_criteria:\n  - "{SENTINEL_A}"\ninputs:\n  - "a.csv"\n',
    # block is last in the file
    f'requirements: |\n  do the thing\nacceptance_criteria:\n  - "{SENTINEL_A}"\n',
    # no trailing newline
    f'requirements: |\n  do the thing\nacceptance_criteria:\n  - "{SENTINEL_A}"',
    # blank lines inside the block
    f'acceptance_criteria:\n\n  - "{SENTINEL_A}"\n\n  - "b"\n\ninputs:\n  - "a.csv"\n',
    # indented continuation of a long criterion
    f'acceptance_criteria:\n  - "{SENTINEL_A}\n    continued on the next line"\ninputs:\n  - "a.csv"\n',
])
def test_stripping_holds_across_yaml_shapes(monkeypatch, yaml_shape):
    """
    The regex is anchored and non-greedy, so its behaviour depends on what
    follows the block. Each shape below is one a real task file can take.
    """
    monkeypatch.setattr(ai, "_read_task", lambda task_id: yaml_shape)
    assert SENTINEL_A not in ai._task_without_acceptance_criteria("T")


def test_every_coding_agent_call_site_uses_the_stripped_task():
    """
    Guards the wiring, not the regex. A new prompt builder that read the task
    directly would pass every test above and still leak.
    """
    source = open(ai.__file__, encoding="utf-8").read()
    body = source[source.index("def agent_generate_fix"):]
    for fn in ("agent_generate_fix", "agent_generate_patch"):
        start = body.index(f"def {fn}")
        chunk = body[start:body.index("\ndef ", start + 1) if "\ndef " in body[start + 1:] else len(body)]
        assert "_task_without_acceptance_criteria" in chunk, (
            f"{fn} does not strip the acceptance criteria")
        assert not re.search(r"\b_read_task\(", chunk), (
            f"{fn} reads the task directly, bypassing the strip")


# ------------------------------- what the TEST side is not given either ------

def test_integration_and_system_generation_are_told_they_have_no_implementation():
    """
    The docs say test generation never reads the code except for the unit
    stage. That claim rests on two prompts saying so, and nothing else, so a
    reworded prompt would quietly make three documents wrong.

    It matters because "the test agent sees all three parts of the task file"
    reads, to someone skimming, as "the test agent sees everything". It does
    not: when integration and system tests are written there is no
    implementation to see.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("integration_test_prompt.md", "system_test_prompt.md"):
        path = os.path.join(root, "src", "qikly", "inputs_public", "agent_defs", name)
        with open(path, encoding="utf-8") as handle:
            text = handle.read().lower()
        assert "do not have access to the implementation" in text, (
            f"{name} no longer tells the model it cannot see the implementation"
        )


def test_the_unit_prompt_is_the_one_place_the_implementation_is_handed_over():
    """
    The stated exception, and the reason the unit stage runs last. If this
    stopped being an exception the docs would be describing a separation that
    no longer exists.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "qikly", "inputs_public",
                        "agent_defs", "unit_test_prompt.md")
    import re

    with open(path, encoding="utf-8") as handle:
        # Whitespace-normalised: the phrase wraps across lines in the file, so
        # a plain substring check silently fails on a reflow.
        text = re.sub(r"\s+", " ", handle.read().lower())
    assert "one exception" in text
    assert "see the implementation" in text
    assert "{codebase_text}" in text, "the code is no longer actually passed in"


def test_the_interface_names_a_path_and_signatures_not_source():
    """
    interface.module is an address, not code: the dotted path where the
    implementation will be written. Both agents need it, the coder to know
    where to write and test generation to know what to import. It is the one
    field that looks like it might smuggle the implementation across, and it
    does not.
    """
    import yaml

    from qikly.agent_api.agent_interface import task_config_path

    with open(task_config_path("CALC_TAX"), encoding="utf-8") as handle:
        interface = yaml.safe_load(handle)["interface"]
    assert set(interface) == {"module", "integration_functions", "system_entrypoint"}
    assert isinstance(interface["module"], str)
    assert "\n" not in interface["module"], "a module path, not a body of code"
    assert all(isinstance(f, str) for f in interface["integration_functions"])
