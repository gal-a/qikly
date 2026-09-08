import contextlib
import hashlib
import json
import uuid
import os
import re
import shutil
from datetime import datetime

import yaml

from qikly.agent_api.agent_interface import (
    agent_generate_fix, agent_generate_patch, agent_src_code_path, task_config_path,
    agent_generate_integration_tests, agent_generate_system_tests, agent_generate_unit_tests,
    criteria_batches,
)
from qikly import approval
from qikly.agent_tools import junit
from qikly.agent_tools.apply_patch import apply_patch
from qikly.agent_tools.run_tests import run_tests
from qikly.agent_tools.inspect_code import inspect_failure, failure_signature
from qikly.paths import (
    PUBLIC_INPUTS_DIR, ensure_task_data, list_input_dir, private_input_path, private_inputs_dir,
    project_root,
)

LOG_DIR = "outputs/logs"
PATCH_DIR = "outputs/logs/patches"
GENERATED_TESTS_ROOT = "outputs/tests"

DEFAULT_STAGE_ORDER = ["integration", "system", "unit"]
DEFAULT_MAX_ATTEMPTS_PER_STAGE = 10
TASK_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# stage name -> (generator function, filename for the generated test file)
TEST_GENERATORS = {
    "integration": (agent_generate_integration_tests, "test_integration.py"),
    "system": (agent_generate_system_tests, "test_system.py"),
    "unit": (agent_generate_unit_tests, "test_unit.py"),
}

_BATCH_OVERRIDE = None


def criteria_per_batch():
    """
    How many acceptance criteria one test-generation call is shown.

    0, the default, means one call carrying the whole bar, which is the
    behaviour every published number was measured under. A positive value
    splits the bar and makes one call per batch, so a longer bar produces more
    test code instead of the same amount spread thinner. Set under
    `test_generation:` in settings.yaml.
    """
    if _BATCH_OVERRIDE is not None:
        return _BATCH_OVERRIDE
    section = load_settings().get("test_generation") or {}
    try:
        return int(section.get("criteria_per_batch", 0) or 0)
    except (TypeError, ValueError):
        return 0


@contextlib.contextmanager
def criteria_batching(value):
    """
    Force a batch size for the enclosed convergence, overriding settings.

    Exists so an experiment can hold suite SIZE constant while varying the
    criteria. A larger suite rejects foreign code more often whether or not
    its bar is stricter, so comparing two arms of unequal size cannot separate
    a better bar from more tests.
    """
    global _BATCH_OVERRIDE
    previous = _BATCH_OVERRIDE
    _BATCH_OVERRIDE = value
    try:
        yield
    finally:
        _BATCH_OVERRIDE = previous


@contextlib.contextmanager
def criteria_batching_disabled():
    """
    Run the enclosed convergence with one generation call for the whole bar.

    For a convergence whose only purpose is to produce an implementation to
    look at, a bigger suite is pure cost: more calls, more iterations, and a
    much higher chance of exhausting the budget before any code exists. The
    refinement loop is exactly that case, and when batching was first switched
    on its internal convergence began failing so often that refinement
    returned no new criteria on 14 of 24 attempts, against 3 of 16 before.
    """
    global _BATCH_OVERRIDE
    previous = _BATCH_OVERRIDE
    _BATCH_OVERRIDE = 0
    try:
        yield
    finally:
        _BATCH_OVERRIDE = previous


TRANSACTIONS_PATH = None  # set per run in orchestrate()
# The run's own timestamp and stage list, exposed for the same reason
# TRANSACTIONS_PATH is: the CLI has to assemble this run's artifacts after
# orchestrate() returns, and re-deriving a timestamp there would produce a
# different one and silently point at nothing.
RUN_TIMESTAMP = None
RUN_STAGES = ()
SAVE_TRANSACTIONS = True  # overridden per run from settings.yaml

def load_settings():
    """
    The bundled defaults, with your inputs_private/config/settings.yaml
    overlaid on top if you have one.

    Overlaid one top-level section at a time, not merged key by key: setting
    `orchestrator.max_retries_per_stage` privately keeps the bundled
    `orchestrator.test_order`, but a private `orchestrator:` section that
    omits a key it doesn't care about still inherits it. Whole-file
    replacement was the alternative and it's worse -- it means every private
    settings file has to restate every default, and silently drifts the day
    a new default is added.
    """
    settings = {}
    for path in (
        os.path.join(PUBLIC_INPUTS_DIR, "config", "settings.yaml"),
        os.path.join(project_root(), private_inputs_dir(), "config", "settings.yaml"),
    ):
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        for section, value in loaded.items():
            if isinstance(value, dict) and isinstance(settings.get(section), dict):
                settings[section].update(value)
            else:
                settings[section] = value
    if not settings:
        raise FileNotFoundError(
            f"No settings.yaml found. Expected bundled defaults at "
            f"{os.path.join(PUBLIC_INPUTS_DIR, 'config', 'settings.yaml')}"
        )
    return settings

def discover_task_ids():
    """
    List every task_id with a config in config/tasks/, across both the
    bundled examples and your own inputs_private/ -- the default set run.py
    runs when no specific task is requested. A private task file shadows a
    bundled one of the same name rather than running twice.
    """
    return sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in list_input_dir("config/tasks")
        if p.endswith(".yaml")
    )


def verify_task_id(task_id):
    """
    task_id namespaces this task's own inputs_private/data/, outputs/data/,
    outputs/tests/, and outputs/agent_src/code/ subtrees, so any number of
    differently shaped V&V tasks -- including several running concurrently
    in separate processes -- can coexist in this same project without their
    files colliding. It must double as a Python package segment (test files
    import the generated code through it), hence the identifier
    restriction. task_id is supplied by the caller (see run.py); this just
    validates it and confirms config/tasks/<task_id>.yaml agrees
    with itself, catching a renamed file whose internal task_id wasn't
    updated to match.
    """
    if not task_id or not TASK_ID_RE.match(task_id):
        raise ValueError(
            f"task_id must be a valid identifier (letters/digits/underscore, "
            f"not starting with a digit) -- got {task_id!r}"
        )
    path = task_config_path(task_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"task config not found at: {path}")
    with open(path, "r") as f:
        task_config = yaml.safe_load(f) or {}
    configured_id = task_config.get("task_id")
    if configured_id != task_id:
        raise ValueError(
            f"{path} is named for task_id {task_id!r} but its own task_id "
            f"field says {configured_id!r} -- rename the file or fix the field"
        )
    return task_id

def _warn_if_no_acceptance_criteria(task_id):
    """
    acceptance_criteria isn't required by anything in this file -- test
    generation (agent_generate_*_tests, agent_api/agent_interface.py) reads
    the task config in full regardless of whether it's set, and the coding
    agent's prompts only ever strip it if it's there. So a task missing it
    doesn't error, it just quietly loses the whole point: without a bar
    sharper than `requirements`, the coding agent has nothing hidden to fail
    against, and the run will likely converge trivially on the first
    attempt instead of exercising the FIX/PATCH loop at all. Surfaced as a
    warning, not an error, since an empty-criteria run is still valid to
    run deliberately (e.g. orchestrator/tuning/refine_acceptance_criteria.py's
    first round starts from a freshly-generated list, not a hand-written
    one -- see README.md#auto-generating-acceptance-criteria).
    """
    with open(task_config_path(task_id), "r") as f:
        task_config = yaml.safe_load(f) or {}
    if not task_config.get("acceptance_criteria"):
        print(
            f"[{task_id}] WARNING: no acceptance_criteria defined. Test generation "
            f"only has `requirements` to work with, so this run will likely converge "
            f"on the first attempt instead of exercising the FIX/PATCH loop. See "
            f"README.md#auto-generating-acceptance-criteria. Re-run with "
            f"--generate-criteria to have run.py generate and write a first draft "
            f"before this run."
        )


def generate_and_write_acceptance_criteria_if_missing(task_id, seed=None):
    """
    Explicit, opt-in *criteria seeding* for a task with no acceptance_criteria
    yet (run.py --generate-criteria) -- generates a one-shot first draft
    (agent_generate_acceptance_criteria) and writes it directly into this
    task's real config file.

    This is deliberately different from orchestrator/tuning/{eval,refine}_
    acceptance_criteria.py, which never write to a task's real config: those
    tools exist to evaluate generation quality against a task's existing,
    hand-tuned ground truth, so overwriting it would destroy the thing being
    measured. A task with no acceptance_criteria at all has no ground truth
    to protect -- writing a first draft is the actual point here, not a
    side effect to avoid. Always prints what it did (loudly, not silently)
    since a generated draft landing in version control unannounced would be
    a surprise worth avoiding.

    Does nothing and returns False if acceptance_criteria is already
    present, so a hand-tuned bar is never clobbered. Returns True if it
    generated and wrote a draft.
    """
    from qikly.agent_api.agent_interface import (
        agent_generate_acceptance_criteria, _ACCEPTANCE_CRITERIA_RE, _format_criteria_block,
    )

    path = task_config_path(task_id)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    task_config = yaml.safe_load(text) or {}
    if task_config.get("acceptance_criteria"):
        return False

    print(f"[{task_id}] --generate-criteria: no acceptance_criteria yet, generating a first draft from requirements alone...")
    criteria = agent_generate_acceptance_criteria(task_id, seed=seed)
    if not criteria:
        print(f"[{task_id}] --generate-criteria: generation returned nothing -- proceeding without acceptance_criteria.")
        return False

    criteria_block = _format_criteria_block(criteria)
    if _ACCEPTANCE_CRITERIA_RE.search(text):
        new_text = _ACCEPTANCE_CRITERIA_RE.sub(lambda m: criteria_block, text.rstrip() + "\n")
    else:
        new_text = text.rstrip() + "\n\n" + criteria_block

    # Written to inputs_private/, even when the task it read was a bundled
    # example -- see paths.private_input_path(). For a bundled task this
    # creates your own overriding copy, which from here on is the one that
    # runs; the packaged original stays untouched.
    out_path = private_input_path(f"config/tasks/{task_id}.yaml")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)

    print(
        f"[{task_id}] --generate-criteria: wrote {len(criteria)} auto-generated "
        f"acceptance_criteria to {out_path}. This is a first draft, not hand-tuned "
        f"ground truth -- review it (see README.md#auto-generating-acceptance-criteria) "
        f"rather than treating it as settled."
    )
    return True


def resolve_stage_order(settings):
    """
    Use settings.yaml's orchestrator.test_order when it's a sane permutation
    of the known stages, otherwise fall back to the default. "unit" must run
    last regardless of what the config says: it's generated from the code
    under test, which doesn't exist until the integration stage's interface-
    discovery bootstrap has created it and system has exercised it end-to-end.

    Two further things depend on "unit" being last, so don't relax this:
    regression re-checks only re-run *earlier* stages, so the last stage is
    never itself re-checked (nothing runs after it that could break it), and
    the bootstrap probe below targets stages[0], which must be a stage whose
    tests were written without seeing the implementation.
    """
    configured = (settings.get("orchestrator") or {}).get("test_order")
    if not configured:
        return DEFAULT_STAGE_ORDER
    if sorted(configured) != sorted(DEFAULT_STAGE_ORDER) or configured[-1] != "unit":
        return DEFAULT_STAGE_ORDER
    return configured

def log_transaction(entry):
    """
    Append one JSON event to this run's transactions log. Stamps "ts" (ISO
    timestamp) automatically so consumers (orchestrator/reports/report.py,
    orchestrator/reports/metrics_report.py, orchestrator/live_view.py) can
    compute durations and tail the log for live progress without every call
    site having to pass its own timestamp.
    """
    if not SAVE_TRANSACTIONS:
        return
    entry = {"ts": datetime.now().isoformat(), **entry}
    with open(TRANSACTIONS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()

def generate_patch_id():
    return str(uuid.uuid4())[:8]

def ensure_dirs(run_patch_dir):
    os.makedirs(run_patch_dir, exist_ok=True)

def backup_and_clear_agent_src(run_timestamp, agent_src_dir):
    """
    Start each run from a clean outputs/agent_src/code/<task_id>/, moving
    whatever's there into a timestamped folder under
    outputs/agent_src/code/<task_id>/old/ first. agent_src_dir is already
    task-specific (see agent_src_code_path()), so two tasks' runs -- even
    concurrent ones in separate processes -- never touch the same directory.
    """
    if not os.path.isdir(agent_src_dir):
        return

    entries = [e for e in os.listdir(agent_src_dir) if e != "old"]
    if not entries:
        return

    backup_dir = os.path.join(agent_src_dir, "old", run_timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    for name in entries:
        shutil.move(os.path.join(agent_src_dir, name), os.path.join(backup_dir, name))

def backup_and_clear_generated_tests(run_timestamp, tests_dir):
    """
    Move any test files generated by a previous run out of tests_dir into a
    timestamped backup folder under tests_dir/old/ before this run generates
    fresh ones -- mirrors backup_and_clear_agent_src().
    """
    if not os.path.isdir(tests_dir):
        return

    entries = [e for e in os.listdir(tests_dir) if e != "old"]
    if not entries:
        return

    backup_dir = os.path.join(tests_dir, "old", run_timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    for name in entries:
        shutil.move(os.path.join(tests_dir, name), os.path.join(backup_dir, name))

def load_seed_spec(task_id):
    """
    Read a task's optional `seed:` block, which lets a user supply their own
    starting point instead of having this run generate one:

        seed:
          implementation: "seeds/CALC_TAX/calc.py"   # file or directory
          tests:
            integration: "seeds/CALC_TAX/test_integration.py"
            unit: "seeds/CALC_TAX/unit/"             # file or directory

    Returns (implementation_path_or_None, {stage: path}). Paths are relative
    to the project root (everything here runs after chdir_to_project_root()).

    Both keys are optional and independent: seed the code, seed some or all
    test stages, seed both, or neither. Seeding tests for a stage suppresses
    generation for that stage only. Seeding the implementation suppresses the
    interface-discovery bootstrap, since there is already code to test.

    Note that acceptance_criteria are *already* user-supplied by default --
    hand-writing them in the task config is the normal path, and
    --generate-criteria is the opt-in for a task that has none. So this
    completes the set: all three inputs to the loop (criteria, code, tests)
    can come from outside it.
    """
    with open(task_config_path(task_id), "r") as f:
        task_config = yaml.safe_load(f) or {}
    seed = task_config.get("seed") or {}
    if not isinstance(seed, dict):
        raise ValueError(
            f"[{task_id}] `seed:` must be a mapping with optional "
            f"`implementation:` and `tests:` keys -- got {type(seed).__name__}"
        )
    implementation = seed.get("implementation")
    tests = seed.get("tests") or {}
    if not isinstance(tests, dict):
        raise ValueError(
            f"[{task_id}] `seed.tests:` must be a mapping of stage name to "
            f"path (e.g. `integration: path/to/test_integration.py`) -- got "
            f"{type(tests).__name__}"
        )
    unknown = sorted(set(tests) - set(TEST_GENERATORS))
    if unknown:
        raise ValueError(
            f"[{task_id}] `seed.tests:` names unknown stage(s) {unknown} -- "
            f"valid stages are {sorted(TEST_GENERATORS)}"
        )
    return implementation, tests

def install_seed(src, dest_dir, filename=None):
    """
    Copy a seed file or directory into dest_dir, which the caller has already
    reset. Copying *after* the reset rather than skipping the reset is
    deliberate: every run still starts from one declared state, so repeated
    runs of a task stay comparable to each other and no run inherits the
    previous run's residue. The declared state is just a supplied one instead
    of an empty one.

    A single file keeps its own basename unless `filename` overrides it --
    the implementation's basename has to match the task's interface.module,
    so it is never renamed, while a seeded test file is renamed to the
    canonical name for its stage.

    Returns the list of paths written.
    """
    if not os.path.exists(src):
        raise FileNotFoundError(
            f"seed path not found: {src} (paths are relative to the project "
            f"root, {project_root()})"
        )
    os.makedirs(dest_dir, exist_ok=True)
    written = []

    if os.path.isfile(src):
        target = os.path.join(dest_dir, filename or os.path.basename(src))
        shutil.copy2(src, target)
        return [target]

    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "old")]
        rel = os.path.relpath(root, src)
        target_root = dest_dir if rel == "." else os.path.join(dest_dir, rel)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            if name.endswith(".pyc"):
                continue
            target = os.path.join(target_root, name)
            shutil.copy2(os.path.join(root, name), target)
            written.append(target)

    if not written:
        raise ValueError(f"seed directory contained no files to copy: {src}")
    return written

def validate_seed_tests(stage, installed):
    """
    Same guard as _validate_generated_tests below, applied to a seeded stage.
    A seeded suite gates the run exactly as a generated one does, so the same
    failure mode applies: an unparseable or empty suite makes pytest report a
    collection error or "no tests collected", the loop reads that as an
    ordinary test failure, and the coding agent burns its whole budget on a
    problem that is in the test file rather than in its code.

    Unlike generated tests this raises instead of retrying. There is no second
    sample to draw from a file the user wrote, so the useful response is to
    stop immediately and say what is wrong with it.

    Checks are collective across the stage, since a seeded directory may
    legitimately split helpers out from tests: every .py file must parse, and
    at least one must be named test_*.py and contain a def test_* function,
    which is what pytest will actually collect.
    """
    problems = []
    collectible = []

    for path in installed:
        if not path.endswith(".py"):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        try:
            # Compile the bytes rather than a decoded string so a PEP 263
            # coding declaration is honoured the same way import would.
            compile(raw, path, "exec")
        except SyntaxError as e:
            problems.append(f"{path} is not valid Python: {e}")
            continue
        source = raw.decode("utf-8", errors="replace")
        if os.path.basename(path).startswith("test_") and re.search(
            r"^def test_\w+\s*\(", source, re.MULTILINE
        ):
            collectible.append(path)

    if not collectible:
        problems.append(
            "nothing here is collectible: pytest only picks up files named "
            "test_*.py containing `def test_*` functions"
        )

    if problems:
        raise ValueError(
            f"seeded {stage} tests would gate this run but are unusable:\n  - "
            + "\n  - ".join(problems)
        )

def _validate_generated_tests(source, stage):
    """
    Catch a garbage LLM test-generation response before it's used to gate
    the whole pipeline. Without this, invalid syntax or a file with no
    test_ functions would just make pytest report "no tests collected" (or
    a collection error) as a normal test failure -- and the coding agent
    would then burn its entire attempt budget on a failure it structurally
    cannot fix, since the problem is the test file, not its code.
    Returns an error string, or None if the source looks usable.
    """
    try:
        compile(source, f"<generated {stage} tests>", "exec")
    except SyntaxError as e:
        return f"generated {stage} test file is not valid Python: {e}"

    if not re.search(r"^def test_\w+\s*\(", source, re.MULTILINE):
        return f"generated {stage} test file contains no test_ functions"

    return None

GENERATE_TESTS_MAX_ATTEMPTS = 3

def generate_and_write_tests(stage, tests_dir, task_id, seed=None):
    """
    Call the LLM to generate the test file for `stage` and write it to
    <tests_dir>/<stage>/<filename>. Returns the written path.
    Retries generation up to GENERATE_TESTS_MAX_ATTEMPTS times if the result
    fails basic validation -- a syntax error is a one-off generation
    mistake, not a sign the model can't do the task, so a run shouldn't
    crash outright on the first two failures in a row when a third
    independent sample is likely to succeed.

    Each retry perturbs the seed (seed+attempt-1) rather than reusing the
    exact same one. When a run seed is set, generation is deliberately
    near-deterministic (see README.md's Determinism note) -- confirmed
    directly: retrying with the identical seed reproduced the exact same
    invalid line, byte-for-byte, three times in a row on a real run, so a
    same-seed retry was providing no real second chance at all. This only
    affects internal test-generation retries; the seed passed everywhere
    else (FIX/PATCH, the run's other test stages) is untouched, so run-level
    reproducibility is unaffected.
    """
    generator, filename = TEST_GENERATORS[stage]
    batches = criteria_batches(task_id, criteria_per_batch())

    stage_dir = os.path.join(tests_dir, stage)
    os.makedirs(stage_dir, exist_ok=True)
    written = []

    for index, batch in enumerate(batches, start=1):
        source = _generate_one(stage, generator, task_id, seed, batch, index)
        # One file per batch rather than one merged file. Concatenating
        # generated modules looks tidier and silently loses tests: two batches
        # that both define test_rejects_empty_row leave only the second, and
        # nothing reports the loss. Separate files let pytest collect both.
        name = filename if len(batches) == 1 else \
            f"{filename[:-3]}_{index}.py"
        test_path = os.path.join(stage_dir, name)
        with open(test_path, "w", newline="\n") as f:
            f.write(source)
        written.append(test_path)
        log_transaction({"stage": stage, "test_path": test_path,
                         "batch": index, "batches": len(batches),
                         "criteria_in_batch": None if batch is None else len(batch),
                         "action": "tests_generated"})

    return written[0]


def _generate_one(stage, generator, task_id, seed, criteria, batch_index):
    """
    One generation call, retried on invalid output.

    Each retry perturbs the seed rather than reusing it: with a run seed set,
    generation is near-deterministic, and a same-seed retry was confirmed to
    reproduce the identical invalid line three times in a row, so it provided
    no second chance at all. Batches perturb it further so two batches of the
    same task do not come back as the same file.
    """
    source = None
    for attempt in range(1, GENERATE_TESTS_MAX_ATTEMPTS + 1):
        attempt_seed = seed
        if seed is not None:
            attempt_seed = seed + attempt - 1 + 1000 * (batch_index - 1)
        source = generator(task_id, seed=attempt_seed, criteria=criteria)
        error = _validate_generated_tests(source, stage)
        if not error:
            return source
        if attempt < GENERATE_TESTS_MAX_ATTEMPTS:
            log_transaction({"stage": stage, "error": error, "source": source,
                             "attempt": attempt, "action": "tests_generation_invalid_retry"})
        else:
            # Log the invalid source before raising: otherwise the only trace
            # of what the model produced is the error message, which is not
            # enough to tell a one-off fluke from a prompt problem.
            log_transaction({"stage": stage, "error": error, "source": source,
                             "attempt": attempt, "action": "tests_generation_invalid_failed"})
            raise RuntimeError(
                f"LLM-generated {stage} tests failed validation "
                f"{GENERATE_TESTS_MAX_ATTEMPTS} times in a row: {error}"
            )
    return source

def agent_src_has_code(agent_src_dir):
    if not os.path.isdir(agent_src_dir):
        return False
    for root, dirs, files in os.walk(agent_src_dir):
        dirs[:] = [d for d in dirs if d != "old"]
        if any(f.endswith(".py") for f in files):
            return True
    return False

def check_for_regressions(prior_stages, tests_dir, task_id, run_timestamp, total_stages, attempt_label):
    """
    Re-run every stage that already passed earlier in this run, to catch a
    later stage's patch silently breaking one of them -- nothing else in the
    loop re-verifies a stage once it's moved past, since each stage only
    re-runs its own tests. Returns (stage_name, result) for the first
    regressed stage found, or (None, None) if all of them still pass.
    """
    for idx, prior_stage in enumerate(prior_stages, start=1):
        result = run_tests(
            prior_stage, tests_dir, task_id=task_id, iteration=attempt_label, run_timestamp=run_timestamp,
            stage_number=idx, total_stages=total_stages,
            junit_path=junit.stage_path(task_id, run_timestamp, prior_stage),
        )
        log_transaction({
            "action": "test_run", "stage": prior_stage, "iteration": attempt_label, "stage_number": idx,
            "status": result["status"], "counts": result.get("counts"), "tests": result.get("tests"),
            "failed_tests": result.get("failed_tests"), "is_regression_check": True,
        })
        if result["status"] != "pass":
            return prior_stage, result
    return None, None

def run_fix_patch_cycle(task_id, stage, failure_info, run_patch_dir, iteration, seed=None,
                         previous_patch=None, previous_patch_error=None,
                         previous_ineffective_patch=None, previous_patch_too_large=False,
                         max_patch_size=None):
    """
    One FIX -> PATCH -> apply cycle. Returns (success, fix_id, patch_path, error, failure_kind).
    failure_kind identifies *why* success is False ("fix_generation_failed",
    "patch_generation_failed", "too_large", "apply_failed"), so the caller can
    give the next attempt retry guidance that matches the actual problem
    instead of generic apply-failure advice.
    """
    fix_id = generate_patch_id()

    log_transaction({
        "iteration": iteration,
        "fix_id": fix_id,
        "stage": stage,
        "failure": failure_info,
        "repeat_failure": previous_ineffective_patch is not None,
        "action": "agent_fix_requested"
    })

    # Ask agent for FIX (reasoning)
    try:
        fix = agent_generate_fix(
            task_id, failure_info, seed=seed, previous_ineffective_patch=previous_ineffective_patch
        )
    except Exception as e:
        log_transaction({
            "iteration": iteration,
            "fix_id": fix_id,
            "stage": stage,
            "error": str(e),
            "action": "fix_generation_failed"
        })
        return False, fix_id, None, str(e), "fix_generation_failed"

    log_transaction({
        "iteration": iteration,
        "fix_id": fix_id,
        "stage": stage,
        "fix": fix,
        "action": "agent_fix_generated"
    })

    # Ask agent for PATCH (diff), including the previous failed attempt if any
    try:
        patch = agent_generate_patch(
            task_id, fix, seed=seed, previous_patch=previous_patch, previous_patch_error=previous_patch_error,
            previous_patch_too_large=previous_patch_too_large
        )
    except Exception as e:
        log_transaction({
            "iteration": iteration,
            "fix_id": fix_id,
            "stage": stage,
            "error": str(e),
            "action": "patch_generation_failed"
        })
        return False, fix_id, None, str(e), "patch_generation_failed"

    patch_path = os.path.join(run_patch_dir, f"{fix_id}.diff")
    # encoding="utf-8" explicitly. Without it Python uses the platform's
    # locale encoding, which on Windows is cp1252, so the diff is written
    # in one encoding and read back in another. That is how byte 0x97
    # reached a reader: the model emitted an em dash, cp1252 stored it as
    # one byte, and the UTF-8 read raised on it. A character cp1252 cannot
    # represent at all would have failed here instead, at write time.
    with open(patch_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(patch)

    log_transaction({
        "iteration": iteration,
        "fix_id": fix_id,
        "stage": stage,
        "patch_path": patch_path,
        "action": "patch_created"
    })

    if max_patch_size and len(patch) > max_patch_size:
        error = (
            f"Generated PATCH is {len(patch)} characters, exceeding the "
            f"configured max_patch_size of {max_patch_size}. Keep the diff "
            f"smaller and change only what's necessary."
        )
        log_transaction({
            "iteration": iteration,
            "fix_id": fix_id,
            "stage": stage,
            "error": error,
            "action": "patch_too_large"
        })
        return False, fix_id, patch_path, error, "too_large"

    # The human gate, when there is one. Default is apply, so this is a
    # no-op unless someone asked for review or a dry run.
    approved, why = approval.decide(patch, fix_id, stage, iteration)
    if not approved:
        log_transaction({
            "iteration": iteration,
            "fix_id": fix_id,
            "stage": stage,
            "patch_path": patch_path,
            "reason": why,
            "action": "patch_not_applied",
        })
        # The diff stays on disk. A rejection is a fact about this run, and a
        # patch that vanished when it was declined would make a steered run
        # indistinguishable from an unsteered one afterwards.
        return False, fix_id, patch_path, why, "not_applied"

    try:
        apply_patch(patch_path)
    except Exception as e:
        log_transaction({
            "iteration": iteration,
            "fix_id": fix_id,
            "stage": stage,
            "error": str(e),
            "action": "patch_apply_failed"
        })
        return False, fix_id, patch_path, str(e), "apply_failed"

    return True, fix_id, patch_path, None, None

def existing_stage_tests(tests_dir, stage):
    """Test files already on disk for one stage, ignoring the archive."""
    d = os.path.join(tests_dir, stage)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".py"))


def resumable(task_id):
    """
    What a previous run left behind that a new one could continue from.

    A run that dies partway, out of credit, killed, a provider outage, leaves
    generated suites and often a converged implementation on disk, and every
    one of those cost model calls. Starting again throws all of it away and
    pays for it a second time, which is the whole reason this exists.
    """
    tests_dir = os.path.join(GENERATED_TESTS_ROOT, task_id)
    stages = {}
    for stage in TEST_GENERATORS:
        files = existing_stage_tests(tests_dir, stage)
        if files:
            stages[stage] = files
    code_dir = agent_src_code_path(task_id)
    return {"tests": stages, "implementation": agent_src_has_code(code_dir)}


def _stuck_reason(patch_hashes):
    """
    Why this stage cannot make progress, or None if it still might.

    A model that has run out of ideas does not fail in new ways. It proposes
    the diff it already tried, or alternates between two of them, and every
    attempt after that costs a call and cannot succeed. An attempt budget
    catches this eventually, but only by spending the whole budget: one
    observed demo run burned nine identical iterations on the same failing
    test before the limit stopped it.

    Two patterns, both needing three applied patches before they can fire, so
    that a model legitimately refining the same area twice is not cut off:

      repetition   the last three diffs are byte for byte identical
      oscillation  the last three alternate between two diffs, A B A

    Only APPLIED patches count. A diff that failed to apply is a different
    problem, and the retry prompts for that already exist.
    """
    if len(patch_hashes) < 3:
        return None
    a, b, c = patch_hashes[-3:]
    if a == b == c:
        return "the last three patches were byte for byte identical"
    if a == c and a != b:
        return "the last three patches alternated between the same two diffs"
    return None


def orchestrate(task_id, seed=None, resume=False):
    global TRANSACTIONS_PATH, SAVE_TRANSACTIONS, RUN_TIMESTAMP, RUN_STAGES

    task_id = verify_task_id(task_id)
    _warn_if_no_acceptance_criteria(task_id)
    # Before anything reads the spec: the generated code will open this
    # task's fixtures at inputs_private/data/<task_id>/ relative to the working
    # directory, so they have to exist there. No-op after the first run, and
    # never overwrites a fixture you've edited.
    ensure_task_data(task_id)
    settings = load_settings()
    SAVE_TRANSACTIONS = (settings.get("logging") or {}).get("save_transactions", True)
    max_attempts_per_stage = (settings.get("orchestrator") or {}).get(
        "max_retries_per_stage", DEFAULT_MAX_ATTEMPTS_PER_STAGE
    )
    max_patch_size = (settings.get("agent") or {}).get("max_patch_size")
    stages = resolve_stage_order(settings)
    tests_dir = os.path.join(GENERATED_TESTS_ROOT, task_id)
    agent_src_dir = agent_src_code_path(task_id)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # task_id is embedded in every per-run path below (transactions log,
    # patch dir, and inside run_tests()'s report filenames) so that two
    # tasks' runs -- including concurrent ones in separate processes --
    # never share a file, even if their timestamps collide.
    TRANSACTIONS_PATH = os.path.join(LOG_DIR, f"transactions_{task_id}_{run_timestamp}.jsonl")
    RUN_TIMESTAMP = run_timestamp
    RUN_STAGES = tuple(stages)
    run_patch_dir = os.path.join(PATCH_DIR, task_id, run_timestamp)

    ensure_dirs(run_patch_dir)

    seed_implementation, seed_tests = load_seed_spec(task_id)
    if seed_implementation or seed_tests:
        seeded = (["implementation"] if seed_implementation else []) + sorted(seed_tests)
        print(
            f"[{task_id}] NOTE: seeded run -- supplying {', '.join(seeded)} from the "
            f"task's `seed:` block instead of generating them. Seeded runs measure a "
            f"different thing from unseeded ones, so don't pool them in one rate."
        )

    # Generate this run's pre-implementation test files from the spec alone,
    # before outputs/agent_src/code/<task_id>/ is cleared -- they don't
    # depend on the implementation. The "unit" stage's tests are generated
    # later, once real code exists for them to target. Any stage named in
    # `seed.tests` is installed from the user's file instead of generated.
    # Resuming keeps whatever the previous attempt generated. Clearing it is
    # what makes an ordinary re-run cost full price after a failure: the
    # suites and the implementation are both already paid for, and neither
    # gets better by being generated again.
    reusable = resumable(task_id) if resume else {"tests": {}, "implementation": False}
    if reusable["tests"] or reusable["implementation"]:
        log_transaction({"action": "resuming", "stages": sorted(reusable["tests"]),
                         "implementation": reusable["implementation"]})
        print(f"[{task_id}] resuming: keeping "
              f"{', '.join(sorted(reusable['tests'])) or 'no suites'}"
              f"{' and the implementation' if reusable['implementation'] else ''}")
    else:
        backup_and_clear_generated_tests(run_timestamp, tests_dir)

    for stage, path in seed_tests.items():
        _, canonical_filename = TEST_GENERATORS[stage]
        installed = install_seed(path, os.path.join(tests_dir, stage), canonical_filename)
        validate_seed_tests(stage, installed)
        log_transaction({
            "action": "seed_installed", "kind": "tests", "stage": stage,
            "source": path, "files": installed,
        })
    # Say what is happening. Generating a suite is one model call per stage
    # and takes a few seconds each, during which nothing else prints: the run
    # looked hung between "Running with seed=..." and the first test result.
    # An unexplained pause in a tool that spends money reads as a fault.
    pending = [st for st in stages
               if st != "unit" and st not in seed_tests and st not in reusable["tests"]]
    for number, stage in enumerate(pending, start=1):
        # No [task_id] prefix here: _run_task_process already wraps print()
        # to add one, so writing it by hand prints it twice.
        print(f"generating {stage} tests from the spec "
              f"({number} of {len(pending)}) ...", flush=True)
        generate_and_write_tests(stage, tests_dir, task_id, seed=seed)
        print(f"{stage} tests written, before any code exists", flush=True)

    if not reusable["implementation"]:
        backup_and_clear_agent_src(run_timestamp, agent_src_dir)
    if seed_implementation and not reusable["implementation"]:
        installed = install_seed(seed_implementation, agent_src_dir)
        log_transaction({
            "action": "seed_installed", "kind": "implementation",
            "source": seed_implementation, "files": installed,
        })

    if not agent_src_has_code(agent_src_dir):
        # No implementation: outputs/agent_src/code/<task_id>/ was just reset
        # and no `seed.implementation` was supplied to refill it. So this
        # first run of the first stage's tests is guaranteed to fail on
        # collection ("No module named '<interface.module>'"). Run it for
        # real anyway. The point is NOT that the failure teaches the agent
        # the interface -- it already has interface.module and every
        # signature from the task config, which is stripped of
        # acceptance_criteria only. What running it for real buys:
        #
        #   1. First code is created by the same FIX/PATCH cycle as every
        #      later repair. There is no separate "write the initial
        #      implementation" prompt or code path to keep in sync.
        #   2. The traceback shows the generated test's actual import line,
        #      so the agent targets the module path as pytest resolves it
        #      here rather than as it reads the dotted name in the config.
        #
        # It doesn't count against the stage's attempt budget since we
        # already know it'll fail.
        bootstrap_result = run_tests(
            stages[0], tests_dir, task_id=task_id, iteration=0, run_timestamp=run_timestamp,
            stage_number=1, total_stages=len(stages),
            junit_path=junit.stage_path(task_id, run_timestamp, stages[0]),
        )
        log_transaction({
            "action": "test_run", "stage": stages[0], "iteration": 0, "stage_number": 1,
            "status": bootstrap_result["status"], "counts": bootstrap_result.get("counts"),
            "tests": bootstrap_result.get("tests"), "failed_tests": bootstrap_result.get("failed_tests"),
            "is_regression_check": False, "is_bootstrap": True,
        })
        if bootstrap_result["status"] != "pass":
            failure_info = inspect_failure(bootstrap_result)
            run_fix_patch_cycle(
                task_id, "bootstrap", failure_info, run_patch_dir, iteration=0, seed=seed,
                max_patch_size=max_patch_size
            )

    for stage_number, stage in enumerate(stages, start=1):
        if stage == "unit" and stage not in seed_tests:
            # Only generated now, from the code that just cleared the
            # integration/system stages -- this is the one point in the
            # pipeline where test generation is allowed to see the
            # implementation it's testing. A seeded unit stage was already
            # installed before the run started, and is skipped here.
            generate_and_write_tests("unit", tests_dir, task_id, seed=seed)

        attempts = 0
        previous_patch = None
        previous_patch_error = None
        previous_patch_too_large = False
        # Signature of the failure that the most recently *applied* patch was
        # trying to fix, and that patch's content -- used to detect when a
        # patch applies cleanly but doesn't actually change the test outcome.
        pending_fix_signature = None
        pending_fix_patch = None
        # Hashes of the diffs applied on this stage, oldest first. A model
        # that has run out of ideas does not fail in new ways: it proposes the
        # same diff again, or alternates between two. Every further attempt
        # after that costs a call and cannot succeed.
        applied_patch_hashes = []
        # Consecutive patches that applied cleanly and left the failure
        # unchanged. This is the counter that catches a real stall; the hashes
        # above only catch a model repeating itself word for word.
        ineffective_streak = 0

        while True:
            attempts += 1

            # Run tests for this stage
            result = run_tests(
                stage, tests_dir, task_id=task_id, iteration=attempts, run_timestamp=run_timestamp,
                stage_number=stage_number, total_stages=len(stages),
                junit_path=junit.stage_path(task_id, run_timestamp, stage),
            )
            log_transaction({
                "action": "test_run", "stage": stage, "iteration": attempts, "stage_number": stage_number,
                "status": result["status"], "counts": result.get("counts"), "tests": result.get("tests"),
                "failed_tests": result.get("failed_tests"), "is_regression_check": False,
            })

            # A stage passing isn't enough on its own: a patch made to reach
            # this point could have silently broken an earlier stage, since
            # nothing else re-runs a stage once it's been left behind.
            regressed_stage, regressed_result = None, None
            if result["status"] == "pass" and stage_number > 1:
                regressed_stage, regressed_result = check_for_regressions(
                    stages[:stage_number - 1], tests_dir, task_id, run_timestamp, len(stages),
                    attempt_label=f"{attempts}-regcheck"
                )

            if result["status"] == "pass" and regressed_stage is None:
                break  # move to next stage

            if attempts > max_attempts_per_stage:
                if regressed_stage is not None:
                    raise RuntimeError(
                        f"Exceeded {max_attempts_per_stage} attempts on stage '{stage}': "
                        f"stage '{regressed_stage}', which previously passed, keeps "
                        f"regressing after each fix."
                    )
                raise RuntimeError(
                    f"Exceeded {max_attempts_per_stage} attempts on stage '{stage}' without passing tests."
                )

            stuck = _stuck_reason(applied_patch_hashes)
            if stuck:
                log_transaction({"action": "stopped_stuck", "stage": stage,
                                 "iteration": attempts, "reason": stuck})
                raise RuntimeError(
                    f"Stopped on stage '{stage}' after {attempts - 1} attempts: {stuck}. "
                    f"Every further attempt would cost a model call and produce the same "
                    f"diff. The report names the tests that never passed."
                )

            # Capture failure -- either this stage's own, or a regression in
            # a stage that already passed earlier in this run.
            if result["status"] != "pass":
                failure_info = inspect_failure(result)
                current_signature = failure_signature(result)
            else:
                failure_info = (
                    f"REGRESSION: stage '{regressed_stage}' previously passed, but the "
                    f"latest change to outputs/agent_src/code/ broke it again.\n\n"
                    + inspect_failure(regressed_result)
                )
                current_signature = f"regression:{regressed_stage}:{failure_signature(regressed_result)}"

            previous_ineffective_patch = None
            if pending_fix_patch is not None and current_signature == pending_fix_signature:
                # The last patch applied cleanly, but the failure is unchanged.
                previous_ineffective_patch = pending_fix_patch
                ineffective_streak += 1
            else:
                ineffective_streak = 0

            # A repeated failure is NOT a stall, and this must not become an
            # abort again. It was one, briefly, stopping the stage after three
            # patches that left the same tests failing. The very next recorded
            # run disproved it: unit iterations 2 through 7 all reported 11/12
            # with the identical signature, and iteration 8 passed. Aborting at
            # three would have thrown away a run that converged.
            #
            # A model grinding at one failing test for six attempts is what
            # working on a hard case looks like from outside. Only a byte
            # identical diff proves nothing can change, which is what
            # _stuck_reason above tests. So this counter only narrates.
            if ineffective_streak == 3:
                print(f"[{task_id}] same failure for {ineffective_streak + 1} "
                      f"attempts now, still trying", flush=True)

            success, fix_id, patch_path, error, failure_kind = run_fix_patch_cycle(
                task_id, stage, failure_info, run_patch_dir, iteration=attempts, seed=seed,
                previous_patch=previous_patch, previous_patch_error=previous_patch_error,
                previous_ineffective_patch=previous_ineffective_patch,
                previous_patch_too_large=previous_patch_too_large,
                max_patch_size=max_patch_size
            )
            if not success:
                previous_patch_error = error
                previous_patch_too_large = (failure_kind == "too_large")
                if patch_path is not None:
                    # errors="replace", for the same reason the code loader
                    # and apply_patch use it: this is a diff the model wrote,
                    # and a cp1252 byte in it (0x97, an em dash, is the one
                    # that actually happened) must reach the next prompt as a
                    # replacement character rather than end the run. Bad model
                    # output is what this loop exists to fix.
                    with open(patch_path, "r", encoding="utf-8",
                              errors="replace") as f:
                        previous_patch = f.read()
                else:
                    # FIX or PATCH generation itself failed before any diff
                    # was produced (e.g. a truncated LLM response) -- there's
                    # no previous diff content to show the model.
                    previous_patch = None
                pending_fix_signature = None
                pending_fix_patch = None
                continue  # ask the agent for a fresh FIX/PATCH

            previous_patch = None
            previous_patch_error = None
            previous_patch_too_large = False
            pending_fix_signature = current_signature
            with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
                pending_fix_patch = f.read()
            applied_patch_hashes.append(
                hashlib.sha1(pending_fix_patch.encode("utf-8", "replace")).hexdigest())

    # All stages passed
    log_transaction({"action": "all_tests_passed"})
