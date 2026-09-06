"""
Showing the withholding instead of asserting it.

The central claim of this project is that the agent writing the code never
receives the acceptance criteria. There has always been a way to check it:
`pytest tests/test_withholding.py`, which passes in seconds and needs no API
key. That persuades engineers, and it persuades nobody else, because it asks
the reader to trust a test they have not read about a mechanism they cannot
see.

This prints the mechanism. For a real task, side by side: what test generation
receives, what the coding agent receives, and the diff between them. The
criteria are visibly present in one column and visibly absent from the other,
in the actual prompt text the actual run would send.

No model is called. Nothing is generated. This builds the same prompts the
orchestrator builds and shows them, so it costs nothing and works offline.

## Why it reads the real builders

It would be much easier to write a demonstration that constructs two strings
and highlights the difference. That demonstration would prove nothing: it would
show what this file believes, not what the run does, and it would keep passing
after someone changed the prompt builder underneath it.

So every string here comes from the same functions `agent_interface` calls. If
the withholding ever broke, this would show it broken.
"""
import difflib


def build(task_id):
    """
    What each side sees, from the real prompt builders.

    Both are the task file as *text*, which is what the prompts actually carry,
    so the difference between them is a plain diff rather than a comparison of
    two parsed structures that might each be right while the text is wrong.

    Returns a dict so the same facts can be rendered as prose or as JSON
    without one being re-parsed out of the other.
    """
    import yaml

    from qikly.agent_api.agent_interface import (_read_task, task_config_path,
                                                 _task_without_acceptance_criteria)

    full = _read_task(task_id)
    withheld = _task_without_acceptance_criteria(task_id)
    criteria = (yaml.safe_load(full) or {}).get("acceptance_criteria") or []

    # The check that matters, done on the text the agent is actually handed
    # rather than on the structure someone believes it to be.
    leaked = [c for c in criteria if isinstance(c, str) and c.strip() and c in withheld]

    # The path as a reader would name it, trimmed to the part that says which
    # tree it came from: a bundled example or one of their own.
    path = task_config_path(task_id).replace("\\", "/")
    for marker in ("inputs_public/", "inputs_private/"):
        if marker in path:
            path = path[path.index(marker):]
            break

    return {
        "task_id": task_id,
        "task_path": path,
        "criteria_count": len(criteria),
        "criteria": criteria,
        "test_generation_chars": len(full),
        "coding_agent_chars": len(withheld),
        "test_generation_sees": full,
        "coding_agent_sees": withheld,
        "leaked": leaked,
        "withheld_ok": not leaked and bool(criteria),
    }


def render(facts):
    lines = []
    task_id = facts["task_id"]
    count = facts["criteria_count"]

    lines.append("=" * 72)
    lines.append(f"  {facts.get('task_path', task_id)}")
    lines.append("  what each agent sees")
    lines.append("=" * 72)
    lines.append("")

    if not count:
        lines.append(f"  {task_id} declares no acceptance_criteria, so there is")
        lines.append("  nothing to withhold and nothing to show. Pick a task that")
        lines.append("  has some, or write them first.")
        return "\n".join(lines)

    lines.append(f"  This task declares {count} acceptance criteria.")
    lines.append("")
    lines.append("  THE TEST GENERATION AGENT receives all of them. The first three:")
    lines.append("")
    for i, item in enumerate(facts["criteria"][:3], start=1):
        lines.append(f"    {i}. {item}")
    if count > 3:
        lines.append(f"    ... and {count - 3} more")
    lines.append("")

    lines.append("  THE CODING AGENT receives the same file with that section cut out.")
    lines.append("  What is removed before it is handed over:")
    lines.append("")

    before = facts["test_generation_sees"].splitlines()
    after = facts["coding_agent_sees"].splitlines()
    removed = [l[1:] for l in difflib.unified_diff(before, after, lineterm="", n=0)
               if l.startswith("-") and not l.startswith("---") and l[1:].strip()]
    for line in removed[:5]:
        lines.append(f"  REMOVED  {line.strip()[:104]}")
    if len(removed) > 5:
        lines.append(f"  ... and {len(removed) - 5} more removed line(s)")
    added = [l for l in difflib.unified_diff(before, after, lineterm="", n=0)
             if l.startswith("+") and not l.startswith("+++")]
    lines.append("")
    # Spelled out because the two numbers on this page do not obviously agree:
    # a reader counts 11 criteria and 12 removed lines and has to work out
    # where the extra one came from. It is the YAML key the list hangs off.
    entries = sum(1 for line in removed if line.strip().startswith("-"))
    other = len(removed) - entries
    if entries == count and other:
        lines.append(f"  {len(removed)} lines removed: the "
                     f"`acceptance_criteria:` key,")
        lines.append(f"  plus all {count} criteria under it.")
    elif entries:
        lines.append(f"  {len(removed)} lines removed, {entries} of them criteria.")
    else:
        lines.append(f"  {len(removed)} line(s) removed.")
    lines.append(f"  The file shrinks from {facts['test_generation_chars']:,} "
                 f"characters to {facts['coding_agent_chars']:,}.")
    lines.append("")

    if facts["withheld_ok"]:
        lines.append("  VERDICT: no criterion text reaches the coding agent, so when a "
                     "test fails it")
        lines.append("  sees the error and never the rule it broke.")
    else:
        lines.append("  VERDICT: FAILED. Criteria text is present in what the coding")
        lines.append("  agent receives, which breaks the property this whole tool rests")
        lines.append("  on. Leaked:")
        for item in facts["leaked"][:5]:
            lines.append(f"    {item[:100]}")

    lines.append("")
    lines.append("  Built by the same functions a real run uses, with no model call.")
    lines.append("=" * 72)
    return "\n".join(lines)
