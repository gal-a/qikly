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
    # The label has to agree with what is printed below it. It said "The first
    # three" unconditionally until 2026-09-07, and `qikly --init` writes a
    # starter task with exactly two criteria, so the very first --explain a new
    # user runs announced three and listed two. This is the command the README
    # calls the one worth running first, precisely because it makes the central
    # claim checkable rather than trusted, which makes it the worst place in
    # the tool to be caught miscounting.
    if count == 1:
        lines.append("  THE TEST GENERATION AGENT receives it:")
    elif count <= 3:
        lines.append("  THE TEST GENERATION AGENT receives all of them:")
    else:
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
    # Said as criteria first, because that is the unit the reader was just
    # given and the line count is not the same number: on 11 criteria the diff
    # removes 12 lines, and the extra one is the YAML key the list hangs off.
    # Leading with the line count makes a reader stop and reconcile the two.
    entries = sum(1 for line in removed if line.strip().startswith("-"))
    other = len(removed) - entries
    if entries == count and other:
        lines.append(f"  All {count} acceptance criteria are removed, with the")
        lines.append(f"  `acceptance_criteria:` key they hang off: "
                     f"{len(removed)} lines removed.")
    elif entries:
        lines.append(f"  {entries} acceptance criteria are removed, "
                     f"{len(removed)} lines in all.")
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


# One page with nothing external: no scripts, fonts, images or stylesheets, so
# it can be attached, hosted or screenshotted exactly as written.
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; background: #0b0f10; color: #e3eae8;
         font: 16px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif; }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 36px 24px 28px; }
  .brand { margin: 0 0 6px; font: 600 .75rem/1 ui-monospace, Consolas, monospace;
           letter-spacing: .14em; text-transform: uppercase; color: #57b8bd; }
  h1 { margin: 0 0 10px; font-size: 1.7rem; line-height: 1.2; }
  .lede { margin: 0 0 8px; color: #98a5a3; max-width: 72ch; }
  .verdict { margin: 14px 0 22px; padding: 10px 14px; border-radius: 8px; font-weight: 600; }
  .verdict.ok { background: #112f2e; color: #8fdcdc; border: 1px solid #2b8f95; }
  .verdict.bad { background: #3a1414; color: #fca5a5; border: 1px solid #b91c1c; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .col { min-width: 0; background: #141a1b; border: 1px solid #293334; border-radius: 10px;
         overflow: hidden; }
  .col h2 { margin: 0; padding: 12px 16px; font: 600 .78rem/1.2 ui-monospace, Consolas, monospace;
            letter-spacing: .12em; text-transform: uppercase; border-bottom: 1px solid #293334; }
  .col h2 span { display: block; margin-top: 5px; font: 400 .82rem/1.35 "Segoe UI", system-ui,
                 sans-serif; letter-spacing: 0; text-transform: none; color: #98a5a3; }
  .col.tests { border-top: 3px solid #57b8bd; }
  .col.tests h2 { color: #57b8bd; }
  .col.code { border-top: 3px solid #a855f7; }
  .col.code h2 { color: #a855f7; }
  pre { margin: 0; padding: 12px 0; overflow-x: auto;
        font: 13px/1.5 ui-monospace, Consolas, "DejaVu Sans Mono", monospace; }
  .ln { display: block; min-height: 1.5em; padding: 0 16px; white-space: pre; }
  .ln.cut { background: rgba(87, 184, 189, .16); box-shadow: inset 3px 0 0 #57b8bd; color: #c9f1f1; }
  .ln.gap { background: rgba(168, 85, 247, .10); box-shadow: inset 3px 0 0 #a855f7; color: #d8b4fe;
            font-style: italic; }
  .cutbox { margin: 0 0 22px; background: #141a1b; border: 1px solid #293334;
            border-left: 3px solid #57b8bd; border-radius: 10px; overflow: hidden; }
  .cutbox h2 { margin: 0; padding: 12px 16px 0; color: #57b8bd;
               font: 600 .78rem/1.2 ui-monospace, Consolas, monospace; letter-spacing: .12em;
               text-transform: uppercase; }
  footer { margin-top: 20px; color: #6d7b79; font-size: .85rem; }
  footer a { color: #57b8bd; }
  @media (max-width: 820px) { .cols { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
@@BODY@@
</div>
</body>
</html>
"""


def _removed_line_numbers(before, after):
    """
    Indexes into `before` of the lines the coding agent never receives.

    The same matcher `difflib.unified_diff` uses in `render`, so the page marks
    exactly the lines the terminal output counts.
    """
    removed = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, before, after).get_opcodes():
        if tag in ("delete", "replace"):
            removed.update(range(i1, i2))
    return removed


def _hole_label(entries, total):
    """
    A removed block, named in criteria where it holds them.

    `entries` is how many of the block's lines are list entries under
    `acceptance_criteria:`, `total` how many non-blank lines it has. The
    difference is the YAML key itself, which is not worth a number of its own.
    """
    if entries == 1:
        return "1 acceptance criterion"
    if entries:
        return "%d acceptance criteria" % entries
    return "%d line%s" % (total, "" if total == 1 else "s")


def render_html(facts):
    """
    The same facts as `render`, as one self-contained page to share.

    The terminal output is the most persuasive thing this tool prints and the
    hardest to pass on: a screenshot of a terminal crops it, and a paste loses
    the layout. This puts the two views side by side, marks every line the
    coding agent never receives, and loads nothing from anywhere.
    """
    import html

    esc = html.escape
    task_id = facts["task_id"]
    count = facts["criteria_count"]
    before = facts["test_generation_sees"].splitlines()
    after = facts["coding_agent_sees"].splitlines()
    removed = _removed_line_numbers(before, after)
    removed_count = sum(1 for i in removed if before[i].strip())

    # Where each removed block used to sit in the coding agent's file, so its
    # column shows the hole rather than silently closing up around it.
    # Each hole is counted in criteria where it holds them, for the same
    # reason the terminal leads with criteria: the reader has just been told
    # how many the task declares, and a line count is a different number.
    gaps = {}
    for tag, i1, i2, j1, _j2 in difflib.SequenceMatcher(None, before, after).get_opcodes():
        if tag not in ("delete", "replace"):
            continue
        block = [line.strip() for line in before[i1:i2] if line.strip()]
        hole = gaps.setdefault(j1, [0, 0])
        hole[0] += sum(1 for line in block if line.startswith("-"))
        hole[1] += len(block)

    def column(cls, title, note, lines, cut, holes=None):
        spans = []
        for i, line in enumerate(lines + [None]):
            if holes and holes.get(i) and holes[i][1]:
                spans.append('<span class="ln gap">%s removed here</span>'
                             % _hole_label(*holes[i]))
            if line is not None:
                spans.append('<span class="ln%s">%s</span>'
                             % (" cut" if i in cut else "", esc(line)))
        return ('<section class="col %s"><h2>%s<span>%s</span></h2><pre>%s</pre></section>'
                % (cls, title, note, "".join(spans)))

    parts = ['<p class="brand">qikly --explain</p>',
             "<h1>What each agent sees: %s</h1>" % esc(task_id)]
    if not count:
        parts.append('<p class="lede">%s declares no acceptance criteria, so there is '
                     "nothing to withhold and nothing to show.</p>" % esc(task_id))
    else:
        # Every count on this page is in criteria. Saying "12 lines removed" one
        # sentence after "declares 11 acceptance criteria" reads as a
        # contradiction until the reader works out that the twelfth line is the
        # YAML key, and most readers will not stop to do that.
        entries = sum(1 for i in removed if before[i].strip().startswith("-"))
        cut_phrase = ("all %d of them and the acceptance_criteria: key they hang off"
                      % count if entries == count and removed_count > count
                      else "%s, %d line%s in all"
                           % (_hole_label(entries, removed_count), removed_count,
                              "" if removed_count == 1 else "s"))
        parts.append(
            '<p class="lede">This task declares %d acceptance criteria. The agent that '
            "writes the tests receives all of them. The agent that writes the code receives "
            "the same file with them cut out: %s, %s characters down to %s.</p>"
            % (count, cut_phrase,
               format(facts["test_generation_chars"], ","),
               format(facts["coding_agent_chars"], ",")))
        if facts["withheld_ok"]:
            parts.append('<p class="verdict ok">No criterion text reaches the coding agent. '
                         "When a test fails, it sees the error and never the rule it broke.</p>")
        else:
            leaked = "".join("<br>%s" % esc(item[:160]) for item in facts["leaked"][:5])
            parts.append('<p class="verdict bad">FAILED: criterion text is present in what '
                         "the coding agent receives.%s</p>" % leaked)
    if removed:
        # The lines worth sharing, on the first screen. In the full file they
        # usually sit at the bottom, below everything both agents receive.
        cut_lines = "".join('<span class="ln cut">%s</span>' % esc(before[i])
                            for i in sorted(removed))
        parts.append('<section class="cutbox"><h2>Cut before the coding agent gets it</h2>'
                     "<pre>%s</pre></section>" % cut_lines)
    parts.append('<main class="cols">%s%s</main>' % (
        column("tests", "Test generation sees",
               "The whole task file. Highlighted lines are cut before the coding agent gets it.",
               before, removed),
        column("code", "The coding agent sees",
               "The same file, without them.", after, set(), gaps)))
    parts.append('<footer>%s, built by the same functions a real run uses, with no model '
                 'call. <a href="https://test.qikly.com/?ref=explain">test.qikly.com</a></footer>'
                 % esc(facts.get("task_path", task_id)))
    title = "qikly --explain %s: what each agent sees" % task_id
    return PAGE.replace("@@TITLE@@", esc(title)).replace("@@BODY@@", "\n".join(parts))
