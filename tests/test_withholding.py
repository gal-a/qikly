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
from qikly.agent_tools.inspect_code import inspect_failure

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


# Captured from a real `python -m pytest ... --tb` default run against a
# replica of CALC_TAX's failing integration test, with trailing whitespace on
# blank lines removed. Hand-written failure text is what let the documentation
# and this file drift apart, so it is worth keeping this shaped by pytest.
REAL_PYTEST_OUTPUT = '''============================= test session starts =============================
collected 2 items

tests/test_integration.py::test_tax_rate_validation_rules FAILED         [ 50%]
tests/test_integration.py::test_tax_exempt_zero_rate PASSED              [100%]

================================== FAILURES ===================================
_______________________ test_tax_rate_validation_rules ________________________

    def test_tax_rate_validation_rules():
        """Accepted rows carry a tax rate between 0 and 100.

        # Criteria: 7
        """
        rows_1 = extract(INPUT_01)
        rows_2 = extract(INPUT_02)
        result = transform(rows_1 + rows_2)

        for row in result["accepted"]:
            rate = float(row["tax_rate"])
>           assert 0 <= rate <= 100
E           assert 150.0 <= 100

tests/test_integration.py:18: AssertionError
========================= 1 failed, 1 passed in 0.08s =========================
'''


# The same failing test at the two narrow rungs, captured the same way. Note
# what is absent from both: the docstring. That is the whole point of the
# ladder, and asserting it against pytest's real output rather than against a
# belief about pytest is what makes the assertion worth anything.
TB_LINE_OUTPUT = '''================================== FAILURES ===================================
E   assert 150.0 <= 100
/tmp/calcrep/tests/test_integration.py:18: assert 150.0 <= 100
=========================== short test summary info ===========================
FAILED tests/test_integration.py::test_tax_rate_validation_rules - assert 150...
========================= 1 failed, 1 passed in 0.02s =========================
'''

TB_SHORT_OUTPUT = '''================================== FAILURES ===================================
_______________________ test_tax_rate_validation_rules ________________________
tests/test_integration.py:18: in test_tax_rate_validation_rules
    assert 0 <= rate <= 100
E   assert 150.0 <= 100
=========================== short test summary info ===========================
FAILED tests/test_integration.py::test_tax_rate_validation_rules - assert 150...
========================= 1 failed, 1 passed in 0.09s =========================
'''

# An exception raised inside the implementation, at the same two rungs. Both
# name `calc.py` and the line, which is the evidence that starting narrow does
# not blind the agent to its own code.
TB_LINE_IMPL_ERROR = '''================================== FAILURES ===================================
E   ValueError: invalid literal for int() with base 10: '150.0'
/tmp/calcrep/calc.py:7: ValueError: invalid literal for int() with base 10: '150.0'
=========================== short test summary info ===========================
FAILED tests/test_integration.py::test_tax_rate_validation_rules - ValueError...
============================== 1 failed in 0.02s ==============================
'''

TB_SHORT_IMPL_ERROR = '''================================== FAILURES ===================================
_______________________ test_tax_rate_validation_rules ________________________
tests/test_integration.py:14: in test_tax_rate_validation_rules
    result = transform(rows_1 + rows_2)
calc.py:7: in transform
    total += int(r["tax_rate"])
E   ValueError: invalid literal for int() with base 10: '150.0'
=========================== short test summary info ===========================
FAILED tests/test_integration.py::test_tax_rate_validation_rules - ValueError...
============================== 1 failed in 0.06s ==============================
'''


_FAILED_LINE = "FAILED tests/test_integration.py::test_tax_rate_validation_rules"


def real_failure_text():
    """The FIX input, built the way the orchestrator builds it."""
    return inspect_failure({
        "raw_output": REAL_PYTEST_OUTPUT,
        "failed_tests": [
            "FAILED tests/test_integration.py::test_tax_rate_validation_rules"
        ],
    })


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
    prompt = build_fix_prompt("AGENT_MD_STUB", task, real_failure_text())
    assert SENTINEL_A not in prompt
    assert SENTINEL_B not in prompt


def test_patch_prompt_contains_no_criterion(stub_task):
    task = ai._task_without_acceptance_criteria(stub_task)
    prompt = build_patch_prompt("AGENT_MD_STUB", task, "FIX: change the rounding",
                                "def run(): pass")
    assert SENTINEL_A not in prompt
    assert SENTINEL_B not in prompt


def test_the_failure_text_is_pytests_own_output_including_the_test_source():
    """
    What the coding agent receives on a failure, pinned as it actually is.

    The earlier version of the test above passed `inspect_failure` a one-line
    string, "test_x failed: expected 3 got 4". That is what the documentation
    used to claim the agent gets, and the test agreed with the documentation
    rather than with pytest, so neither could catch the difference.

    Pytest runs at its default `--tb=auto` (see `agent_tools/run_tests.py`),
    and `inspect_failure` passes `raw_output` through untouched. So the real
    payload carries, for every currently failing test, its name, its source
    from `def` down to the failing statement, its docstring, and the values
    pytest prints under the assertion.

    That is deliberate: a traceback whose frames are in the implementation is
    exactly what makes a repair possible. This test exists so that anyone who
    changes the traceback mode, in either direction, does it knowing what the
    channel carries rather than discovering it later.
    """
    text = real_failure_text()

    # Present, and load-bearing for the repair.
    assert "def test_tax_rate_validation_rules" in text
    assert "assert 0 <= rate <= 100" in text
    assert "assert 150.0 <= 100" in text

    # Present, and the reason the README no longer says "only an assertion
    # error": a docstring restates the rule in the test author's words.
    assert "Accepted rows carry a tax rate between 0 and 100" in text

    # Absent, which is the property that actually matters.
    assert SENTINEL_A not in text
    assert SENTINEL_B not in text


def test_a_passing_test_gives_up_its_name_but_not_its_body():
    """
    How much of the rest of the bar a single failure reveals.

    Written expecting passing tests to be invisible, and it failed on the
    first run, which is why it is worth having. `run_tests.py` passes `-v`, so
    pytest lists every collected test by name with its status. A passing test
    therefore contributes its *name* to the agent's view, and test names are
    not nothing: `test_tax_exempt_zero_rate` announces that a tax-exempt rule
    exists and is being checked.

    What a passing test does not contribute is its body, its docstring or its
    assertions. Pytest prints a traceback only for failures. So the boundary
    is: names of everything, substance of what is currently red.

    Dropping `-v` would close this, at the cost of the per-test status lines
    that `_parse_test_results` reads to build the counts and the reports. That
    is a trade, not a bug, and this test names it so the trade stays visible.
    """
    text = real_failure_text()

    assert "test_tax_exempt_zero_rate" in text, (
        "-v lists passing tests by name; if that stops being true, the "
        "docstring above and the README both need updating")

    # The passing test's own docstring restates its criterion, and that must
    # not travel. Only the failing test's body is printed.
    assert "tax-exempt row is accepted" not in text
    assert "# Criteria: 8" not in text


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


# --- staged diagnostic feedback -------------------------------------------
#
# The rung scheme narrows the channel above rather than widening it, which is
# the only reason it is allowed near this mechanism at all. These pin both
# halves: that the default is unchanged, and that the narrow rungs really do
# withhold the test's prose.


def test_the_default_is_the_full_traceback_and_nothing_reads_settings_to_get_it():
    """
    Every published convergence figure was measured at the full traceback, so
    the default has to stay there even if the settings file is missing, empty
    or holds a value nobody recognises.
    """
    from qikly.agent_tools import run_tests as rt
    from qikly.orchestrator import orchestrator as orch

    assert rt.TB_FULL == "auto"
    assert orch.traceback_mode_for(0, "full") == rt.TB_FULL

    # Passed straight through, not pre-resolved with `or`. A falsy mode takes a
    # different branch inside traceback_mode_for: it falls back to reading
    # settings. An earlier version of this test wrote `junk or "full"`, which
    # resolved "" and None before the call and so never reached that branch.
    for junk in ("", None, "STAGED_BUT_MISSPELLED", "off", "Full", "  full  "):
        assert orch.traceback_mode_for(0, junk) == rt.TB_FULL

    # And the settings fallback itself, with the bundled yaml out of the
    # picture, so this asserts the code rather than the shipped default.
    import pytest as _pytest
    for settings in ({}, {"agent": {}}, {"agent": {"diagnostic_feedback": None}},
                     {"agent": {"diagnostic_feedback": "nonsense"}}):
        with _pytest.MonkeyPatch.context() as patch:
            patch.setattr(orch, "load_settings", lambda s=settings: s)
            assert orch.diagnostic_feedback() == "full"
            assert orch.traceback_mode_for(0, None) == rt.TB_FULL


def test_staged_starts_narrow_and_reaches_the_full_traceback():
    """
    Staged must converge on the full traceback, or a run could stall at a rung
    that will never carry enough to repair the fault. Two ineffective patches
    is the whole ladder.
    """
    from qikly.agent_tools import run_tests as rt
    from qikly.orchestrator import orchestrator as orch

    seen = [orch.traceback_mode_for(streak, "staged") for streak in range(6)]
    assert seen[0] == "line", "the first attempt is shown the least"
    assert seen[-1] == rt.TB_FULL, "staged must end where full begins"
    assert seen.count(rt.TB_FULL) >= 3, "it stays at full once it gets there"


def test_the_narrow_rungs_withhold_the_docstring_that_paraphrases_the_criterion():
    """
    The reason the ladder exists.

    A generated test's docstring restates the rule it was written from, and
    pytest's default traceback prints it. `line` and `short` do not. This
    asserts against real pytest output rather than a belief about pytest: the
    three fixtures below were captured by running the same failing test at
    each mode.
    """
    from qikly.agent_tools.inspect_code import inspect_failure

    prose = "Accepted rows carry a tax rate between 0 and 100"

    auto = inspect_failure({"raw_output": REAL_PYTEST_OUTPUT,
                            "failed_tests": [_FAILED_LINE]})
    assert prose in auto, "the captured default output should contain the docstring"

    line_mode = inspect_failure({"raw_output": TB_LINE_OUTPUT,
                                 "failed_tests": [_FAILED_LINE]})
    assert prose not in line_mode
    assert "assert 150.0 <= 100" in line_mode, "the fault is still locatable"

    short_mode = inspect_failure({"raw_output": TB_SHORT_OUTPUT,
                                  "failed_tests": [_FAILED_LINE]})
    assert prose not in short_mode
    assert "assert 150.0 <= 100" in short_mode


def test_every_rung_still_names_a_fault_inside_the_implementation():
    """
    The narrow rungs must not blind the agent to its own code. An exception
    raised in the implementation names that file and line at every rung, which
    is what makes starting narrow defensible rather than merely quieter.
    """
    from qikly.agent_tools.inspect_code import inspect_failure

    for raw in (TB_LINE_IMPL_ERROR, TB_SHORT_IMPL_ERROR):
        text = inspect_failure({"raw_output": raw, "failed_tests": [_FAILED_LINE]})
        assert "calc.py" in text
        assert "ValueError" in text


def test_a_collection_error_is_still_legible_at_the_narrow_rungs():
    """
    The narrow rungs must not break the one message that matters most.

    When the module will not import, no test runs and the counts say nothing a
    reader can use. `_collection_summary` exists to turn that into a first line
    worth reading, and it finds the exception by matching pytest's `E   `
    prefix on an `ERROR collecting` block. If a narrow traceback dropped that
    prefix, a run against a broken import would tell the agent nothing, every
    iteration, until the budget ran out.

    The fixture below is one capture, not three. Running the same broken import
    under `--tb=auto`, `--tb=line` and `--tb=short` on pytest 9.1.1 produced
    byte-identical output in the part this parses, because a collector formats
    its own failure before the traceback style applies. Asserting the same
    string three times would only have looked like more coverage, so this
    records the finding instead and checks the parse once.

    What is NOT covered here, and is worth knowing: this pins our parser
    against a captured string, not against pytest. If a future pytest changes
    how a collector renders, this test keeps passing and real runs degrade.
    `tests/test_run_tests.py` has the live subprocess check, at the default
    mode only.
    """
    from qikly.agent_tools.inspect_code import inspect_failure

    captured = "\n".join([
        "______________________ ERROR collecting tests/test_x.py ______________",
        "E   ModuleNotFoundError: No module named 'nonexistent_module'",
    ])

    text = inspect_failure({"raw_output": captured, "failed_tests": []})
    assert "COLLECTION ERROR" in text
    assert "ModuleNotFoundError" in text
    assert "Unknown failure" not in text
