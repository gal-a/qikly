"""
Ask, before any code is written, whether the generated suites can be passed at all.

`--check-criteria` asks that question of the specification. This asks it of the
tests written from it, because the test-writing agent can misread a criterion
that is perfectly clear, and the loop has no way to notice.

Found on a real task, 2026-09-15: a following-distance check whose criterion
said "a time headway of exactly 2.00 seconds gives warning false". Ten runs,
ten seeds. In seven of them a generated test warned at exactly 2.00 seconds
anyway, and all seven failed; the three whose tests read the boundary correctly
all converged. Where the integration suite got it wrong and the system suite got
it right, the coding agent flipped `<` and `<=` until the stall detector stopped
the run: each patch made one test pass and the other fail, and no code could
ever pass both. The whole budget went on a fault that was in the tests.

**Why it has to sit here, between test generation and the first line of code.**
The coding agent never sees the criteria or the test source, only failure
output, so it cannot tell a wrong test from a right one. Test generation cannot
check itself either: the same reading that produced the wrong test would approve
it. A separate look at the suites next to the criteria is the only point where
the error is visible and nothing has been spent on it yet.

**Two things it looks for.** A test that asserts something an acceptance
criterion or requirement rules out, and two tests that expect different results
for the same input. Boundaries get their own instruction, because that is where
the measured failures were: `<` against `<=` at a stated limit reads as a detail
and decides the whole run.

It is advisory, like `check_criteria`. The orchestrator rewrites a suite once
when the check reports a finding, and carries on either way: a model judging
whether two tests can both pass is not reliable enough to be given the power to
stop a run. It never raises, for the same reason.

    python -m qikly.orchestrator.tuning.check_suites --tasks ADAS_HEADWAY

checks suites already on disk, one model call per task.
"""
import json
import os
import re
import sys

PRE_IMPLEMENTATION_STAGES = ("integration", "system")

PROMPT = """You are checking generated test suites before any implementation exists.

Below are a task's DESCRIPTION, REQUIREMENTS and ACCEPTANCE_CRITERIA, followed by
the test SUITES written from them. Every test is meant to agree with the
acceptance criteria and with every other test.

Report only tests that NO correct implementation could pass:
- a test that asserts behaviour an acceptance criterion or requirement explicitly
  rules out
- two tests that expect DIFFERENT RESULTS FOR THE SAME INPUT

BOUNDARIES ARE THE COMMON CASE AND YOU MUST CHECK EVERY ONE, IN TWO STEPS.

STEP 1, THE LIMITS. List every numeric limit or threshold the acceptance
criteria state, and for each one what the criteria say happens to a value
exactly at that limit, such as "exactly 250 is accepted" or "exactly 2.00 gives
warning false".

STEP 2, THE TESTS. For every test that checks one of those limits, quote the
comparison it uses (`<` against `<=`, `>` against `>=`) and work out what that
test expects for a value exactly at the limit. If it expects the opposite of
STEP 1, the test is a finding. This is the most common fault. It is a finding
even when the test agrees about every other value, and even when every suite
makes the same mistake, so agreement between suites proves nothing.

Do NOT report:
- missing tests, weak tests, or behaviour the criteria leave open
- style, naming, structure, duplication, or anything you would call an improvement
- a test stricter than the criteria only where the criteria say nothing

DESCRIPTION:
<<DESCRIPTION>>

REQUIREMENTS:
<<REQUIREMENTS>>

ACCEPTANCE_CRITERIA:
<<CRITERIA>>

SUITES:
<<SUITES>>

Return a JSON object:
  {"limits": [{"limit": "<a limit from STEP 1>",
               "at_the_limit": "<what the criteria say happens exactly at it>"}],
   "findings": [{"suite": "<the suite the test is in, such as integration or system>",
                 "test": "<the test function name>",
                 "conflicts_with": "<the acceptance criterion it contradicts, quoted, or the other test as suite::name>",
                 "why": "<one sentence naming the input and the two results that cannot both hold>"}]}

"findings" is [] if every test agrees. Return only the JSON object.
"""


def _as_lines(items):
    return "\n".join(f"- {x}" for x in (items or [])) or "(none)"


def suite_sources(tests_dir, stages):
    """Every generated test file for these stages, as (stage, filename, source)."""
    found = []
    for stage in stages:
        stage_dir = os.path.join(tests_dir, stage)
        if not os.path.isdir(stage_dir):
            continue
        for name in sorted(os.listdir(stage_dir)):
            if not name.endswith(".py"):
                continue
            try:
                with open(os.path.join(stage_dir, name), encoding="utf-8") as handle:
                    found.append((stage, name, handle.read()))
            except OSError:
                continue
    return found


def build_prompt(requirements, criteria, suites, description=None):
    """
    The specification, then every suite in full.

    Filled by replacement rather than str.format: the suites are Python source,
    and every dict literal and f-string in them is a brace that format() would
    try to interpret.
    """
    blocks = "\n\n".join(f"=== {stage}: {name} ===\n{source}" for stage, name, source in suites)
    return (PROMPT
            .replace("<<DESCRIPTION>>", description or "(none)")
            .replace("<<REQUIREMENTS>>", _as_lines(requirements))
            .replace("<<CRITERIA>>", _as_lines(criteria))
            .replace("<<SUITES>>", blocks or "(none)"))


def _unbulleted(value):
    """Strip a list marker the prompt added and a model quoted back."""
    return re.sub(r"^\s*[-*•]\s+", "", str(value or "")).strip()


def parse_findings(raw):
    """
    Pull the JSON array out of a model reply, tolerating fences and prose.

    The prompt asks for an object whose "findings" holds the list, so the model
    writes its reading of every limit down before judging the tests; a bare
    list is accepted too. Which shape it is follows from whichever bracket
    comes first, since an object's own "limits" list would otherwise be
    mistaken for the findings.

    Returns [] on anything unparseable. A checker that raised on a malformed
    reply would turn advice into a new way for runs to die.
    """
    if not raw or not isinstance(raw, str):
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    first_array, first_object = text.find("["), text.find("{")
    if first_object != -1 and (first_array == -1 or first_object < first_array):
        end = text.rfind("}")
        try:
            data = json.loads(text[first_object:end + 1])
        except json.JSONDecodeError:
            return []
        data = data.get("findings") if isinstance(data, dict) else None
    elif first_array != -1:
        end = text.rfind("]")
        if end < first_array:
            return []
        try:
            data = json.loads(text[first_array:end + 1])
        except json.JSONDecodeError:
            return []
    else:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("test"):
            continue
        suite = str(item.get("suite") or "").strip().lower()
        test = str(item.get("test")).strip()
        if "::" in test:
            # A model naming the test as suite::name, the form the prompt uses
            # for the other side of a conflict.
            prefix, _, test = test.rpartition("::")
            suite = suite or prefix.strip().lower()
        out.append({
            "suite": suite,
            "test": test,
            "conflicts_with": _unbulleted(item.get("conflicts_with")),
            "why": str(item.get("why") or ""),
        })
    return out


def check(task_id, tests_dir, stages=PRE_IMPLEMENTATION_STAGES, seed=None):
    """
    One call. Returns a list of findings, empty when the suites agree.

    Never raises: a provider failure here must not stop a run, because this
    is advice and the run is the work.
    """
    import yaml

    from qikly.agent_api.agent_interface import task_config_path
    from qikly.agent_api.call_llm import call_llm

    try:
        with open(task_config_path(task_id), encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
    except Exception:
        return []

    criteria = cfg.get("acceptance_criteria") or []
    if not criteria:
        return []
    suites = suite_sources(tests_dir, stages)
    if not suites:
        return []

    try:
        raw = call_llm("suite_consistency",
                       build_prompt(cfg.get("requirements"), criteria, suites,
                                    cfg.get("description")), seed=seed)
    except Exception:
        return []
    return parse_findings(raw)


def _label(finding):
    return f"{finding['suite']}::{finding['test']}" if finding.get("suite") else finding["test"]


def report_lines(findings):
    """The findings as lines a person can act on, without a task prefix."""
    if not findings:
        return ["the generated suites agree with the criteria and with each other"]
    lines = [f"{len(findings)} generated test(s) that no correct implementation could pass:"]
    for f in findings:
        lines.append(f"  test      : {_label(f)}")
        lines.append(f"  conflicts : {f['conflicts_with']}")
        lines.append(f"  why       : {f['why']}")
    return lines


def report(task_id, findings, printer=print):
    """Print findings for one task, or say the suites agree. Returns the count."""
    for line in report_lines(findings):
        printer(f"[{task_id}] {line}")
    if findings:
        printer(f"[{task_id}] This is advisory and nothing has been changed. Compare each test")
        printer(f"[{task_id}] with its criterion: a model judging whether two tests can both")
        printer(f"[{task_id}] pass is not reliable enough to be obeyed.")
    return len(findings)


def guidance_for(stage, findings):
    """
    What a rewrite of one suite is told about the draft it replaces.

    Only ever sent to test generation, which reads the criteria anyway. The
    coding agent never receives it: that would hand it the quoted criteria.
    """
    relevant = [f for f in findings if f.get("suite") in ("", stage)] or findings
    lines = [
        "A previous draft of this suite was checked against the acceptance criteria "
        "before any code existed. These tests could not be passed by any correct "
        "implementation:",
    ]
    for f in relevant:
        lines.append(f"- {_label(f)}: {f['why']} (conflicts with: {f['conflicts_with']})")
    lines.append(
        "Write the suite again. Keep every test consistent with the acceptance criteria "
        "and with the other tests, especially at each boundary value: whether the value "
        "exactly at a stated limit passes or fails must match the criterion word for word.")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Check generated suites already on disk against the acceptance "
                    "criteria and each other. One model call per task.")
    parser.add_argument("--tasks", help="comma-separated task ids; all tasks with suites if omitted")
    args = parser.parse_args(argv)

    from qikly.orchestrator.orchestrator import GENERATED_TESTS_ROOT, discover_task_ids
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    seed_env = os.environ.get("AGENT_SEED")
    seed = int(seed_env) if seed_env else None
    task_ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else discover_task_ids()

    total = 0
    for task_id in [t for t in task_ids if t]:
        tests_dir = os.path.join(GENERATED_TESTS_ROOT, task_id)
        if not suite_sources(tests_dir, PRE_IMPLEMENTATION_STAGES):
            print(f"[{task_id}] no generated integration or system suites on disk; run the task first")
            continue
        total += report(task_id, check(task_id, tests_dir, seed=seed))

    try:
        from qikly.agent_api.usage import USAGE
        print()
        print(USAGE.summary())
    except Exception:
        pass
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
