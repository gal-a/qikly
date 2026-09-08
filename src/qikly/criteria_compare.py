"""
How much of your bar would qikly have written for you?

You already have acceptance criteria. Before trusting `--generate-criteria` on
a task where you have not, the useful question is what it would have produced
on one where you have, and what it would have missed.

So this drafts criteria from your `requirements` alone, exactly as
`--generate-criteria` would, and reports them against the ones you wrote,
which are treated here as the ground truth. Yours are never modified and never
shown to the drafting agent.

## Why the score is a judgement and says so

Two criteria can say the same thing in different words, so deciding whether a
draft covers "amount must be a positive number" needs reading, not string
matching. That reading is done by a model, in one extra call, and the result is
labelled as an opinion rather than a measurement everywhere it appears.

An earlier version of this comparison printed the two lists and stopped, on the
grounds that scoring needs a human. That was right about the difficulty and
wrong about the consequence: a reader given twenty criteria in two columns does
the matching in their head, badly, and remembers an impression. A stated
judgement they can disagree with is more useful than an unstated one they have
to form.

## What this is not

It is not evidence that a covered criterion produces an equally good test. Two
bars can describe the same rule and generate suites that catch different
things, which is why this project measures refinement by fault detection rather
than by criteria text. Read this as "would I have lost a rule", not as "is the
generated bar as good".
"""
import re

COVERAGE_PROMPT = """You are comparing two lists of acceptance criteria for the same specification.

REFERENCE criteria, written by a person. These are the ground truth:
{reference}

DRAFT criteria, generated from the requirements alone:
{draft}

For each REFERENCE criterion, decide whether any DRAFT criterion expresses the
same rule. Wording will differ; judge the rule, not the phrasing. A draft that
covers part of a reference criterion but omits its boundary value is PARTIAL.

Output one line per reference criterion, nothing else, in this exact form:

[1] COVERED by draft 3
[2] PARTIAL by draft 5 | the draft omits the boundary value
[3] MISSED

Then, on its own final line, list any draft criteria that match no reference
criterion at all:

EXTRA: 2, 7
"""

_LINE = re.compile(r"^\[(\d+)\]\s*(COVERED|PARTIAL|MISSED)\b(?:\s*by draft\s*(\d+))?"
                   r"(?:\s*\|\s*(.*))?", re.IGNORECASE)
_EXTRA = re.compile(r"^EXTRA:\s*(.*)$", re.IGNORECASE)


def parse_coverage(text, reference_count):
    """
    The model's verdicts, as data. Pure: no network.

    A verdict for a criterion that does not exist is dropped, and a criterion
    with no verdict counts as unjudged rather than as covered. Silence must
    never read as success here: the whole point is to find what was missed.
    """
    verdicts, extra = {}, []
    for line in (text or "").split("\n"):
        line = line.strip()
        found = _LINE.match(line)
        if found:
            index = int(found.group(1))
            if 1 <= index <= reference_count:
                verdicts[index] = {
                    "status": found.group(2).upper(),
                    "draft": int(found.group(3)) if found.group(3) else None,
                    "note": (found.group(4) or "").strip() or None,
                }
            continue
        more = _EXTRA.match(line)
        if more:
            extra = [int(n) for n in re.findall(r"\d+", more.group(1))]
    return verdicts, extra


def summarise(reference, draft, verdicts, extra):
    counts = {"COVERED": 0, "PARTIAL": 0, "MISSED": 0, "UNJUDGED": 0}
    for i in range(1, len(reference) + 1):
        counts[verdicts.get(i, {}).get("status", "UNJUDGED")] += 1
    return {
        "reference_count": len(reference),
        "draft_count": len(draft),
        "covered": counts["COVERED"],
        "partial": counts["PARTIAL"],
        "missed": counts["MISSED"],
        "unjudged": counts["UNJUDGED"],
        "extra": extra,
    }


def render(task_id, reference, draft, verdicts, extra, summary):
    out = ["=" * 72,
           f"  {task_id}: what --generate-criteria would have written",
           "=" * 72, ""]
    out.append(f"  You wrote {summary['reference_count']} criteria. Drafting from "
               f"your requirements alone produced {summary['draft_count']}.")
    out.append("")
    out.append(f"  Covered {summary['covered']}   partial {summary['partial']}   "
               f"missed {summary['missed']}"
               + (f"   unjudged {summary['unjudged']}" if summary["unjudged"] else ""))
    out.append("")

    gaps = [(i, v) for i, v in sorted(verdicts.items())
            if v["status"] in ("MISSED", "PARTIAL")]
    if gaps:
        out.append("  WHAT THE DRAFT WOULD HAVE COST YOU")
        for i, v in gaps:
            out.append(f"    [{v['status']}] {reference[i - 1]}")
            if v["note"]:
                out.append(f"        {v['note']}")
        out.append("")
    else:
        out.append("  Nothing of yours was missed, on this model's reading.")
        out.append("")

    if extra:
        out.append("  DRAFT CRITERIA WITH NO COUNTERPART IN YOURS")
        out.append("  Worth reading: these are either noise, or a rule you have not")
        out.append("  written down yet.")
        for n in extra:
            if 1 <= n <= len(draft):
                out.append(f"    {draft[n - 1]}")
        out.append("")

    out.append("  The matching above is a model's judgement, not a measurement.")
    out.append("  Wording differs between two criteria that mean the same thing, so")
    out.append("  deciding coverage needs reading; disagree with any line of it.")
    out.append("")
    out.append("  It also says nothing about test quality. Two bars can describe the")
    out.append("  same rule and produce suites that catch different faults, which is")
    out.append("  why this project measures a bar by what its tests detect rather")
    out.append("  than by its text.")
    out.append("=" * 72)
    return "\n".join(out)


def compare(task_id, seed=None):
    """Draft criteria, judge them against yours, and return the whole result."""
    import yaml

    from qikly.agent_api.agent_interface import (_read_task,
                                                 agent_generate_acceptance_criteria)
    from qikly.agent_api.call_llm import call_llm

    reference = (yaml.safe_load(_read_task(task_id)) or {}).get("acceptance_criteria") or []
    if not reference:
        raise ValueError(
            f"{task_id} has no acceptance_criteria, so there is nothing to compare "
            f"a draft against. This command answers 'what would qikly have written "
            f"instead of what I wrote', which needs what you wrote.")

    draft = agent_generate_acceptance_criteria(task_id, seed=seed)

    prompt = COVERAGE_PROMPT.format(
        reference="\n".join(f"[{i}] {c}" for i, c in enumerate(reference, 1)),
        draft="\n".join(f"[{i}] {c}" for i, c in enumerate(draft, 1)))
    # The same agent role that drafts criteria also judges the match,
    # so both halves of this command follow one settings key.
    raw = call_llm("acceptance_criteria", prompt, seed=seed)

    verdicts, extra = parse_coverage(raw, len(reference))
    summary = summarise(reference, draft, verdicts, extra)
    return {"task_id": task_id, "reference": reference, "draft": draft,
            "verdicts": {str(k): v for k, v in verdicts.items()},
            "extra": extra, "summary": summary}
