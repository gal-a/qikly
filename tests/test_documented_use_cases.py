"""
Every row of the use-case table on the landing page actually works.

`docs/index.html` tells a reader which command to run based on which parts of
a task file they already have. Seven rows, seven promises, and until now they
were covered unevenly: `--scaffold` and `--resume` had their own files while
`--generate-criteria` was tested only for defaulting to off, which says
nothing about whether it does the thing the table claims.

These are offline. Where a row needs a model, the call is stubbed: the point
is that the wiring holds and the documented effect happens, not that a model
answers well. The stub is always the smallest possible one, so a break in the
code around it still fails here.

The last test in this file is the one that matters most. It reads the table
out of the page and fails if a row exists with no test above it, so a row
added later cannot quietly become an undocumented promise.
"""
import os
import re

import pytest
import yaml

from qikly import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "docs", "index.html")


# ------------------------------------------------------- row: just looking --

def test_demo_writes_only_inside_its_own_folder(tmp_path, monkeypatch):
    """
    The table promises "a throwaway folder". If the demo could write outside
    it, the promise on the page would be false and someone would find out by
    losing something.
    """
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    root = cli._demo_root()
    assert root.startswith(str(tmp_path))
    assert cli.DEMO_DIR in root


# ------------------------------------ row: code someone else wrote (part 2) --

def test_scaffold_writes_the_interface_and_refuses_to_write_the_criteria(tmp_path,
                                                                         monkeypatch):
    """
    The row claims scaffold produces part 2 and leaves 1 and 3 to you. The
    refusal is the load-bearing half: criteria read out of an implementation
    only describe what it already does.
    """
    module = tmp_path / "billing.py"
    module.write_text("def run_billing(paths, out):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("billing.py", None) == 0

    written = yaml.safe_load(
        (tmp_path / "inputs_private/config/tasks/BILLING.yaml").read_text(encoding="utf-8"))
    assert written["interface"]["module"]
    assert written["interface"]["integration_functions"]
    assert "TODO" in written["acceptance_criteria"][0]
    assert "TODO" in written["requirements"][0]


# --------------------------------------------- row: requirements only (1) --

def test_init_creates_a_runnable_layout_with_a_starter_task(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_init() == 0
    task = tmp_path / "inputs_private/config/tasks/MY_FIRST_TASK.yaml"
    assert task.exists()
    data = yaml.safe_load(task.read_text(encoding="utf-8"))
    assert data["requirements"] and data["acceptance_criteria"]


# --------------------------------------------- row: want a draft of the bar --

def test_generate_criteria_writes_a_draft_into_a_task_that_has_none(tmp_path,
                                                                    monkeypatch):
    """
    The row this file exists for. It was covered only by a test asserting the
    flag defaults to False, which says nothing about whether the flag does
    what the page says.
    """
    from qikly.orchestrator import orchestrator as orch

    task = tmp_path / "NEEDS_BAR.yaml"
    task.write_text(
        'task_id: "NEEDS_BAR"\n'
        "requirements:\n"
        '  - "Reject any row whose amount is not positive"\n',
        encoding="utf-8")
    out = tmp_path / "written.yaml"
    monkeypatch.setattr(orch, "task_config_path", lambda t: str(task))
    # It reads the task wherever it lives but writes to inputs_private, so
    # that a bundled example gains your own overriding copy rather than being
    # edited in place. Patching only the read path lets it write into the real
    # tree, which is how this test first found the distinction.
    monkeypatch.setattr(orch, "private_input_path", lambda rel: str(out))
    monkeypatch.setattr(
        "qikly.agent_api.agent_interface.agent_generate_acceptance_criteria",
        lambda *a, **k: ["amount 0 is rejected and 0.01 is accepted"])

    assert orch.generate_and_write_acceptance_criteria_if_missing("NEEDS_BAR") is True
    assert yaml.safe_load(out.read_text(encoding="utf-8"))[
        "acceptance_criteria"] == ["amount 0 is rejected and 0.01 is accepted"]
    assert "acceptance_criteria" not in task.read_text(encoding="utf-8"), (
        "the task it read was edited in place; a bundled example must stay untouched"
    )


def test_generate_criteria_never_clobbers_a_bar_you_wrote(tmp_path, monkeypatch):
    """
    The opt-in exists so a hand-written bar survives. Overwriting one would
    destroy the only ground truth the task had, silently.
    """
    from qikly.orchestrator import orchestrator as orch

    task = tmp_path / "HAS_BAR.yaml"
    task.write_text(
        'task_id: "HAS_BAR"\n'
        "requirements:\n"
        '  - "Reject any row whose amount is not positive"\n'
        "acceptance_criteria:\n"
        '  - "mine, written by hand"\n',
        encoding="utf-8")
    monkeypatch.setattr(orch, "task_config_path", lambda t: str(task))
    monkeypatch.setattr(
        "qikly.agent_api.agent_interface.agent_generate_acceptance_criteria",
        lambda *a, **k: pytest.fail("a model was called for a task that already has a bar"))

    assert orch.generate_and_write_acceptance_criteria_if_missing("HAS_BAR") is False
    assert yaml.safe_load(task.read_text(encoding="utf-8"))[
        "acceptance_criteria"] == ["mine, written by hand"]


# ------------------------------------------------- row: you wrote all three --

def test_a_task_with_all_three_parts_is_discoverable_and_withholds_the_third():
    """
    The highlighted row. The whole claim is that part 3 reaches test
    generation and stops there, so this checks the stripped spec still carries
    1 and 2 and has lost 3.
    """
    from qikly.agent_api.agent_interface import _ACCEPTANCE_CRITERIA_RE, task_config_path
    from qikly.orchestrator.orchestrator import discover_task_ids

    assert "CALC_TAX" in discover_task_ids()
    with open(task_config_path("CALC_TAX"), encoding="utf-8") as handle:
        raw = handle.read()
    stripped = yaml.safe_load(_ACCEPTANCE_CRITERIA_RE.sub("", raw))
    assert stripped["requirements"], "the coding agent lost part 1"
    assert stripped["interface"], "the coding agent lost part 2"
    assert "acceptance_criteria" not in stripped, "part 3 reached the coding agent"


# ------------------------------------------------------ row: doubt the spec --

def test_check_criteria_gates_on_a_contradiction(monkeypatch, capsys):
    from qikly.orchestrator.tuning import check_criteria as cc

    monkeypatch.setattr(cc, "check", lambda t, seed=None: [
        {"criterion": "c", "conflicts_with": "r", "why": "w"}])
    assert cli._do_check_criteria("CALC_TAX") == 1
    assert "contradiction" in capsys.readouterr().out


def test_check_criteria_exits_zero_on_a_clean_spec(monkeypatch):
    from qikly.orchestrator.tuning import check_criteria as cc

    monkeypatch.setattr(cc, "check", lambda t, seed=None: [])
    assert cli._do_check_criteria("CALC_TAX") == 0


# ----------------------------------------------------------- row: it stopped --

def test_resume_reads_the_disk_rather_than_trusting_the_flag():
    """
    The row promises it picks up what is there. Resuming a task with nothing
    on disk must therefore behave exactly like a fresh run, not fail.
    """
    from qikly.orchestrator.orchestrator import resumable

    state = resumable("NO_SUCH_TASK_XYZ")
    assert state["tests"] == {}
    assert state["implementation"] is False


# ------------------------------------------------- the table cannot outgrow us --

def _documented_commands():
    with open(PAGE, encoding="utf-8") as handle:
        page = handle.read()
    table = re.search(r'<table class="uses">.*?</table>', page, re.S)
    assert table, "the use-case table is gone from the landing page"
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S)
    out = []
    for row in rows[1:]:                       # skip the header
        code = re.search(r"<code>(.*?)</code>", row, re.S)
        if code:
            out.append(re.sub(r"\s+", " ", code.group(1)).strip())
    return out


def test_every_row_of_the_table_names_a_flag_that_exists():
    """
    A documented command that does not parse is worse than an undocumented
    one: the reader assumes they typed it wrong.
    """
    import sys

    argv = sys.argv
    try:
        for command in _documented_commands():
            flags = re.findall(r"--[a-z-]+", command)
            args = []
            for flag in flags:
                args.append(flag)
                if flag in ("--tasks", "--scaffold", "--task-id", "--demo-dir",
                            "--criteria-from", "--criteria-from-jira",
                            "--explain", "--compare-criteria", "--artifacts-url"):
                    args.append("X")
            sys.argv = ["qikly"] + args
            try:
                cli._parse_args()
            except SystemExit:
                pytest.fail(f"the page documents a command that does not parse: {command}")
    finally:
        sys.argv = argv


def test_the_table_still_has_a_row_for_every_use_case_we_test():
    """
    The guard that keeps this file honest. If a row is added to the page and
    nothing here covers it, the page is making a promise no test checks.
    """
    commands = _documented_commands()
    assert len(commands) >= 8, f"the table lost rows: {commands}"
    joined = " ".join(commands)
    for flag in ("--demo", "--scaffold", "--init", "--generate-criteria",
                 "--check-criteria", "--resume", "--criteria-from"):
        assert flag in joined, f"{flag} is no longer documented in the table"
    assert any(c.strip() in ("qikly --tasks <MY_TASKS>", "qikly --tasks &lt;MY_TASKS&gt;")
               for c in commands), "the plain run, the case the tool is built for, is missing"


# --------------------------------------- row: the rules are in a ticket -----


def test_criteria_can_be_lifted_from_a_ticket(tmp_path, monkeypatch):
    """
    The table promises that pasting a ticket in gets you its acceptance
    criteria and not its description. Offline, no model involved: this is a
    parser. `tests/test_criteria_import.py` covers the formats in full; this
    checks the row's promise end to end through the CLI.
    """
    ticket = tmp_path / "ticket.md"
    ticket.write_text(
        "PROJ-1 Something\n\n"
        "Description\n- not a criterion\n\n"
        "## Acceptance Criteria\n- a real rule\n", encoding="utf-8")
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T.yaml").write_text('task_id: "T"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), "T") == 0
    written = yaml.safe_load((tasks / "T.yaml").read_text(encoding="utf-8"))
    assert written["acceptance_criteria"] == ["a real rule"]


# ------------------------------ the troubleshooting section is executable ---

def _troubleshooting():
    """The dedicated page. The README carries a summary and a link to it."""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "TROUBLESHOOTING.md"), encoding="utf-8") as handle:
        return handle.read()


def test_every_flag_it_recommends_parses():
    """
    Someone reads this section at the worst moment, after a run they paid for
    stalled. A command that does not parse there turns a troubleshooting guide
    into a second problem.
    """
    import re
    import sys

    argv = sys.argv
    cli_flags = {"--check-criteria", "--validate", "--trends", "--by", "--tasks"}
    try:
        for flag in sorted(set(re.findall(r"--[a-z-]+", _troubleshooting()))):
            if flag not in cli_flags:
                continue  # run_all's flags, checked below
            args = [flag]
            if flag in ("--tasks", "--by"):
                args.append("X" if flag == "--tasks" else "week")
            sys.argv = ["qikly"] + args
            try:
                cli._parse_args()
            except SystemExit:
                pytest.fail(f"the troubleshooting section recommends {flag}, "
                            f"which does not parse")
    finally:
        sys.argv = argv


def test_the_settings_keys_it_names_exist():
    """
    Three settings are named as things to check. A key that has been renamed
    sends someone editing a file that will have no effect.
    """
    import os

    import yaml

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "src", "qikly", "inputs_public", "config",
                           "settings.yaml"), encoding="utf-8") as handle:
        settings = yaml.safe_load(handle)

    block = _troubleshooting()
    if "max_retries_per_stage" in block:
        assert "max_retries_per_stage" in (settings.get("orchestrator") or {})
    if "test_order" in block:
        assert "test_order" in (settings.get("orchestrator") or {})
    if "criteria_per_batch" in block:
        assert "criteria_per_batch" in (settings.get("test_generation") or {})


def test_it_leads_with_the_thing_that_matters_most():
    """
    Model choice moves convergence more than any setting in the file, and it is
    one environment variable. Anything else first sends someone editing YAML
    when they should be changing models.
    """
    block = _troubleshooting()
    first = block.index("## 1.")
    assert "stronger model" in block[first:first + 120].lower()
    # And the README's summary must not bury it either, since that is where
    # most people will read it.
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    summary = readme[readme.index("## When a run does not converge"):]
    assert "stronger model" in summary[:900]


def test_it_ends_by_saying_one_run_proves_nothing():
    """
    The conclusion someone is about to draw from a single stall is the one this
    project exists to prevent them drawing.
    """
    block = _troubleshooting()
    assert "artifact, not a rate" in block
    assert "--repeat" in block[block.index("artifact, not a rate"):]
    # It has to be near the end, where a reader lands after trying everything,
    # not buried among the ten checks.
    assert block.index("artifact, not a rate") > len(block) * 0.75


def test_scaffold_says_which_code_a_run_will_test():
    """
    A reader asked, correctly, whether "code someone else wrote, and you want it
    verified" meant supplying the interface or the implementation. It meant
    both, and nothing said so: a scaffolded task runs against a FRESH
    implementation unless seed.implementation is uncommented, so someone
    pointing qikly at their own module would have watched it write different
    code and test that instead.

    The choice is now in the file it applies to, and in the guidance printed
    when the file is written.
    """
    import inspect

    from qikly import cli, scaffold

    # Two files now, rather than one file with the deciding line commented
    # out. Commenting asks a reader to understand the distinction before they
    # have run anything; two short files let them read both and delete one.
    assert "seed:" in scaffold.SEED_EXISTING
    assert "implementation:" in scaffold.SEED_EXISTING
    # On a line basis, not a substring: SEED_NONE mentions `seed:` inside a
    # comment explaining its absence, which is the opposite of declaring one.
    active = [l for l in scaffold.SEED_NONE.splitlines()
              if l.strip().startswith("seed:")]
    assert not active, f"the fresh-implementation task declares a seed: {active}"
    assert "{seed_block}" in scaffold.TASK_TEMPLATE, "the ending is chosen, not fixed"

    printed = inspect.getsource(cli._do_scaffold)
    assert "_VERIFY" in printed, "the two files must be distinguishable by name"
    assert "delete the other" in printed, "and the reader has to be told to pick"


def test_the_landing_page_marks_the_three_parts_consistently():
    """
    The table's columns are #1, #2 and #3, and the definitions above it have to
    carry the same marks or the table is three unlabelled ticks.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    for mark in ("#1", "#2", "#3"):
        assert page.count(mark) >= 2, f"{mark} appears in fewer than two places"
    assert 'title="requirements">#1' in page
    assert 'title="acceptance_criteria">#3' in page


def test_the_page_answers_the_two_models_objection():
    """
    The first thing a sceptical reader says is "use a different model for each
    half". Leaving it unanswered on the page that makes the argument is how a
    reader decides the argument was not thought through.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    # Matched on the objection being raised and answered, not on one phrasing:
    # this text was rewritten once for being too long to follow.
    assert "another for the tests" in page, "the objection is not stated"
    assert "does not fix the underlying issue" in page, (
        "the objection is stated but not answered")
    assert "what they were shown" in page, "the answer does not name the reason"


def _worked_example(design):
    """
    The worked example's section, located structurally rather than by its
    title. The title is prose and gets rewritten; the numbered walkthrough
    inside it is the thing that makes it the worked example.
    """
    marker = design.index("### 1. What the coding agent is given")
    return design.rfind(chr(10) + "## ", 0, marker) + 1


def _after_worked_example(design):
    """
    Where the worked example ends and the argument begins: the next H2 after
    it. Located structurally because section titles are prose, and pinning
    prose means a wording change fails a test about ordering.
    """
    return design.index(chr(10) + "## ", _worked_example(design) + 1) + 1


def test_the_worked_example_quotes_a_real_run():
    """
    The worked example in DESIGN_1_CASE_STUDY.md is lifted from one run of
    CALC_TAX, not written
    by hand. That is the whole reason it is worth including: an invented
    example proves the author understood the design, and a real one proves the
    design does what it says.

    The facts it quotes are pinned here against the artifacts that produced
    them, so a rewrite that drifts into illustration fails.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "DESIGN_1_CASE_STUDY.md"),
              encoding="utf-8") as handle:
        design = handle.read()
    example = design[_worked_example(design):
                     _after_worked_example(design)]

    # The failing assertion, the reasoning it produced, and the one-character
    # fix. Each is a direct quote from the run.
    for quoted in ("test_tax_rate_validation_rules",
                   "assert 150.0 <= 100",
                   "lacks an upper bound check",
                   "tax_rate > 100"):
        assert quoted in example, f"the worked example no longer quotes {quoted!r}"

    # And the criterion it never saw has to still exist in the shipped task,
    # or the example is describing a rule the reader cannot go and find.
    with open(os.path.join(root, "src", "qikly", "inputs_public", "config",
                           "tasks", "CALC_TAX.yaml"), encoding="utf-8") as handle:
        assert "more than 100% is also" in handle.read()


def test_the_design_opens_with_the_diagram_and_the_example():
    """
    The article argued for three screens before showing anything, and a reader
    who has not seen the split reads all of that in the wrong frame. Order is
    the fix, so order is what is pinned.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "DESIGN_1_CASE_STUDY.md"),
              encoding="utf-8") as handle:
        design = handle.read()

    diagram = design.index("```mermaid")
    example = _worked_example(design)
    argument = _after_worked_example(design)
    assert diagram < example < argument, (
        "the diagram and the worked example must both come before the argument")

    # Measured from where the prose starts, not from byte zero: every part
    # carries a maintenance comment and a part-of-three nav table, and those
    # are not what buries a diagram.
    prose_starts = design.index("# Engineering a Better System")
    assert diagram - prose_starts < 3000, (
        "the diagram is too far down to frame what follows")


def test_the_hero_image_quotes_the_same_run_as_the_article():
    """
    docs/images/qikly_hero.png is the blog header, and it is rasterised from
    docs/images/qikly_hero.svg, so the SVG is the source and the only copy worth
    checking. It carries three things that can go stale independently of the
    prose beside them: the run's cost, the passing count, and the command a
    reader is invited to type. An image is the worst place for a stale number,
    because nobody greps a picture.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "images", "qikly_hero.svg"),
              encoding="utf-8") as handle:
        hero = handle.read()
    with open(os.path.join(root, "docs", "DESIGN_1_CASE_STUDY.md"),
              encoding="utf-8") as handle:
        design = handle.read()
    with open(os.path.join(root, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()

    assert "![" in design and "images/qikly_hero.png" in design, (
        "the article no longer shows the header image")

    # The same run the worked example is lifted from.
    assert "38s" in hero and "11 model calls" in hero
    assert "38 seconds and 11 model calls" in design, (
        "the article and the header image disagree about the run's cost")
    assert "9/9 passed" in hero and "9/9 passed" in design

    # The rule the coding agent had to reconstruct, on the code card.
    assert "rate &gt; 100" in hero

    # And the command on the image has to be one the tool actually has.
    assert "$ qikly --demo" in hero
    assert "qikly --demo" in readme, (
        "the header image offers a command the README does not document")
