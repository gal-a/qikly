from qikly.agent_api.call_llm import call_llm
from qikly.agent_api.prompts.acceptance_criteria_prompt import build_acceptance_criteria_prompt
from qikly.agent_api.prompts.acceptance_criteria_review_prompt import build_acceptance_criteria_review_prompt
from qikly.agent_api.prompts.fixture_proposal_prompt import build_fixture_proposal_prompt, read_fixtures
from qikly.agent_api.prompts.fix_prompt import build_fix_prompt
from qikly.agent_api.prompts.patch_prompt import build_patch_prompt
from qikly.agent_api.prompts.integration_test_prompt import build_integration_test_prompt
from qikly.agent_api.prompts.system_test_prompt import build_system_test_prompt
from qikly.agent_api.prompts.unit_test_prompt import build_unit_test_prompt
from qikly.agent_api.code_loader.code_loader import load_codebase, load_target_files

import difflib
import json
import os
import re

from qikly.paths import list_input_dir, resolve_input

# Resolved per call rather than bound once at import: which file answers
# "code_agent.md" depends on whether the project has an inputs_private/
# override, and binding at import time would freeze that decision before a
# caller has had a chance to chdir into the project.
def agent_md_path():
    return resolve_input("agent_defs/code_agent.md")


def test_agent_md_path():
    return resolve_input("agent_defs/test_agent.md")


AGENT_SRC_ROOT = "outputs/agent_src/code"

_ACCEPTANCE_CRITERIA_RE = re.compile(r"^acceptance_criteria:.*?(?=^\S|\Z)", re.MULTILINE | re.DOTALL)
_TARGET_FILES_RE = re.compile(r"^target_files:\s*\n((?:[ \t]*-.*\n?)*)", re.MULTILINE)

# Known task-type prefixes. Add a new domain family's prefix here when it's
# added to config/tasks/, so task_type() recognizes it instead of falling
# back to the full task_id.
_TASK_TYPES = ("ETL", "CALC", "MERGE")


def task_type(task_id):
    """
    The task-type prefix (the part before the first underscore) -- ETL,
    CALC, MERGE, ... -- used to group findings/reports by domain family
    (see orchestrator/tuning/refine_acceptance_criteria.py's multi-task
    summary). Falls back to the full task_id if it doesn't match a known
    prefix, rather than guessing or raising -- an unrecognized prefix just
    means a new task type that hasn't been added to _TASK_TYPES yet.
    """
    prefix = task_id.split("_", 1)[0]
    return prefix if prefix in _TASK_TYPES else task_id


def task_config_path(task_id):
    """
    config/tasks/<task_id>.yaml -- one file per V&V task, so any number of
    tasks can be defined side by side and selected independently (see
    run.py's task discovery / multiprocessing driver). Resolves to your
    inputs_private/ copy if you have written one, else the bundled example.
    """
    return resolve_input(f"config/tasks/{task_id}.yaml")


def agent_src_code_path(task_id):
    """
    outputs/agent_src/code/<task_id>/ -- each task gets its own code
    subtree. This is what actually makes running multiple tasks
    concurrently (one process per task) safe: without the per-task
    subfolder, two processes would clear and rewrite the same shared
    outputs/agent_src/code/ directory out from under each other.
    """
    return os.path.join(AGENT_SRC_ROOT, task_id)


def _available_task_ids():
    """
    Duplicates orchestrator.orchestrator.discover_task_ids()'s logic rather
    than importing it -- orchestrator.py already imports from this module,
    so importing back would be circular. Both are one call to
    list_input_dir(), low risk of drifting apart.
    """
    return sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in list_input_dir("config/tasks")
        if p.endswith(".yaml")
    )


def _read_task(task_id):
    path = task_config_path(task_id)
    if not os.path.exists(path):
        suggestion = difflib.get_close_matches(task_id, _available_task_ids(), n=1)
        hint = f" Did you mean {suggestion[0]!r}?" if suggestion else ""
        raise FileNotFoundError(f"task config not found at: {path}.{hint}")
    return open(path).read()


def _task_without_acceptance_criteria(task_id):
    """
    Read this task's config with its acceptance_criteria section removed,
    for the coding agent's FIX/PATCH prompts. Test generation reads the
    task config in full (see agent_generate_*_tests below) --
    acceptance_criteria is the bar QA holds the implementation to, not
    something handed to the developer up front. Coding and test generation
    otherwise share the same model at temperature=0 with a fixed seed, so
    without withholding something, both sides read the spec identically and
    every stage passes on the first attempt. This asymmetry is what makes
    the coding agent's first attempt genuinely fallible, the way a
    developer working from requirements alone would be.
    """
    task_text = _read_task(task_id)
    stripped = _ACCEPTANCE_CRITERIA_RE.sub("", task_text)
    return stripped.rstrip() + "\n"


def _extract_target_files(fix_text):
    """
    Pull the file paths out of a FIX's target_files: list (see
    agent_defs/code_agent.md for the format the model is asked to
    follow). Used so the PATCH prompt only has to load the files the FIX
    said it would touch, not the whole task codebase. Returns [] if the
    section is missing or empty -- callers should fall back to loading
    everything rather than giving the model no code context at all.
    """
    match = _TARGET_FILES_RE.search(fix_text)
    if not match:
        return []
    files = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith("-"):
            files.append(line[1:].strip().strip('"').strip("'"))
    return [f for f in files if f]


def agent_generate_acceptance_criteria(task_id, seed=None):
    """
    Proposes acceptance_criteria from a task's requirements/interface/
    description alone, playing the QA-hardening role a human currently has
    to play by hand (see agent_defs/acceptance_criteria_prompt.md).
    Returns a plain list[str] -- deliberately not written to any file, so a
    caller can merge in user-supplied custom criteria with a plain
    `generated + custom` and so this never mutates an existing task's real,
    hand-tuned acceptance_criteria as a side effect.
    """
    task = _task_without_acceptance_criteria(task_id)
    prompt = build_acceptance_criteria_prompt(task)
    raw = call_llm("acceptance_criteria", prompt, seed=seed)
    return _extract_criteria_list(raw)


def _extract_criteria_list(text):
    """
    Parses a `- "..."` YAML-bullet-list response (see
    acceptance_criteria_prompt.md's required output format) into a list of
    strings, tolerant of stray markdown fences the model might add anyway
    (same tolerance _extract_diff/_extract_python already apply elsewhere).
    """
    match = re.search(r"```(?:yaml)?\s*\n(.*?)(?:```|\Z)", text, re.DOTALL)
    body = match.group(1) if match else text
    criteria = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("-"):
            item = line[1:].strip()
            if len(item) >= 2 and item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            if item:
                criteria.append(item)
    return criteria


def _format_criteria_block(criteria):
    """
    Inverse of _extract_criteria_list -- renders a list[str] back into an
    `acceptance_criteria:` YAML section matching the format real task files
    use. Shared by run.py's --generate-criteria criteria seeding
    (orchestrator/orchestrator.py) and
    orchestrator/tuning/refine_acceptance_criteria.py's scratch-file writer,
    so both stay consistent with each other and with how a hand-written
    task file actually looks.
    """
    return "acceptance_criteria:\n" + "\n".join(f"  - {json.dumps(c)}" for c in criteria) + "\n"


_CRITERIA_CATEGORIES = {
    "insufficient_strictness", "parsing_looseness", "rounding_precision",
    "silent_failure", "internal_consistency", "domain_normalization",
    "intent_mismatch", "schema_structural", "other",
}


def agent_generate_acceptance_criteria_review(task_id, current_criteria, implementation_code, seed=None):
    """
    Adversarial follow-up to agent_generate_acceptance_criteria: given the
    criteria proposed so far and a real, converged implementation that
    already satisfies them, asks the model to find what a plausible
    implementation could still get away with (see
    agent_defs/acceptance_criteria_review_prompt.md). This is where
    the loop gets the signal one-shot generation structurally can't have --
    an actual implementation choice to react to, not just the spec text.
    Returns a list[(category, criterion_text)] of NEW findings only,
    possibly empty (an empty list is the loop's stopping signal, not a
    failure). category is one of _CRITERIA_CATEGORIES, grounded in the
    recurring bug shapes actually observed across real runs (see
    acceptance_criteria_review_prompt.md) -- not the same list[str] shape
    agent_generate_acceptance_criteria returns, since a category label is
    round-reporting metadata, not part of the criterion text itself (the
    plain text is what gets fed back into the next round and written into
    a task file, never the tag).
    """
    task = _task_without_acceptance_criteria(task_id)
    prompt = build_acceptance_criteria_review_prompt(task, current_criteria, implementation_code)
    # Its own mode, not "acceptance_criteria": the reviewer is a separate agent
    # with a separate prompt, and it has to be addressable separately to be
    # runnable on a different model from the one that drafted the criteria.
    raw = call_llm("acceptance_criteria_review", prompt, seed=seed)
    return _extract_tagged_criteria_list(raw)


def agent_propose_fixture_rows(task_id, criteria, seed=None):
    """
    Which criteria no existing fixture row can trigger, and what row would fix
    each one. Returns a list of dicts, possibly empty.

    A criterion nothing can exercise produces a test that passes whatever the
    code does. Roughly two thirds of the faults planted in this project's own
    measurements were caught by nobody for that reason, so the bar was partly
    unmeasurable rather than partly wrong.

    This NEVER writes to a fixture file. It returns proposals, and the caller
    writes them somewhere a person reads. Two reasons. A row is harder to judge
    than a criterion, because its correctness is relative to the criterion it
    was proposed for rather than visible on its face. And a fixture set that
    grows in whatever direction a model finds interesting stops resembling the
    data you actually process, at which point every rate measured on it
    describes a world that does not exist.
    """
    import yaml

    with open(task_config_path(task_id), encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    paths = [p for p in (config.get("inputs") or [])]
    task = _task_without_acceptance_criteria(task_id)
    prompt = build_fixture_proposal_prompt(task, criteria, read_fixtures(paths))
    return _extract_fixture_proposals(call_llm("fixture_proposal", prompt, seed=seed),
                                      len(criteria))


def _extract_fixture_proposals(text, criteria_count):
    """
    Parse `- [criterion N] [file] row | outcome` lines, and `covered`.

    Anything that does not match the documented shape is dropped rather than
    guessed at: a malformed row would be written into a proposal file that a
    person is meant to be able to paste from, and half a row is worse than no
    row. A criterion number outside the list is dropped for the same reason,
    since it cannot be reviewed against anything.
    """
    import re

    out = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-").strip()
        head = re.match(r"\[criterion\s+(\d+)\]\s*(.*)", line, re.I)
        if not head:
            continue
        index = int(head.group(1))
        if not 1 <= index <= criteria_count:
            continue
        rest = head.group(2).strip()
        if rest.lower().startswith("covered"):
            out.append({"criterion": index, "covered": True})
            continue
        body = re.match(r"\[([^\]]+)\]\s*(.+?)\s*\|\s*(.+)$", rest)
        if not body:
            continue
        row = body.group(2).strip()
        # A description of a row is not a row. One reply proposed the literal
        # text "(empty file)" to mean "a log with no events", and it was
        # pasted into a .jsonl as a line, breaking the fixture. A proposal has
        # to be the data itself, because the whole point is that it can be
        # appended without further interpretation.
        if row.startswith("(") and row.endswith(")"):
            continue
        out.append({"criterion": index, "covered": False,
                    "file": body.group(1).strip(),
                    "row": row,
                    "outcome": body.group(3).strip()})
    return out


def _extract_tagged_criteria_list(text):
    """
    Parses a `- [category] "..."` list (see
    acceptance_criteria_review_prompt.md's required output format) into a
    list of (category, criterion_text) tuples. Falls back to category
    "other" for a missing or unrecognized tag rather than dropping the
    finding -- a mis-tagged real finding is still a real finding, and a
    parsing quirk here shouldn't silently lose it.
    """
    match = re.search(r"```(?:yaml)?\s*\n(.*?)(?:```|\Z)", text, re.DOTALL)
    body = match.group(1) if match else text
    tag_re = re.compile(r'^-\s*\[(\w+)\]\s*(.*)$')
    results = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        m = tag_re.match(line)
        if m:
            category, item = m.group(1).strip().lower(), m.group(2).strip()
        else:
            category, item = "other", line[1:].strip()
        if category not in _CRITERIA_CATEGORIES:
            category = "other"
        if len(item) >= 2 and item.startswith('"') and item.endswith('"'):
            item = item[1:-1]
        if item:
            results.append((category, item))
    return results


def agent_generate_fix(task_id, failure_info, seed=None, previous_ineffective_patch=None):
    """
    Build FIX prompt and call the LLM to generate a FIX object.
    """

    path = agent_md_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"code_agent.md not found at: {path}")

    agent_md = open(path, encoding="utf-8").read()
    task = _task_without_acceptance_criteria(task_id)

    prompt = build_fix_prompt(
        agent_md, task, failure_info, previous_ineffective_patch=previous_ineffective_patch
    )
    return call_llm("fix", prompt, seed=seed)


def agent_generate_patch(task_id, fix, seed=None, previous_patch=None, previous_patch_error=None,
                          previous_patch_too_large=False):
    """
    Build PATCH prompt and call the LLM to generate a PATCH object. Only
    loads the files the FIX named in its target_files: list, not the whole
    task codebase -- keeps the prompt (and the model's ability to introduce
    an unrelated change) scoped to what the FIX actually said it would
    touch. Falls back to the whole task codebase if target_files couldn't be
    parsed out of the FIX text, rather than giving the model no code at all.
    """
    path = agent_md_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"code_agent.md not found at: {path}")

    agent_md = open(path, encoding="utf-8").read()
    task = _task_without_acceptance_criteria(task_id)
    code_dir = agent_src_code_path(task_id)
    target_files = _extract_target_files(fix)
    # The FIX names the files and, in prose, the functions it means to
    # change, so it is also the retrieval query for anything too large to
    # load whole.
    codebase_text = (load_target_files(code_dir, target_files, context=fix)
                     if target_files else load_codebase(code_dir))

    prompt = build_patch_prompt(
        agent_md, task, fix, codebase_text,
        previous_patch=previous_patch, previous_patch_error=previous_patch_error,
        previous_patch_too_large=previous_patch_too_large
    )
    raw_patch = call_llm("patch", prompt, seed=seed)
    diff = _extract_diff(raw_patch)
    return _recount_hunk_headers(diff)


def _load_test_agent_md():
    path = test_agent_md_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"test_agent.md not found at: {path}")
    return open(path, encoding="utf-8").read()


def read_acceptance_criteria(task_id):
    """This task's acceptance_criteria as a list, or [] if it has none."""
    import yaml

    data = yaml.safe_load(_read_task(task_id)) or {}
    return list(data.get("acceptance_criteria") or [])


def _task_with_criteria(task_id, criteria):
    """
    The task config text with its acceptance_criteria replaced by `criteria`.

    Used to generate tests against one batch of the bar at a time. Passing
    None returns the config untouched, which is the single-call behaviour.
    """
    text = _read_task(task_id)
    if criteria is None:
        return text
    block = ("acceptance_criteria:\n"
             + "".join(f"  - {json.dumps(c)}\n" for c in criteria))
    # Replace through a callable. re.sub treats a string replacement as a
    # template, so the backslash escapes json.dumps emits get reinterpreted
    # and the result is either a re.error or a tab injected into the YAML.
    return _ACCEPTANCE_CRITERIA_RE.sub(lambda _m: block, text)


def criteria_batches(task_id, per_batch):
    """
    Split this task's criteria into batches of `per_batch`, or [None] when
    batching is off, which means one call carrying the whole bar.

    Batching exists because the suite was measured not to grow with the bar:
    across 67 archived suites, refinement raised the criteria count 54% and
    the generated suite got 6% smaller, so tests per criterion fell from 2.21
    to 1.32. One call for the whole set appears to produce a roughly fixed
    amount of test code however much it is asked to cover, which dilutes
    coverage rather than adding it.
    """
    if not per_batch or per_batch < 1:
        return [None]
    criteria = read_acceptance_criteria(task_id)
    if len(criteria) <= per_batch:
        return [None]
    return [criteria[i:i + per_batch] for i in range(0, len(criteria), per_batch)]


def agent_generate_integration_tests(task_id, seed=None, criteria=None):
    """
    Build the INTEGRATION test prompt (spec only, no implementation access)
    and call the LLM to generate that test file's source.

    `criteria` restricts the bar shown to this call. None means the whole set.
    """
    test_agent_md = _load_test_agent_md()
    task = _task_with_criteria(task_id, criteria)

    prompt = build_integration_test_prompt(test_agent_md, task)
    raw = call_llm("test_integration", prompt, seed=seed)
    return _extract_python(raw)


def agent_generate_system_tests(task_id, seed=None, criteria=None):
    """
    Build the SYSTEM test prompt (spec only, no implementation access) and
    call the LLM to generate that test file's source.
    """
    test_agent_md = _load_test_agent_md()
    task = _task_with_criteria(task_id, criteria)

    prompt = build_system_test_prompt(test_agent_md, task)
    raw = call_llm("test_system", prompt, seed=seed)
    return _extract_python(raw)


def agent_generate_unit_tests(task_id, seed=None, criteria=None):
    """
    Build the UNIT test prompt and call the LLM to generate that test file's
    source. Unlike the integration/system prompts, this one includes the
    current outputs/agent_src/code/<task_id>/ implementation -- the one
    deliberate exception to keeping test generation blind to the code under
    test, since unit tests need to target the implementation's actual
    functions by name.
    """
    test_agent_md = _load_test_agent_md()
    task = _task_with_criteria(task_id, criteria)
    codebase_text = load_codebase(agent_src_code_path(task_id))

    prompt = build_unit_test_prompt(test_agent_md, task, codebase_text)
    raw = call_llm("test_unit", prompt, seed=seed)
    return _extract_python(raw)


def _extract_python(text):
    """
    test_agent.md instructs the model to output raw Python source with no
    wrapping. Some models add a ```python fenced block anyway -- strip that
    wrapping the same way _extract_diff() does for PATCH output.
    """
    match = re.search(r"```(?:python)?\s*\n(.*?)(?:```|\Z)", text, re.DOTALL)
    body = match.group(1) if match else text
    return body.strip("\n") + "\n"


def _extract_diff(text):
    """
    code_agent.md instructs the model to wrap the PATCH in a `PATCH:` label and a
    ```diff fenced block. Strip that wrapping so callers get a plain unified diff.
    """
    match = re.search(r"```diff\s*\n(.*?)(?:```|\Z)", text, re.DOTALL)
    body = match.group(1) if match else text
    return body.strip("\n") + "\n"


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


def _recount_hunk_headers(diff_text):
    """
    LLM-generated diffs frequently have wrong hunk header line counts
    (@@ -old_start,old_count +new_start,new_count @@) even when the hunk
    body itself is correct, which makes `patch`/`git apply` reject an
    otherwise-valid diff. Counting context/added/removed lines is a purely
    mechanical operation, so recompute the counts ourselves rather than
    relying on the model to get the arithmetic right.
    """
    lines = diff_text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        match = _HUNK_HEADER_RE.match(lines[i])
        if not match:
            out.append(lines[i])
            i += 1
            continue

        old_start, new_start, trailer = match.groups()
        body = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith(("@@ ", "--- ", "+++ ", "diff ")):
            body.append(lines[j])
            j += 1

        old_count = sum(1 for l in body if l.startswith((" ", "-")))
        new_count = sum(1 for l in body if l.startswith((" ", "+")))

        out.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{trailer}")
        out.extend(body)
        i = j

    return "\n".join(out) + "\n"
