"""
Ask, before spending a stage's budget, whether the bar can be met at all.

Stall cause one in the write-up is a criterion that contradicts the
requirements: the test asks for behaviour no implementation could have while
still satisfying the spec, so the agent produces changes that fix the test and
break the spec, or the reverse, forever. The remedy was named there and never
built. This is it.

The check is one model call against the whole task, not one per criterion,
because a contradiction is a relationship between statements and looking at
them one at a time cannot see it. Against a stage budget of ten attempts, each
carrying a FIX and a PATCH, one call to find out the loop is unwinnable is
cheap at any plausible hit rate.

**Why it has to sit here, before the run.** Everything inside the loop is
bound by the rule the whole tool exists for: the coding agent never sees the
acceptance criteria. So the one agent positioned to notice that the spec
disagrees with itself is the one forbidden from seeing half the evidence, and
no amount of iterating can recover it. A specification fault is not a bug the
loop can find. It is only findable before the loop starts.

**Three things it looks for, and the third was added last.** A criterion
against the requirements, a criterion against the description, and a criterion
against another criterion. The last one needs saying explicitly or it is
missed: two criteria that disagree make the suite unsatisfiable by themselves,
with no requirement involved anywhere. The prompt also carves out numeric
thresholds from the "merely stricter" exemption, because "fails below 2 m" and
"fails below 2.5 m" read as one rule and a tighter version of it while
actually disagreeing about every value in between, and that is a typo, not a
design.

It is advisory. It prints and returns findings; it never edits a task and
never blocks a run. A checker that refused to run on a false positive would be
worse than the stalls it prevents, and a model judging whether two English
sentences can both hold is not reliable enough to be given that power.
"""
import json
import re

PROMPT = """You are checking one specification for internal contradictions before
any code is written for it.

Below are a task's DESCRIPTION, its REQUIREMENTS and its ACCEPTANCE_CRITERIA.
The description says what the task is for. Requirements describe what the
software must do. Acceptance criteria are the checkable edge cases it will be
tested against.

Report only cases where NO possible implementation could satisfy both
statements at once, or where one demands something another explicitly forbids.

Check BOTH directions of conflict:
- a criterion against a requirement or against the description
- a criterion against ANOTHER CRITERION

The second is easy to miss and costs the same. Two criteria that disagree with
each other make the suite unsatisfiable on their own, whatever the
requirements say, so the run cannot converge no matter what the agent writes.

NUMERIC THRESHOLDS ARE A SPECIAL CASE AND YOU MUST REPORT THEM.
When two statements set DIFFERENT numeric thresholds on the SAME quantity,
report it, even though one looks merely stricter than the other. "Fails below
2 m" and "fails below 2.5 m" are not one rule and a tighter version of it:
they disagree about every value between 2 and 2.5, and one of the two numbers
is a typo or a misreading. Naming the disputed range is the whole finding.

Do NOT report:
- a criterion that merely adds detail the others leave open
- a criterion that is qualitatively stricter, unless the others positively
  require the looser behaviour, or unless it is a numeric threshold on a
  quantity another statement also bounds, which is always reportable
- vagueness, style, duplication, or anything you would call an improvement

A criterion being more specific than a requirement is the normal and intended
relationship between the two. Apart from the numeric case above, only genuine
impossibility counts.

DESCRIPTION:
{description}

REQUIREMENTS:
{requirements}

ACCEPTANCE_CRITERIA:
{criteria}

Return a JSON array. Each element:
  {{"criterion": "<the criterion, quoted>",
    "conflicts_with": "<the requirement, description sentence or OTHER
                       CRITERION it cannot coexist with, quoted>",
    "why": "<one sentence on why no implementation satisfies both>"}}

Return [] if there are none. Return only the JSON array.
"""


def _as_lines(items):
    return "\n".join(f"- {x}" for x in (items or [])) or "(none)"


def _unbulleted(value):
    """
    Strip the list marker the prompt used, which models quote back verbatim.

    The statements reach the model as "- <statement>", so a reply quoting one
    faithfully carries the bullet into the report, where it reads as part of
    the requirement rather than as formatting we added.
    """
    return re.sub(r"^\s*[-*•]\s+", "", str(value or "")).strip()


def parse_findings(raw):
    """
    Pull the JSON array out of a model reply, tolerating fences and prose.

    Returns [] on anything unparseable. A checker that raised on a malformed
    reply would turn an advisory feature into a new way for runs to die.
    """
    if not raw:
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("criterion"):
            out.append({
                "criterion": _unbulleted(item.get("criterion", "")),
                "conflicts_with": _unbulleted(item.get("conflicts_with", "")),
                "why": str(item.get("why", "")),
            })
    return out


def build_prompt(requirements, criteria, description=None):
    """
    The whole specification, in the order a person would read it.

    `description` is included because a fault can sit between the prose and
    the criteria without either contradicting a requirement: the description
    is where the task says what it is for, and a criterion measuring something
    else is wrong in a way the requirements alone cannot show.
    """
    return PROMPT.format(description=(description or "(none)"),
                         requirements=_as_lines(requirements),
                         criteria=_as_lines(criteria))


def check(task_id, seed=None):
    """
    One call. Returns a list of findings, empty when the spec is consistent.

    Never raises: a provider failure here must not stop a run that would
    otherwise have gone ahead, because this check is advice and the run is the
    work.
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
    requirements = cfg.get("requirements") or []
    if not criteria or not requirements:
        return []

    try:
        raw = call_llm("acceptance_criteria_review",
                       build_prompt(requirements, criteria,
                                    cfg.get("description")), seed=seed)
    except Exception:
        return []
    return parse_findings(raw)


def report(task_id, findings, printer=print):
    """Print findings in the form a person can act on, or say nothing found."""
    if not findings:
        printer(f"[{task_id}] no contradictions found within the specification.")
        return 0
    printer(f"[{task_id}] {len(findings)} possible contradiction(s). "
            f"Each one is a stage that will burn its whole budget without converging:")
    for f in findings:
        printer(f"  criterion : {f['criterion']}")
        printer(f"  conflicts : {f['conflicts_with']}")
        printer(f"  why       : {f['why']}")
        printer("")
    printer("  This is advisory and nothing has been changed. Fix the specification,")
    printer("  or ignore it if you disagree: a model judging whether two English")
    printer("  sentences can both hold is not reliable enough to be obeyed.")
    return len(findings)
