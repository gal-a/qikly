"""
Criteria read out of prose, and the two guards that make them trustworthy.

The command's whole claim is that a reader can check its working. That rests
on the quote beside each criterion being real, and on a sentence that cannot
be tested being refused rather than guessed at. Both are enforced in code
rather than asked for in the prompt, because a prompt cannot be relied on:
against one project the model fabricated three different versions of the same
quoted line, inventing a CJK character, then two Latin words.

These tests pin the enforcement, not the model. The model is stubbed, so they
run offline and cost nothing.
"""
import json
import os

import pytest
import yaml

from qikly import criteria_from_docs as cfd


DOC = """# widget

Formatting
----------

``simple`` is the default format.

An unknown format name raises ValueError.

The formatter tries to produce tidier output.
"""


def _doc(tmp_path, text=DOC, name="README.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _stub(monkeypatch, payload):
    """Answer the one model call with `payload`, as the real call would."""
    monkeypatch.setattr(
        "qikly.agent_api.call_llm.call_llm",
        lambda mode, prompt, seed=None: payload)


def test_a_criterion_whose_quote_is_real_is_kept(tmp_path, monkeypatch):
    _stub(monkeypatch, json.dumps({
        "criteria": [{"criterion": "the default format is simple",
                      "source": "``simple`` is the default format."}],
        "rejected": []}))
    kept, rejected, unquoted = cfd.extract([_doc(tmp_path)])
    assert [c["criterion"] for c in kept] == ["the default format is simple"]
    assert unquoted == []


def test_a_fabricated_quote_is_dropped_rather_than_reported(
        tmp_path, monkeypatch):
    """
    The guard that matters most.

    A criterion the reader cannot verify is worse than no criterion, because
    the whole offer is "check my working". The real failure looked exactly
    like this: a plausible sentence with two characters that were never in
    the file.
    """
    _stub(monkeypatch, json.dumps({
        "criteria": [{"criterion": "the default format is simple",
                      "source": "``simple`` is the default format mo."}],
        "rejected": []}))
    kept, _, unquoted = cfd.extract([_doc(tmp_path)])
    assert kept == []
    assert len(unquoted) == 1


def test_reflowed_whitespace_is_not_treated_as_fabrication(
        tmp_path, monkeypatch):
    """
    Prose wraps. A quote broken across lines is the same sentence, and
    rejecting it would throw away good criteria for a formatting difference.
    """
    _stub(monkeypatch, json.dumps({
        "criteria": [{"criterion": "an unknown format name raises ValueError",
                      "source": "An unknown format\n    name raises "
                                "ValueError."}],
        "rejected": []}))
    kept, _, unquoted = cfd.extract([_doc(tmp_path)])
    assert len(kept) == 1 and unquoted == []


def test_rejected_sentences_survive_to_the_report(tmp_path, monkeypatch):
    """
    They are a deliverable, not debris: "this sentence does not say what it
    means" is often the more useful finding, and printing them is how a
    reader sees the rule was applied rather than skipped.
    """
    _stub(monkeypatch, json.dumps({
        "criteria": [],
        "rejected": [{"sentence": "The formatter tries to produce tidier "
                                  "output.",
                      "why": "tidier is not an observable result"}]}))
    kept, rejected, _ = cfd.extract([_doc(tmp_path)])
    assert kept == []
    text = cfd.render(["README.md"], kept, rejected, [])
    assert "tidier is not an observable result" in text
    assert "No testable claim found" in text


def test_a_stray_backslash_does_not_lose_the_whole_reply(
        tmp_path, monkeypatch):
    """
    Documentation is full of backslashes, in format strings and regexes, and
    the model passes them into JSON unescaped. One of them made an entire
    library's reply unparseable, so the repair is load-bearing rather than
    cosmetic.
    """
    _stub(monkeypatch,
          '{"criteria": [{"criterion": "a \\d escape is matched",'
          ' "source": "``simple`` is the default format."}],'
          ' "rejected": []}')
    kept, _, _ = cfd.extract([_doc(tmp_path)])
    assert len(kept) == 1


def test_the_report_is_paste_ready_yaml(tmp_path, monkeypatch):
    _stub(monkeypatch, json.dumps({
        "criteria": [{"criterion": 'the default is "simple"',
                      "source": "``simple`` is the default format."}],
        "rejected": []}))
    kept, rejected, unquoted = cfd.extract([_doc(tmp_path)])
    text = cfd.render(["README.md"], kept, rejected, unquoted)
    # Parse it, rather than counting quote characters. The earlier version of
    # this test counted them, which passed on output yaml.safe_load rejects
    # and baked in a bug: a double quote in a criterion was rewritten to a
    # single quote, silently changing the literal the prompt had asked the
    # model to preserve exactly.
    doc = yaml.safe_load(text)
    assert doc["acceptance_criteria"] == ['the default is "simple"']


def test_empty_documents_are_refused_before_a_model_is_called(tmp_path):
    with pytest.raises(ValueError):
        cfd.extract([_doc(tmp_path, text="   \n")])


# ------------------------------------------- what the quote check refuses --
#
# Each of these was accepted by an earlier `quote in haystack` check, and was
# reproduced in an audit on 2026-10-08.

NEVER = "The parser never raises on empty input.\nIt returns None for blank text.\n"


@pytest.mark.parametrize("quote", [
    "raises on empty input.",          # drops "never", inverting the claim
    "e",                               # one character
    "### a.md",                        # qikly's own header, not the document
    "It returns None for blank text. Negative widths are rejected.",  # spans two files
])
def test_a_quote_that_is_not_a_whole_sentence_of_one_document_is_refused(quote):
    bodies = [NEVER, "Negative widths are rejected.\n"]
    assert cfd._as_quoted(quote, bodies) is None


def test_a_whole_sentence_is_accepted_and_a_composed_accent_matches():
    decomposed = "Cafe\u0301 names are sorted by their accented form.\n"
    composed = "Caf\u00e9 names are sorted by their accented form."
    assert cfd._as_quoted(composed, [decomposed]) == composed


def test_a_fabricated_rejection_is_not_printed_as_a_quote(tmp_path, monkeypatch):
    """A rejected sentence sits beside the same `>` marker as a real quote."""
    _stub(monkeypatch, json.dumps({
        "criteria": [],
        "rejected": [{"sentence": "The formatter guesses the column widths.",
                      "kind": "ambiguous_claim", "why": "invented"}]}))
    _, rejected, _ = cfd.extract([_doc(tmp_path)])
    assert rejected == []


def test_malformed_items_are_skipped_rather_than_crashing(tmp_path, monkeypatch):
    _stub(monkeypatch, json.dumps({
        "criteria": ["a bare string", {"source": "no criterion key"},
                     {"criterion": "ok", "source": 5},
                     {"criterion": "the default format is simple",
                      "source": "``simple`` is the default format."}],
        "rejected": {"not": "a list"}}))
    kept, rejected, unquoted = cfd.extract([_doc(tmp_path)])
    assert [c["criterion"] for c in kept] == ["the default format is simple"]
    assert rejected == []
    assert [u["criterion"] for u in unquoted] == ["ok"]


# ----------------------------------------------- parsing what comes back --

def test_a_valid_escape_beside_a_stray_one_survives():
    """The old scanner read the second backslash of `\\d` as a new escape."""
    reply = r'{"criteria": [{"criterion": "x", "source": "\\d and \s"}]}'
    assert "\\\\d" in reply, "the valid pair must reach the parser intact"
    assert cfd._loads(reply)["criteria"][0]["source"] == r"\d and \s"


def test_a_windows_path_with_a_lowercase_u_survives():
    reply = r'{"criteria": [{"criterion": "x", "source": "C:\users\x"}]}'
    assert cfd._loads(reply)["criteria"][0]["source"] == r"C:\users\x"


def test_prose_with_braces_before_the_json_is_skipped():
    reply = ('Here is the {criteria} JSON you asked for: '
             '{"criteria": [{"criterion": "ok", "source": "s"}]}')
    assert cfd._loads(reply)["criteria"][0]["criterion"] == "ok"


def test_a_regex_word_boundary_is_not_called_a_fabrication(tmp_path,
                                                          monkeypatch):
    r"""
    JSON reads `\b` as a backspace, so a quote of a regex arrived changed, no
    longer matched the document, and an honest criterion was printed under
    "a model will invent a citation".
    """
    doc = _doc(tmp_path, r"Use \bword\b to match a whole word anywhere." + "\n")
    # Raw strings: the reply holds the two characters backslash and b, which
    # is valid JSON for a backspace.
    _stub(monkeypatch,
          r'{"criteria": [{"criterion": "\bword\b matches a whole word", '
          r'"source": "Use \bword\b to match a whole word anywhere."}]}')
    kept, _, unquoted = cfd.extract([doc])
    assert unquoted == []
    assert kept[0]["source"] == r"Use \bword\b to match a whole word anywhere."
    assert kept[0]["criterion"] == r"\bword\b matches a whole word"


def test_an_unparseable_reply_says_what_came_back(tmp_path, monkeypatch):
    _stub(monkeypatch, "Sorry, I cannot help with that {")
    with pytest.raises(ValueError) as caught:
        cfd.extract([_doc(tmp_path)])
    assert "Sorry, I cannot help" in str(caught.value)


# ------------------------------------------------------------- the command --

def _cli(monkeypatch, tmp_path, extract):
    from qikly import cli
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setattr("qikly.criteria_from_docs.extract", extract)
    return cli


def test_a_relative_path_is_read_from_where_the_command_was_typed(
        tmp_path, monkeypatch, capsys):
    """
    `chdir_to_project_root()` has run by then, and a bare README.md used to
    find qikly's own README, send that to the model and report success.
    """
    _doc(tmp_path)
    seen = []
    cli = _cli(monkeypatch, tmp_path,
               lambda paths, seed=None: seen.extend(paths) or ([], [], []))
    assert cli._do_criteria_from_docs(["README.md"]) == 0
    assert seen == [str(tmp_path / "README.md")]


def test_a_missing_document_exits_2_before_any_call(tmp_path, monkeypatch,
                                                    capsys):
    def must_not_run(paths, seed=None):
        raise AssertionError("a model call was made for a missing file")
    cli = _cli(monkeypatch, tmp_path, must_not_run)
    assert cli._do_criteria_from_docs(["nowhere.md"]) == 2
    assert "no document at" in capsys.readouterr().err


def test_a_provider_error_is_a_message_not_a_traceback(tmp_path, monkeypatch,
                                                       capsys):
    _doc(tmp_path)
    def no_key(paths, seed=None):
        raise RuntimeError("GEMINI_API_KEY is not set")
    cli = _cli(monkeypatch, tmp_path, no_key)
    assert cli._do_criteria_from_docs(["README.md"]) == 2
    captured = capsys.readouterr()
    assert "GEMINI_API_KEY is not set" in captured.err
    assert captured.out == ""


def test_chatter_during_the_call_stays_out_of_the_yaml(tmp_path, monkeypatch,
                                                       capsys):
    """stdout is meant to be pasted, so a slow-model note must not land in it."""
    _doc(tmp_path)
    def chatty(paths, seed=None):
        print("  [test_system] that call took 95s")
        return ([{"criterion": "the default format is simple",
                  "source": "``simple`` is the default format."}], [], [])
    cli = _cli(monkeypatch, tmp_path, chatty)
    assert cli._do_criteria_from_docs(["README.md"]) == 0
    captured = capsys.readouterr()
    assert "that call took" not in captured.out
    assert "that call took" in captured.err
    assert yaml.safe_load(captured.out)["acceptance_criteria"] == [
        "the default format is simple"]


# ------------------------------------------------- the second audit, 10-10 --

WRAPPED = ("The parser will never\nraise on empty input or on whitespace.\n\n"
           "The following is no longer true: the default timeout is 30 "
           "seconds.\n")


@pytest.mark.parametrize("quote", [
    "raise on empty input or on whitespace.",   # a wrapped line, minus "never"
    "the default timeout is 30 seconds.",       # after a colon
    "The parser will never",                    # stops mid-sentence
])
def test_a_line_break_or_a_colon_is_not_a_sentence_edge(quote):
    assert cfd._as_quoted(quote, [WRAPPED]) is None


def test_a_wrapped_sentence_quoted_whole_is_accepted():
    whole = "The parser will never raise on empty input or on whitespace."
    assert cfd._as_quoted(whole, [WRAPPED]) == whole


def test_a_short_code_line_and_its_output_are_accepted():
    doc = "Example:\n\n```\n>>> add(1, 2)\n3\n>>> add(-1)\nTypeError\n```\n"
    assert cfd._as_quoted(">>> add(1, 2)", [doc]) == ">>> add(1, 2)"
    assert cfd._as_quoted(">>> add(-1)\nTypeError", [doc])
    assert cfd._as_quoted("add", [doc]) is None, "a fragment of a code line"


def test_a_table_row_and_a_cell_are_accepted():
    doc = ("| option | default |\n|---|---|\n"
           "| width | 80 columns unless set otherwise |\n")
    assert cfd._as_quoted("80 columns unless set otherwise", [doc])
    # The row exactly as written, which is what the prompt asks for. An
    # earlier version refused it and accepted a pipe-free join instead,
    # which appears nowhere in the document.
    row = "| width | 80 columns unless set otherwise |"
    assert cfd._as_quoted(row, [doc]) == row
    assert cfd._as_quoted("width 80 columns unless set otherwise", [doc]) is None
    csv_doc = (".. csv-table:: Requirements\n   :header: id, text, kind\n\n"
               """   ' PEP_257_2','Use r\"\"\"raw triple double quotes\"\"\" if you use backslashes.',' Convention'\n""")
    assert cfd._as_quoted(
        'Use r"""raw triple double quotes""" if you use backslashes.',
        [csv_doc])


@pytest.mark.parametrize("doc, quote", [
    # An indented directive body is prose, not a literal block.
    (".. note::\n\n    When the option is not given, Click does not\n"
     "    prompt for a value and the default is used.\n",
     "prompt for a value and the default is used."),
    # RST `#.` items are list items, not headings.
    ("#. The parser does not\n   treat empty strings as missing values.\n",
     "treat empty strings as missing values."),
    # Two pipes in a code span do not make a table row.
    ("The parser accepts `a|b|c` and does not\nraise on empty input.\n",
     "raise on empty input."),
    # A quoted, comma-holding line outside a csv-table is ordinary prose.
    ("The reader does not count\n\"NA\", \"null\" and empty cells as missing values.\n",
     "\"NA\", \"null\" and empty cells as missing values."),
    # A full stop in an abbreviation is not a sentence end.
    ("Unless --strict is set (see Sec. 3.) the parser ignores unknown keys.\n",
     "the parser ignores unknown keys."),
    # A comment wrapped across two lines of code.
    ("```\n# The parser does not\n# raise on empty input.\nparse('')\n```\n",
     "raise on empty input."),
    # The first line of a grid-table cell that continues below.
    ("+---------+------------------------------+\n"
     "| strict  | Unknown options raise errors |\n"
     "|         | only when this flag is given.|\n"
     "+---------+------------------------------+\n",
     "Unknown options raise errors"),
])
def test_a_fragment_that_drops_a_condition_is_refused(doc, quote):
    assert cfd._as_quoted(quote, [doc]) is None


@pytest.mark.parametrize("doc, quote", [
    (".. note::\n\n    When the option is not given, Click does not\n"
     "    prompt for a value and the default is used.\n",
     "When the option is not given, Click does not prompt for a value and "
     "the default is used."),
    (".. code-block:: text\n\nExample::\n\n    $ python hello.py --count=3\n",
     "$ python hello.py --count=3"),
    (":param count: Number of greetings to print before exiting.\n",
     "Number of greetings to print before exiting."),
    ("**Fast.** The first pass consumes it entirely.\n",
     "The first pass consumes it entirely."),
    ("> [!WARNING]\n> Passing a negative width raises ValueError.\n",
     "Passing a negative width raises ValueError."),
    ('<p align="center">\nMissing values are shown as an empty string.\n</p>\n',
     "Missing values are shown as an empty string."),
    ("+---------+------------------------------+\n"
     "| strict  | Unknown options raise errors |\n"
     "|         | only when this flag is given.|\n"
     "+---------+------------------------------+\n",
     "Unknown options raise errors only when this flag is given."),
])
def test_an_honest_quote_in_common_markup_is_accepted(doc, quote):
    assert cfd._as_quoted(quote, [doc]) == quote


def test_a_windows_path_holding_backslash_r_is_restored():
    doc = r"Reports are written to C:\reports\daily.csv by default." + "\n"
    decoded = "Reports are written to C:\reports\\daily.csv by default."
    assert cfd._as_quoted(decoded, [doc]) == doc.strip()


def test_control_characters_never_make_the_yaml_invalid():
    text = cfd.render(["a.md"],
                      [{"criterion": "red \x1b[31m or \x7f here",
                        "source": "a \x1b[0m b"}],
                      [{"sentence": "x", "kind": "ambiguous_claim",
                        "why": "esc \x1b"}], [])
    assert yaml.safe_load(text)["acceptance_criteria"]


def test_a_criterion_that_looks_like_a_mapping_stays_a_string():
    """Plain YAML would read `key: value # x` as a mapping and a comment."""
    text = cfd.render(["a.md"], [{"criterion": "key: value # x",
                                  "source": "s"}], [], [])
    assert yaml.safe_load(text)["acceptance_criteria"] == ["key: value # x"]


def test_a_restated_empty_example_does_not_replace_the_real_reply():
    reply = ('Format: {"criteria": []}\n\n'
             '{"criteria": [{"criterion": "ok", "source": "s"}]}')
    assert cfd._loads(reply)["criteria"][0]["criterion"] == "ok"


def test_a_truncated_reply_with_a_stray_backslash_keeps_its_criteria():
    """The repair has to run before the salvage, or this item is lost."""
    reply = (r'{"criteria": [{"criterion": "a \d b", "source": "s"},'
             r' {"criterion": "cut off')
    kept = cfd._loads(reply)["criteria"]
    assert [k["criterion"] for k in kept] == [r"a \d b"]


def test_a_lost_criterion_is_counted_rather_than_vanishing(tmp_path,
                                                           monkeypatch):
    _stub(monkeypatch, '{"criteria": [{"criterion": "x", "source": "y"}, '
                       '{"criterion": "z", "source": "C:\\out\\"}]}')
    _, _, unquoted = cfd.extract([_doc(tmp_path)])
    assert any("could not be parsed" in u["criterion"] for u in unquoted)


def test_the_update_notice_cannot_reach_the_yaml(tmp_path, monkeypatch,
                                                 capsys):
    import sys as _sys
    from qikly import cli
    _doc(tmp_path)
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setattr(_sys, "argv",
                        ["qikly", "--criteria-from-docs", "README.md"])
    monkeypatch.setattr("qikly.criteria_from_docs.extract",
                        lambda paths, seed=None: ([], [], []))
    monkeypatch.setattr("qikly.version_check.check_for_update",
                        lambda *a, **k: print("qikly 99.0 is available"))
    cli.main()
    assert "available" not in capsys.readouterr().out


def test_a_directory_is_named_as_one(tmp_path, monkeypatch, capsys):
    cli = _cli(monkeypatch, tmp_path, lambda paths, seed=None: ([], [], []))
    assert cli._do_criteria_from_docs(["."]) == 2
    assert "is a directory" in capsys.readouterr().err


def test_an_unexpanded_glob_is_expanded(tmp_path, monkeypatch, capsys):
    _doc(tmp_path, name="a.md")
    _doc(tmp_path, name="b.md")
    seen = []
    cli = _cli(monkeypatch, tmp_path,
               lambda paths, seed=None: seen.extend(paths) or ([], [], []))
    assert cli._do_criteria_from_docs(["*.md"]) == 0
    assert sorted(os.path.basename(p) for p in seen) == ["a.md", "b.md"]


def test_source_code_is_flagged_and_the_report_does_not_deny_it(
        tmp_path, monkeypatch, capsys):
    _doc(tmp_path, text="def f():\n    return 1\n", name="impl.py")
    cli = _cli(monkeypatch, tmp_path, lambda paths, seed=None: ([], [], []))
    assert cli._do_criteria_from_docs(["impl.py"]) == 0
    captured = capsys.readouterr()
    assert "looks like source code" in captured.err
    assert "Nothing here was derived" not in captured.out


def test_a_misattached_flag_is_still_refused(tmp_path, monkeypatch, capsys):
    """
    Dispatching this command early, to keep the update notice out of its
    output, also skipped the guard that refuses a flag given to the wrong
    command. `--score-mutants` was then accepted and ignored.
    """
    import sys as _sys
    from qikly import cli
    _doc(tmp_path)
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.setattr(_sys, "argv", ["qikly", "--criteria-from-docs",
                                       "README.md", "--score-mutants", "5"])
    monkeypatch.setattr("qikly.criteria_from_docs.extract",
                        lambda paths, seed=None: ([], [], []))
    assert cli.main() == 2
    assert "--score-mutants goes with" in capsys.readouterr().err


def test_a_code_block_directive_body_is_code():
    doc = (".. code-block:: python\n   :linenos:\n\n"
           "   result = tabulate(rows, tablefmt=\"plain\")\n   print(result)\n")
    assert cfd._as_quoted("print(result)", [doc]) == "print(result)"


def test_a_restated_example_cannot_hide_a_truncated_reply(tmp_path,
                                                          monkeypatch):
    """
    A restated format example always parses, so the parser handed it back as
    the reply and the real, truncated one after it vanished unreported.
    """
    _stub(monkeypatch,
          'Format: {"criteria": [{"criterion": "<one>", "source": "x"}]}\n\n'
          '{"criteria": [{"criterion": "the default format is simple", '
          '"source": "``simple`` is the default format."}, '
          '{"criterion": "cut off')
    kept, _, unquoted = cfd.extract([_doc(tmp_path)])
    assert [k["criterion"] for k in kept] == ["the default format is simple"]
    assert any("1 more" in u["criterion"] for u in unquoted)


def test_a_restated_example_is_not_reported_as_a_loss(tmp_path, monkeypatch):
    _stub(monkeypatch,
          'The format is {"criteria": [{"criterion": "...", "source": "..."}]}'
          '\n\n{"criteria": [{"criterion": "the default format is simple", '
          '"source": "``simple`` is the default format."}]}')
    kept, _, unquoted = cfd.extract([_doc(tmp_path)])
    assert len(kept) == 1
    assert not any("could not be parsed" in u["criterion"] for u in unquoted)
