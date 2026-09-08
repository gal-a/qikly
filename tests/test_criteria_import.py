"""
Reading acceptance criteria out of the place they were already written.

The blank `acceptance_criteria:` list is the largest thing between someone and
a first run, and for most teams it is not actually blank: the rules are sitting
in a ticket, written before any code was cut, because the process asked for
them. Only the container is wrong.

Two properties are load-bearing here, and both are about restraint. Pasting a
whole ticket must not turn its description into criteria, and prose must never
be chopped into sentences and offered up as rules. A criterion nobody wrote is
exactly the invented bar this project exists to argue against, and it would be
invisible afterwards: it would look like every other line in the file.
"""
import textwrap

from qikly.criteria_import import parse_criteria


def _t(text):
    return parse_criteria(textwrap.dedent(text))


# ------------------------------------------------------- the common case ----

def test_a_plain_bullet_list_is_read_in_order():
    """Far and away what real acceptance criteria look like."""
    assert _t("""\
        - first rule
        - second rule
        - third rule
    """) == ["first rule", "second rule", "third rule"]


def test_every_common_bullet_marker_counts():
    for marker in ("-", "*", "+", "1.", "2)"):
        assert _t(f"{marker} a rule\n") == ["a rule"], marker


def test_a_checkbox_is_markup_rather_than_a_criterion():
    """
    An unticked box is still a rule that has to hold. Ticket templates add
    them for tracking, and carrying `[ ]` into the bar would put it in front of
    a model as though it meant something.
    """
    assert _t("- [ ] a rule\n- [x] another\n") == ["a rule", "another"]


# ------------------------------------------- pasting a whole ticket in ------

def test_only_the_criteria_section_of_a_ticket_is_read():
    """
    The property that makes copy-paste usable. A ticket has a description and
    usually some notes, both of which contain lists, and neither of which is a
    standard the code should be judged against.
    """
    got = _t("""\
        PROJ-412  Merge overlapping exports

        Description
        Combine two CSV exports.
        - this bullet is part of the description

        ## Acceptance Criteria
        - a transaction in both files appears once
        - a negative amount is rejected

        ## Notes
        - ask finance about rounding
    """)
    assert got == ["a transaction in both files appears once",
                   "a negative amount is rejected"]


def test_a_bolded_heading_works_as_well_as_a_markdown_one():
    """Jira and Linear render headings this way constantly."""
    assert _t("""\
        **Acceptance criteria:**
        - one
        - two

        **Notes**
        - ignore me
    """) == ["one", "two"]


def test_an_undecorated_heading_works_too():
    assert _t("""\
        Acceptance Criteria:
        - one

        Notes:
        - ignore me
    """) == ["one"]


def test_a_file_that_is_only_a_list_needs_no_heading():
    """
    The simplest thing anyone will hand this. Requiring a heading in order to
    read a file that is nothing but criteria would fail the easy case to serve
    the hard one.
    """
    assert _t("- one\n- two\n") == ["one", "two"]


# ------------------------------------------------------------- gherkin ------

def test_a_scenario_becomes_one_criterion():
    """
    One scenario describes one rule, so it collapses to one criterion rather
    than three. Supported because Xray, Cucumber and SpecFlow speak it, and
    deliberately not treated as the expected format.
    """
    got = _t("""\
        Feature: Sales merge
          Scenario: duplicate transaction
            Given a transaction appears in both files
            When the amounts agree
            Then it appears once in the output
    """)
    assert len(got) == 1
    assert got[0].startswith("duplicate transaction:")
    assert "amounts agree" in got[0] and "appears once" in got[0]


def test_each_scenario_is_its_own_criterion():
    got = _t("""\
        Scenario: one
          Given a
          Then b
        Scenario: two
          Given c
          Then d
    """)
    assert len(got) == 2


def test_feature_and_background_lines_are_not_criteria():
    got = _t("""\
        Feature: something
        Background:
          Given a shared setup
        Scenario: real one
          Then it holds
    """)
    assert len(got) == 1
    assert "shared setup" not in got[0]


# ---------------------------------------------------------- the restraint ---

def test_prose_produces_nothing_rather_than_guessed_criteria():
    """
    The most important test in this file.

    It is tempting to split a paragraph on sentence boundaries so that every
    input yields something. That would manufacture a standard nobody wrote and
    then judge code against it, which is the failure this whole project is
    built to prevent, committed by the tool itself. An empty result is a real
    answer: it says nobody wrote criteria here.
    """
    assert _t("""\
        This should merge the files correctly and handle errors. Amounts must
        be valid. Dates should be sensible.
    """) == []


def test_an_empty_input_is_not_an_error():
    assert parse_criteria("") == []
    assert parse_criteria(None) == []


def test_windows_line_endings_are_handled():
    assert parse_criteria("- one\r\n- two\r\n") == ["one", "two"]


# ------------------------------------------------------------- the CLI -----

def test_only_yaml_reaches_stdout(tmp_path, capsys, monkeypatch):
    """
    The command exists to be pasted or redirected, so stdout has to be a valid
    YAML block on its own. Advice goes to stderr. Mixing them would make

        qikly --criteria-from ticket.md >> task.yaml

    append prose into the middle of a config file.
    """
    import yaml

    from qikly import cli

    ticket = tmp_path / "ticket.md"
    ticket.write_text("## Acceptance Criteria\n- a rule\n- another rule\n",
                      encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), None) == 0
    captured = capsys.readouterr()
    parsed = yaml.safe_load(captured.out)
    assert parsed["acceptance_criteria"] == ["a rule", "another rule"]
    assert captured.err.strip(), "the guidance should still be shown, on stderr"


def test_a_quote_inside_a_criterion_survives_the_round_trip(tmp_path, capsys, monkeypatch):
    import yaml

    from qikly import cli

    ticket = tmp_path / "t.md"
    ticket.write_text('- rejected, naming the "amount" field\n', encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    cli._do_criteria_from(str(ticket), None)
    parsed = yaml.safe_load(capsys.readouterr().out)
    assert parsed["acceptance_criteria"] == ['rejected, naming the "amount" field']


def test_a_task_that_already_has_criteria_is_never_overwritten(tmp_path, capsys, monkeypatch):
    """
    Merging two bars automatically would be a guess about which rule wins, made
    silently, about the one input everything else is judged against.
    """
    from qikly import cli

    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    original = 'task_id: "T"\nacceptance_criteria:\n  - "the existing rule"\n'
    (tasks / "T.yaml").write_text(original, encoding="utf-8")
    ticket = tmp_path / "t.md"
    ticket.write_text("- a new rule\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), "T") == 2
    assert (tasks / "T.yaml").read_text(encoding="utf-8") == original


def test_criteria_are_appended_to_a_task_that_has_none(tmp_path, capsys, monkeypatch):
    import yaml

    from qikly import cli

    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T.yaml").write_text('task_id: "T"\nrequirements: "do a thing"\n',
                                  encoding="utf-8")
    ticket = tmp_path / "t.md"
    ticket.write_text("- one\n- two\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), "T") == 0
    written = yaml.safe_load((tasks / "T.yaml").read_text(encoding="utf-8"))
    assert written["acceptance_criteria"] == ["one", "two"]
    assert written["requirements"] == "do a thing", "the rest of the task survived"


def test_a_file_with_no_criteria_exits_non_zero(tmp_path, capsys, monkeypatch):
    from qikly import cli

    ticket = tmp_path / "t.md"
    ticket.write_text("Just some prose about the feature.\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_criteria_from(str(ticket), None) == 2


def test_a_scaffolded_placeholder_does_not_block_an_import(tmp_path, monkeypatch):
    """
    The two features did not compose, which only a clean-directory run showed.
    --scaffold seeds `acceptance_criteria: ["TODO: ..."]` so the shape of the
    file is obvious, and --criteria-from then refused to write because the key
    was non-empty. That blocked the natural sequence: scaffold from your code,
    then import the criteria from the ticket that described it.

    A placeholder qikly wrote itself is not a bar worth protecting, so it is
    replaced rather than appended under.
    """
    import yaml

    from qikly import cli

    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T.yaml").write_text(
        'task_id: "T"@requirements: "r"@acceptance_criteria:@'
        '  - "TODO: one checkable statement, with its boundary value"@'.replace("@", chr(10)),
        encoding="utf-8")
    ticket = tmp_path / "t.md"
    ticket.write_text("- 100 is accepted and 101 is rejected@".replace("@", chr(10)),
                      encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), "T") == 0
    written = yaml.safe_load((tasks / "T.yaml").read_text(encoding="utf-8"))
    assert written["acceptance_criteria"] == ["100 is accepted and 101 is rejected"], (
        "the placeholder should be replaced, not kept alongside")
    assert written["requirements"] == "r", "the rest of the task survived"


def test_real_criteria_are_still_protected(tmp_path, monkeypatch):
    """The guard must only relax for a placeholder, never for a written bar."""
    from qikly import cli

    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    original = ('task_id: "T"@acceptance_criteria:@  - "a real rule"@'
                .replace("@", chr(10)))
    (tasks / "T.yaml").write_text(original, encoding="utf-8")
    ticket = tmp_path / "t.md"
    ticket.write_text("- a new rule" + chr(10), encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))

    assert cli._do_criteria_from(str(ticket), "T") == 2
    assert (tasks / "T.yaml").read_text(encoding="utf-8") == original
