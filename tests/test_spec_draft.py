"""
The spec agent: the first draft of a task's answers, written from the
documentation without the code.

What these pin, in order of how much a failure would cost:

- no function body ever reaches the spec agent's prompt, and neither does the
  code a question quotes: a draft read off the code would agree with it by
  construction and find nothing;
- a criterion that claims to quote the documentation and does not is dropped;
- the draft lands in the task file with a note saying where each criterion
  came from, and the drafted criteria are still withheld from the coding agent;
- without a key, or with drafting switched off, --scaffold writes TODOs as it
  did before.
"""
import json
import os
import shutil

import pytest

from qikly import cli, spec_draft

PRICING = ('def apply_discount(price, rate):\n'
           '    """Apply a percentage discount."""\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n'
           '\n'
           '\n'
           'def label(code):\n'
           '    if code.strip().lower() == "vip":\n'
           '        return "gold"\n'
           '    return "standard"\n')
TESTS = ('from pricing import apply_discount, label\n\n\n'
         'def test_discount():\n    assert apply_discount(100, 10) == 90.0\n\n\n'
         'def test_label():\n    assert label("vip") == "gold"\n')
README = ("# Pricing\n\nA rate of 0 leaves the price as it is. A rate of 100 or more "
          "is rejected with ValueError.\n")
TASK = os.path.join("inputs_private", "config", "tasks", "PRICING_VERIFY.yaml")
BODY_LINES = ["rate < 0 or rate > 100", "round(price * (1 - rate / 100), 2)",
              'raise ValueError("rate out of range")', 'code.strip().lower() == "vip"']


@pytest.fixture(scope="module")
def _scored_once(tmp_path_factory):
    """Step 1 run once for the whole file: about 10 seconds a run, and every
    test below starts from the same scored project. Each test gets its own
    copy, so nothing one test writes reaches another."""
    root = tmp_path_factory.mktemp("scored")
    (root / "pricing.py").write_text(PRICING, encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_pricing.py").write_text(TESTS, encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "INVOKED_FROM", str(root))
        mp.chdir(root)
        mp.syspath_prepend(str(root))
        assert cli._do_score_suite(None, None, None, code="pricing.py", tests=None) == 0
    return root


@pytest.fixture
def scored(_scored_once, tmp_path, monkeypatch):
    shutil.copytree(_scored_once, tmp_path, dirs_exist_ok=True)
    # Step 1 saves absolute paths: point the copy at its own folder, as a
    # score taken here would have.
    for saved in tmp_path.rglob("*.json"):
        text = saved.read_text(encoding="utf-8")
        saved.write_text(text.replace(json.dumps(str(_scored_once))[1:-1],
                                      json.dumps(str(tmp_path))[1:-1]), encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def _drafting(monkeypatch, reply):
    """Drafting switched on, with the model call answered by `reply(prompt)`."""
    from qikly.agent_api.providers import router
    monkeypatch.delenv("QIKLY_NO_DRAFT", raising=False)
    monkeypatch.setattr(router, "validate_config", lambda: "fake")
    seen = []

    def call(mode, prompt, seed=None):
        assert mode == "spec_draft"
        seen.append(prompt)
        return reply(prompt)
    from qikly.agent_api import call_llm
    monkeypatch.setattr(call_llm, "call_llm", call)
    return seen


def _answers(prompt):
    count = sum(1 for line in prompt.split("THE QUESTIONS")[1].splitlines()
                if line[:1].isdigit())
    answers = [{"question": n, "criterion": f"apply_discount(100, {n}) returns 1.0",
                "source": "purpose", "quote": "", "check": True}
               for n in range(1, count + 1)]
    answers[0] = {"question": 1, "criterion": "apply_discount(100, 0) returns 100.0",
                  "source": "docs", "quote": "A rate of 0 leaves the price as it is.",
                  "check": False}
    return json.dumps({"requirements": "Pricing helpers; a rate is a percentage.",
                       "answers": answers})


def test_the_prompt_never_holds_the_code(scored, monkeypatch):
    seen = _drafting(monkeypatch, _answers)
    assert cli._do_scaffold("pricing.py", None) == 0
    (prompt,) = seen
    for line in BODY_LINES:
        assert line not in prompt, line
    # What it may read: the README, the signatures and docstrings.
    assert "A rate of 100 or more is rejected" in prompt
    assert "def apply_discount(price, rate):" in prompt
    assert "Apply a percentage discount." in prompt


def test_a_question_reaches_the_agent_without_the_code_it_quotes():
    q = {"function": "apply_discount",
         "question": "Your tests pass whether this is `rate > 100` or `rate >= 100`, so "
                     "nothing checks the boundary itself. What should happen at exactly `100`?"}
    assert spec_draft.neutral_question(q) == ("In apply_discount: What should happen at "
                                              "exactly 100?")
    q = {"function": "label", "question": "Your tests pass without `.strip()` here. Should "
                                          "two inputs that differ only by spaces be treated the same?"}
    assert "strip" not in spec_draft.neutral_question(q)


def test_the_draft_lands_with_where_each_criterion_came_from(scored, monkeypatch):
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert '- "Pricing helpers; a rate is a percentage."' in text
    assert "TODO: MODIFY THIS" not in text
    assert ('#? Answer below drafted by qikly from your README, docs or docstrings: '
            '"A rate of 0 leaves the price as it is.". Keep it, or change it.') in text
    assert '- "apply_discount(100, 0) returns 100.0"' in text
    assert "#? CHECK: your docs don't say. The answer below is qikly's guess" in text
    criteria_part = text[text.index("acceptance_criteria:"):]
    assert '- "TODO: ' not in criteria_part


def test_an_invented_quote_is_dropped(scored, monkeypatch):
    def reply(prompt):
        data = json.loads(_answers(prompt))
        data["answers"][0]["quote"] = "A rate of 0 is a free gift."
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert "free gift" not in text
    assert '- "apply_discount(100, 0) returns 100.0"' not in text
    assert '- "TODO: ' in text[text.index("acceptance_criteria:"):]


def test_drafted_criteria_never_reach_the_coding_agent(scored, monkeypatch):
    from qikly.agent_api.agent_interface import (_read_task, read_acceptance_criteria,
                                                 without_acceptance_criteria)
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    criteria = read_acceptance_criteria("PRICING_VERIFY")
    assert "apply_discount(100, 0) returns 100.0" in criteria
    handed_over = without_acceptance_criteria(_read_task("PRICING_VERIFY"))
    for criterion in criteria:
        assert criterion not in handed_over
    assert "#?" not in handed_over


def test_without_a_key_or_with_drafting_off_the_answers_are_todos(scored, monkeypatch, capsys):
    # The test suite runs with QIKLY_NO_DRAFT=1 and no key.
    cli._do_scaffold("pricing.py", None)
    criteria_part = (scored / TASK).read_text(encoding="utf-8").split("acceptance_criteria:")[1]
    assert '- "TODO: ' in criteria_part
    os.remove(scored / TASK)
    monkeypatch.delenv("QIKLY_NO_DRAFT", raising=False)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    assert "No API key is set" in capsys.readouterr().out


def test_a_failed_draft_leaves_the_todos(scored, monkeypatch, capsys):
    _drafting(monkeypatch, lambda prompt: "not json")
    assert cli._do_scaffold("pricing.py", None) == 0
    assert "could not be read" in capsys.readouterr().out
    assert '- "TODO: ' in (scored / TASK).read_text(encoding="utf-8")


def test_the_interface_shows_signatures_and_docstrings_only():
    text = spec_draft.interface_text(PRICING)
    assert "def apply_discount(price, rate):" in text
    assert "def label(code):" in text
    for line in BODY_LINES:
        assert line not in text


def test_take_tests_says_who_wrote_each_criterion(scored, monkeypatch):
    from qikly import take_tests
    _drafting(monkeypatch, _answers)
    cli._do_scaffold("pricing.py", None)
    criteria = take_tests.criteria_with_origin(str(scored), "PRICING_VERIFY")
    assert criteria[0] == ("apply_discount(100, 0) returns 100.0", "docs")
    assert all(origin == "check" for _, origin in criteria[1:])


def test_the_draft_is_shown_on_screen_check_first(scored, monkeypatch, capsys):
    _drafting(monkeypatch, _answers)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    out = capsys.readouterr().out
    draft = out[out.index("The draft:"):]
    assert draft.index("CHECK  ") < draft.index("docs   apply_discount(100, 0) returns 100.0")
    assert "To run it as it is:  qikly --tasks pricing.py" in out
    assert "To change an answer, edit:" in out


def test_a_dropped_quote_is_counted_and_said(scored, monkeypatch, capsys):
    def reply(prompt):
        data = json.loads(_answers(prompt))
        data["answers"][0]["quote"] = "A rate of 0 is a free gift."
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    assert "1 left as TODO because the quote given for it is not in your documentation" \
        in capsys.readouterr().out


def test_stopping_the_draft_still_writes_the_file(scored, monkeypatch, capsys):
    def reply(prompt):
        raise KeyboardInterrupt
    _drafting(monkeypatch, reply)
    assert cli._do_scaffold("pricing.py", None) == 0
    assert "Drafting stopped" in capsys.readouterr().out
    assert '- "TODO: ' in (scored / TASK).read_text(encoding="utf-8")


def test_a_suite_failing_on_its_own_is_said_to_be_the_setup_not_qikly():
    from qikly import mutation_score as ms
    target = ms.Target("x", [], ["tests"], ".")
    lines = ms.setup_advice(["E   ModuleNotFoundError: No module named 'click'"], target)
    text = "\n".join(lines)
    assert "a problem in your project's environment (not a problem with qikly)" in text
    assert "-m pip install click" in text
    assert "python -m pytest tests" in text


def test_with_no_readme_and_no_docstrings_nothing_is_drafted(scored, monkeypatch, capsys):
    """With names alone, every drafted answer was a guess, label('VIP') raising."""
    os.remove(scored / "README.md")
    (scored / "pricing.py").write_text(PRICING.replace('    """Apply a percentage discount."""\n', ""),
                                       encoding="utf-8")
    # Scored again: the saved questions name lines the edit moved.
    assert cli._do_score_suite(None, None, None, code="pricing.py", tests=None) == 0
    seen = _drafting(monkeypatch, _answers)
    capsys.readouterr()
    cli._do_scaffold("pricing.py", None)
    assert not seen, "a model was called with nothing to draft from"
    assert "no README and no docstrings" in capsys.readouterr().out


# ------------------------------------------- found on the sweep, 2026-10-22 --

SLUGIFY = "def slugify(text, max_length=0):\n    pass\n\n\ndef smart_truncate(text, max_length=0):\n    pass\n"


def test_an_answer_calling_another_function_than_its_quote_is_marked_check():
    """slugify: the README's slugify() example given to smart_truncate()."""
    names = spec_draft.interface_names(SLUGIFY)
    quote = "assert slugify('one two three four', max_length=12) == 'one-two-four'"
    why = spec_draft.other_function(
        quote, "smart_truncate('one two three four', max_length=12) returns 'one-two-four'", names)
    assert why and "slugify()" in why and "smart_truncate()" in why
    same = "slugify('one two three four', max_length=12) returns 'one-two-four'"
    assert spec_draft.other_function(quote, same, names) is None


def test_an_answer_changing_its_examples_arguments_is_marked_check():
    """price-parser's "12,34" became "12€34"; tabulate's "colon_grid" became "plain"."""
    names = {"parse_number", "tabulate"}
    why = spec_draft.other_function('>>> parse_number("12,34")',
                                    'parse_number("12€34") returns Decimal("12.34")', names)
    assert why and "other arguments" in why
    why = spec_draft.other_function(
        'tabulate([["spam", 41.9999]], ["strings"], "colon_grid")',
        'tabulate([["spam", 41.9999]], ["strings"], "plain") returns "..."', names)
    assert why and "tabulate()" in why
    assert spec_draft.other_function('parse_number( "12,34" )',
                                     'parse_number("12,34") returns Decimal("12.34")', names) is None


def test_a_rule_written_in_prose_is_not_an_example_to_match():
    names = {"apply_discount"}
    assert spec_draft.other_function("a rate of 100 or more is rejected with ValueError",
                                     "apply_discount(100, 100) raises ValueError", names) is None


def test_a_drafted_criterion_keeps_its_spaces():
    """tabulate aligns columns with runs of spaces; squeezing them changed the output."""
    text = spec_draft.criterion_text("tabulate(t) returns 'strings      numbers\nspam   1'\n")
    assert text == "tabulate(t) returns 'strings      numbers\\nspam   1'"
    drafted = {"requirements": None, "dropped": 0, "answers": {1: {
        "criterion": text, "source": "docs", "quote": "q", "check": False, "why": None}}}
    out, _, _ = spec_draft.apply('acceptance_criteria:\n  - "TODO: your answer"\n', drafted)
    import yaml
    assert yaml.safe_load(out)["acceptance_criteria"] == [text]


def test_a_call_to_something_outside_the_module_is_not_a_mismatch():
    names = spec_draft.interface_names(SLUGIFY)
    assert spec_draft.other_function("Decimal('1.0') is accepted",
                                     "slugify('x') returns 'x'", names) is None


def test_the_mismatch_is_written_beside_the_answer():
    drafted = {"requirements": None, "dropped": 0, "answers": {1: {
        "criterion": "label('VIP') returns 'gold'", "source": "docs",
        "quote": "apply_discount(100, 100) raises", "check": True,
        "why": "the quote's example calls apply_discount(), and this answer calls label() instead"}}}
    task = "acceptance_criteria:\n  - \"TODO: your answer to the question above\"\n"
    out, done, check = spec_draft.apply(task, drafted)
    lines = out.splitlines()
    assert done == 1 and check == 1
    at = next(i for i, l in enumerate(lines) if "label('VIP')" in l)
    assert lines[at - 1].startswith("  #? CHECK: the quote's example calls apply_discount()")


def test_a_readme_that_is_a_symlink_git_could_not_make_is_followed(tmp_path):
    """tenacity: README.rst holds only 'doc/source/index.rst' on Windows."""
    (tmp_path / "doc" / "source").mkdir(parents=True)
    (tmp_path / "doc" / "source" / "index.rst").write_text(
        "Tenacity retries a call until it succeeds.\n", encoding="utf-8")
    (tmp_path / "README.rst").write_text("doc/source/index.rst", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    module = tmp_path / "pkg" / "retry.py"
    module.write_text("def retry():\n    pass\n", encoding="utf-8")
    assert "retries a call" in spec_draft.readme_text(str(module), str(tmp_path))


def test_a_short_readme_that_names_no_file_is_kept_as_written(tmp_path):
    (tmp_path / "README.md").write_text("Small tools.", encoding="utf-8")
    module = tmp_path / "tools.py"
    module.write_text("def f():\n    pass\n", encoding="utf-8")
    assert spec_draft.readme_text(str(module), str(tmp_path)) == "Small tools."


def test_a_function_reexported_through_all_counts_as_the_modules():
    """python-slugify's smart_truncate lives in _legacy.py and is exported here."""
    source = ("from ._legacy import smart_truncate\n__all__ = ['slugify', 'smart_truncate']\n\n"
              "def slugify(text):\n    pass\n")
    names = spec_draft.interface_names(source)
    assert {"slugify", "smart_truncate"} <= names
    assert spec_draft.other_function("slugify('a b') == 'a-b'", "smart_truncate('a b') returns 'a-b'", names)


def test_a_question_about_a_default_names_its_parameter():
    """iniconfig: "this False flipped" said nothing of which parameter."""
    source = ("class IniConfig:\n"
              "    @classmethod\n"
              "    def parse(\n"
              "        cls,\n"
              "        path,\n"
              "        strip_section_whitespace: bool = False,\n"
              "    ):\n"
              "        if path is not None and strip_section_whitespace:\n"
              "            return 1\n")
    default = {"function": "parse", "line": 6, "code": "strip_section_whitespace: bool = False,",
               "question": "Your tests pass with this `False` flipped. What behaviour depends on it?"}
    body = {"function": "parse", "line": 8, "code": "if path is not None and strip_section_whitespace:",
            "question": "Your tests pass whether this uses `and` or `or`. Which is right?"}
    named = spec_draft.with_parameters([default, body], source)
    assert named[0]["parameter"] == "strip_section_whitespace"
    assert "parameter" not in named[1], "a line in the body is not a default"
    assert "the parameter strip_section_whitespace" in spec_draft.neutral_question(named[0])
    assert "parameter" not in default, "the saved questions are not changed"


def test_a_public_alias_carries_its_private_definitions_docs():
    # msgspec-ext documents _EmailStr and exports it as EmailStr; the spec
    # agent saw neither the name nor the docstring.
    src = ('class _EmailStr(str):\n    """An email address, validated on creation."""\n\n'
           'EmailStr = _EmailStr\n')
    assert "An email address, validated on creation." in spec_draft.public_docstrings(src)
    assert "class EmailStr:" in spec_draft.interface_text(src)


def test_the_docs_folder_pages_naming_the_module_are_read(tmp_path):
    """jambo explains clear_ref_cache(None) only in docs/source/usage.ref_cache.rst.
    A page naming the module's functions is read, the most mentions first; a
    page naming nothing from it, a source file and a build folder are not."""
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    docs = tmp_path / "docs" / "source"
    docs.mkdir(parents=True)
    (docs / "usage.rst").write_text(
        "apply_discount(100, 100) raises ValueError. apply_discount is strict.\n",
        encoding="utf-8")
    (docs / "labels.md").write_text("label('vip') returns 'gold'.\n", encoding="utf-8")
    (docs / "about.md").write_text("A project about prices.\n", encoding="utf-8")
    (docs / "conf.py").write_text("# apply_discount apply_discount\n", encoding="utf-8")
    (tmp_path / "docs" / "_build").mkdir()
    (tmp_path / "docs" / "_build" / "copy.md").write_text("apply_discount\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "pricing.py"), str(tmp_path))
    assert "--- docs/source/usage.rst ---" in text
    assert "--- docs/source/labels.md ---" in text
    assert text.index("usage.rst") < text.index("labels.md")
    assert "A project about prices." not in text
    assert "conf.py" not in text and "_build" not in text


def test_top_level_doc_files_naming_the_module_are_read(tmp_path):
    """ydnatl documents pop(index=-1), "Remove last child", only in
    LLM_GUIDE.md at the project's top level; the reader looked in docs/ alone,
    so the spec agent never saw it. CLAUDE.md and AGENTS.md are read too. The
    README is read on its own, so it is not repeated here; licences,
    contribution rules and dependency lists are not about behaviour."""
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "LLM_GUIDE.md").write_text(
        "apply_discount(100, 100) raises ValueError.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("apply_discount rounds to cents.\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("label('vip') returns 'gold'.\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("README_MARKER apply_discount(1, 2)\n", encoding="utf-8")
    for skipped in ("CONTRIBUTING.md", "LICENSE.txt", "SECURITY.md", "requirements-dev.txt",
                    "CODE_OF_CONDUCT.md"):
        (tmp_path / skipped).write_text("SKIP_MARKER apply_discount(1, 2)\n", encoding="utf-8")
    (tmp_path / "notes.py").write_text("# apply_discount apply_discount\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "pricing.py"), str(tmp_path))
    assert "--- LLM_GUIDE.md ---" in text and "raises ValueError" in text
    assert "--- CLAUDE.md ---" in text and "--- AGENTS.md ---" in text
    assert "README_MARKER" not in text and "SKIP_MARKER" not in text
    assert "notes.py" not in text


def test_a_top_level_doc_holding_the_modules_code_is_filtered(tmp_path):
    """A CLAUDE.md often pastes the code it describes. The same filter as for
    docs/ pages applies: the body never reaches the spec agent."""
    (tmp_path / "mod.py").write_text(
        'def load(path):\n    """Load a file."""\n'
        '    return open(path).read() + "SECRET_BODY_MARKER"\n', encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(
        "`load(path)` raises OSError when the path is missing.\n\n"
        "```python\ndef load(path):\n"
        '    return open(path).read() + "SECRET_BODY_MARKER"\n```\n', encoding="utf-8")
    (tmp_path / "GUIDE.md").write_text((tmp_path / "mod.py").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    # A diff or a test log at the top level: its code lines carry a "+" or ">"
    # the docs filter does not always see past, so no .txt there is read.
    (tmp_path / "changes.txt").write_text(
        "load(path) changed:\n+    return open(path).read() + 'SECRET_BODY_MARKER'\n",
        encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "mod.py"), str(tmp_path))
    assert "SECRET_BODY_MARKER" not in text
    assert "raises OSError when the path is missing" in text
    assert "GUIDE.md" not in text and "changes.txt" not in text


def test_top_level_and_docs_folder_pages_share_one_ranking(tmp_path):
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "few.md").write_text("apply_discount(1, 2) once.\n", encoding="utf-8")
    (tmp_path / "GUIDE.md").write_text(
        "apply_discount(1, 2) and apply_discount(3, 4) and apply_discount(5, 6).\n",
        encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "pricing.py"), str(tmp_path))
    assert text.index("GUIDE.md") < text.index("docs/few.md")


def test_a_quote_from_the_docs_folder_is_kept(scored, monkeypatch):
    """Before the docs folder was read, a quote from it failed the check that a
    quote is really in the documentation, and the answer was dropped."""
    (scored / "docs").mkdir()
    (scored / "docs" / "rates.md").write_text(
        "apply_discount rejects a rate of exactly 100 with ValueError.\n", encoding="utf-8")

    def reply(prompt):
        assert "rejects a rate of exactly 100" in prompt
        data = json.loads(_answers(prompt))
        data["answers"][0] = {"question": 1, "criterion": "apply_discount(100, 100) raises ValueError",
                              "source": "docs",
                              "quote": "apply_discount rejects a rate of exactly 100 with ValueError.",
                              "check": False}
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert '- "apply_discount(100, 100) raises ValueError"' in text


def test_a_criterion_naming_no_expected_value_is_marked_check():
    """jambo's one drafted answer, "clear_ref_cache() runs without error", gave a
    test that passed whatever the call did. Over 293 criteria in the bundled
    and private tasks, this is the only one the check flags."""
    for weak in ("SchemaConverter().clear_ref_cache() runs without error",
                 "parse('x') does not raise", "the call succeeds",
                 "read_csv works on an empty file"):
        assert spec_draft.weak_criterion(weak), weak
    for fine in ("apply_discount(100, 100) raises ValueError",
                 "apply_discount(100, 0) returns 100.0", "to_kelvin(0) is 273.15",
                 "clear_ref_cache(None) runs without error and get_cached_ref('Person') "
                 "returns None afterwards"):
        assert spec_draft.weak_criterion(fine) is None, fine


def test_the_weak_criterion_note_is_written_beside_the_answer(scored, monkeypatch):
    def reply(prompt):
        data = json.loads(_answers(prompt))
        data["answers"][0]["criterion"] = "apply_discount(100, 0) runs without error"
        return json.dumps(data)
    _drafting(monkeypatch, reply)
    cli._do_scaffold("pricing.py", None)
    text = (scored / TASK).read_text(encoding="utf-8")
    assert "#? CHECK: it names no expected value" in text


def test_a_function_body_in_a_docs_page_never_reaches_the_spec_agent(tmp_path):
    """The promise the whole design rests on. A docs page can embed the
    module's code (a fenced block, an rst literal block) or be a copy of it
    saved as .txt; found by the audit of the docs-folder reader."""
    (tmp_path / "mod.py").write_text(
        'def load(path):\n    """Load a file."""\n'
        '    return open(path).read() + "SECRET_BODY_MARKER"\n', encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "internals.md").write_text(
        "How `load` works:\n\n```python\ndef load(path):\n"
        '    return open(path).read() + "SECRET_BODY_MARKER"\n```\n', encoding="utf-8")
    (docs / "usage.rst").write_text(
        "Call ``load(path)``. ``load`` raises OSError when the path is missing.\n\n"
        "Example::\n\n    def load(path):\n"
        '        return open(path).read() + "SECRET_BODY_MARKER"\n\n'
        "After it, load(path) returns the text.\n", encoding="utf-8")
    (docs / "copy.txt").write_text((tmp_path / "mod.py").read_text(encoding="utf-8"),
                                   encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "mod.py"), str(tmp_path))
    assert "SECRET_BODY_MARKER" not in text
    assert "copy.txt" not in text
    assert "raises OSError when the path is missing" in text
    assert "After it, load(path) returns the text." in text


def test_the_most_relevant_page_is_trimmed_rather_than_dropped(tmp_path):
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text("apply_discount(1, 2) is documented. " * 2000,
                                              encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "pricing.py"), str(tmp_path))
    assert text.startswith("--- docs/api.md ---")
    assert len(text) <= spec_draft.DOCS_LIMIT


def test_a_common_short_name_in_prose_does_not_make_a_page_relevant(tmp_path):
    (tmp_path / "mod.py").write_text('def run():\n    """Run it."""\n', encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "start.md").write_text("Get started: run the installer.\n",
                                                encoding="utf-8")
    (tmp_path / "docs" / "api.md").write_text("Call `run()` to start.\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "mod.py"), str(tmp_path))
    assert "api.md" in text and "start.md" not in text


def test_the_audits_weak_criterion_cases():
    for weak in ("f(x) works when x is 0", "runs without error when the list has one item",
                 "f() runs without error for inputs < 0", "never fails on a valid row"):
        assert spec_draft.weak_criterion(weak), weak
    for fine in ("the worker completes 5 jobs", "succeeds with output 3",
                 "the call succeeds with status 200",
                 "the merge succeeds, returning the merged dict",
                 "save() completes and the file exists afterwards"):
        assert spec_draft.weak_criterion(fine) is None, fine


def test_the_reaudits_weak_criterion_cases():
    """A function named like a result verb is not a result, and a condition
    ends where the sentence goes on to one."""
    for weak in ("add(1, 2) runs without error", "update(cfg) works", "log(msg) never raises",
                 "store.save() succeeds", "f(g(x)) runs without error"):
        assert spec_draft.weak_criterion(weak), weak
    for fine in ("succeeds when the server is up and returns the body",
                 "succeeds, given a valid url, returning the body",
                 "apply_discount(100, 0) returns 100"):
        assert spec_draft.weak_criterion(fine) is None, fine


def _module_with_body(tmp_path):
    (tmp_path / "shop.py").write_text(
        'def apply_discount(price, rate):\n    """Price after a discount of rate percent."""\n'
        '    if rate >= 100:\n        raise ValueError("rate too high")\n'
        "    return round(price * (1 - rate / 100), 2)\n", encoding="utf-8")
    return str(tmp_path / "shop.py")


def test_a_body_in_another_layout_never_reaches_the_spec_agent(tmp_path):
    """Found by the re-audit: a doctest, a line with a comment, a one-line
    <pre> and a reformatted line all carried the body past an exact match."""
    module = _module_with_body(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "usage.md").write_text(
        "Use apply_discount(200, 50).\n\nThe price is a number of euros.\n"
        "The rate is a percentage.\nThe result has two decimal places.\n"
        "A rate of 100 or more is refused.\n\n>>> if rate >= 100:\n"
        '...     raise ValueError("rate too high")\n\n'
        "    return round(price * (1 - rate / 100), 2)  # the price\n\n"
        '<pre>if rate>=100: raise ValueError("rate too high")</pre>\n', encoding="utf-8")
    text = spec_draft.all_docs(module, str(tmp_path))
    assert "Use apply_discount(200, 50)." in text
    for body in ('ValueError("rate too high")', "rate >= 100", "rate>=100", "round(price"):
        assert body not in text, body


def test_a_body_in_the_readme_never_reaches_the_spec_agent(tmp_path):
    """Found by the re-audit: the README skipped the code filter."""
    module = _module_with_body(tmp_path)
    (tmp_path / "README.md").write_text(
        "# shop\n\nA rate of 100 or more raises ValueError.\n\n```python\n"
        "def apply_discount(price, rate):\n    if rate >= 100:\n"
        '        raise ValueError("rate too high")\n```\n', encoding="utf-8")
    text = spec_draft.all_docs(module, str(tmp_path))
    assert "A rate of 100 or more raises ValueError." in text
    assert "rate too high" not in text


def test_a_page_restating_a_docstring_is_kept(tmp_path):
    """A docstring is documentation: matching it as code dropped the page."""
    (tmp_path / "api.py").write_text(
        'def apply_discount(price, rate):\n    """Apply a discount.\n\n'
        "    The rate is a percentage between zero and one hundred.\n"
        "    Rates of one hundred or more are refused with ValueError.\n"
        '    The result is rounded to two places.\n    """\n'
        "    return round(price * (100 - rate) / 100, 2)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "apply_discount(price, rate)\n\n"
        "The rate is a percentage between zero and one hundred.\n"
        "Rates of one hundred or more are refused with ValueError.\n"
        "The result is rounded to two places.\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "api.py"), str(tmp_path))
    assert "refused with ValueError" in text


def test_the_body_of_a_sibling_the_module_imports_is_kept_out(tmp_path):
    """A thin wrapper's behaviour lives in the module it delegates to."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "_core.py").write_text(
        "def compute(a, b):\n    total = a * b + 17\n    return total\n", encoding="utf-8")
    (pkg / "api.py").write_text(
        "from ._core import compute\n\n\ndef apply_discount(price, rate):\n"
        "    return compute(price, rate)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "apply_discount(price, rate) applies the rate.\n\nInside: total = a * b + 17\n",
        encoding="utf-8")
    text = spec_draft.docs_text(str(pkg / "api.py"), str(tmp_path))
    assert "applies the rate" in text and "a * b + 17" not in text


_TAX = ('"""Tax helpers.\n\nThese compute the tax on a price,\nwith a rate of twenty percent.\n"""\n\n'
        "# A negative price is treated as zero.\n\n\n"
        'def tax(p):\n    """The price with tax."""\n    if p < 0:\n        return 0\n'
        "    return p * 1.2\n\n\n"
        'def tax_all(prices_list):\n    """Tax every price."""\n'
        "    return [tax(p) for p in prices_list]\n")


def test_a_small_module_saved_as_text_never_reaches_the_spec_agent(tmp_path):
    """Found by the second review: its docstrings and comments outnumbered the
    lines long enough to match, so the copy passed for documentation."""
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "copy.txt").write_text(_TAX, encoding="utf-8")
    assert "p * 1.2" not in spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))


def test_a_readme_example_defining_the_users_own_function_is_kept(tmp_path):
    """Found by the second review: every quickstart handler was dropped."""
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# m\n\n```python\nfrom m import tax_all\n\n\ndef handler(prices):\n"
        "    return tax_all(prices)\n```\n", encoding="utf-8")
    assert "def handler" in spec_draft.all_docs(str(tmp_path / "m.py"), str(tmp_path))


def test_a_signature_list_of_the_modules_functions_is_kept(tmp_path):
    """An API reference lists signatures with `...`: that is documentation."""
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "API of tax:\n\n```python\ndef tax(p: float) -> float: ...\n"
        "def tax_all(prices_list): ...\n```\n", encoding="utf-8")
    assert "def tax_all(prices_list): ..." in spec_draft.docs_text(
        str(tmp_path / "m.py"), str(tmp_path))


def test_prose_and_tables_sharing_a_fragment_with_the_code_are_kept(tmp_path):
    """Found by the second review: a bare `media_id: str` line of an argument
    list, an import or an rst underline in the module removed prose."""
    (tmp_path / "m.py").write_text(
        "from __future__ import annotations\n\n\n"
        "def media_save(media_id: str,\n               folder: str = '.') -> bool:\n"
        "    names = ['TextChannel', 'VoiceChannel',\n"
        "             'StageChannel']\n"
        "    return bool(media_id) and folder_exists(folder)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    page = ("| media_save(media_id: str, folder) | bool | Save media |\n"
            "It returns TextChannel, VoiceChannel or StageChannel.\n"
            "We use from __future__ import annotations everywhere.\n")
    (tmp_path / "docs" / "api.md").write_text(page, encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    for line in page.splitlines():
        assert line in text, line


def test_an_indented_rst_paragraph_starting_with_class_is_kept(tmp_path):
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "usage.rst").write_text(
        "Notes on tax_all(prices).\n\n    class attributes are shared, and tax_all(prices) "
        "returns one price per input.\n", encoding="utf-8")
    assert "returns one price per input" in spec_draft.docs_text(
        str(tmp_path / "m.py"), str(tmp_path))


def test_an_rst_tilde_underline_is_not_a_fence(tmp_path):
    """Found by the third review: a `~~~~` underline opened a Markdown fence
    and a whole style guide went with the block."""
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.rst").write_text(
        "Taxes\n~~~~~\n\nCall tax_all(prices) for a list.\n\nExample::\n\n"
        "    def tax(p):\n        if p < 0:\n            return 0\n        return p * 1.2\n\n"
        "Rounding\n~~~~~~~~\n\ntax_all(prices) never rounds.\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "Call tax_all(prices) for a list." in text and "never rounds" in text
    assert "p * 1.2" not in text


def test_a_fenced_body_of_a_module_function_that_only_calls_is_dropped(tmp_path):
    """Found by the third review: the closing fence broke the parse, and the
    fallback did not see a call as a body."""
    (tmp_path / "m.py").write_text(
        "import threading\n_t = threading.Timer(1, print)\n\n\n"
        "def stop():\n    _t.cancel()\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "Call stop() to stop.\n\n```python\ndef stop():\n    _t.cancel()\n```\n",
        encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "Call stop() to stop." in text and "_t.cancel()" not in text


def test_a_sql_string_in_a_body_stays_code(tmp_path):
    """Found by the third review: a body that is mostly a SQL string leaked."""
    (tmp_path / "m.py").write_text(
        "def build_query(table):\n    return f'''\n        SELECT name, total FROM {table}\n"
        "        WHERE total > 100 AND status = 'open'\n        ORDER BY total DESC\n    '''\n",
        encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "build_query(table) builds the query.\n\n```sql\n"
        "SELECT name, total FROM {table}\nWHERE total > 100 AND status = 'open'\n```\n",
        encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "builds the query" in text and "status = 'open'" not in text


def test_an_api_bullet_repeating_keyword_defaults_is_kept(tmp_path):
    """Found by the third review: `bg_rgb=None,` in a signature took bullets."""
    (tmp_path / "m.py").write_text(
        "def print_rgb(rgb, *values, style=None,\n              bg=None, bg_rgb=None,\n"
        "              sep=' '):\n    text = sep.join(map(str, values))\n"
        "    return paint(text, rgb, style, bg, bg_rgb)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    bullet = "- `print_rgb(rgb, *values, style=None, bg=None, bg_rgb=None, sep=' ')` prints in colour"
    (tmp_path / "docs" / "api.md").write_text(bullet + "\n", encoding="utf-8")
    assert bullet in spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))


def test_prose_after_a_block_nested_in_a_note_is_kept(tmp_path):
    (tmp_path / "m.py").write_text(_TAX, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "usage.rst").write_text(
        ".. note::\n\n    Use it like::\n\n        def tax(p):\n            return p * 1.2\n\n"
        "    After that, tax_all(prices) returns the taxed list.\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "returns the taxed list" in text and "p * 1.2" not in text


def test_plain_assignments_and_code_strings_stay_code_and_a_short_tilde_fence_counts(tmp_path):
    """Found by the fourth review: the keyword-default idiom also exempted
    `rate = DEFAULT_RATE`; a string of code with `# ` comments passed for
    markup; a `~~~` fence after a sentence passed for an rst underline."""
    (tmp_path / "m.py").write_text(
        "DEFAULT_RATE = 0.2\n\n\ndef tax_all(prices):\n    rate = DEFAULT_RATE\n"
        "    remaining = total_due - already_paid\n    return [p * rate for p in prices]\n\n\n"
        "def script():\n    return '''\n# build step\nsubprocess.run(['make', 'all'], check=True)\n"
        "# deploy step\nshutil.copytree(build_dir, deploy_dir)\n'''\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "Use tax_all(prices) and script():\n~~~\ndef tax_all(prices):\n"
        "    rate = DEFAULT_RATE\n~~~\n\nInside: remaining = total_due - already_paid\n\n"
        "```\nshutil.copytree(build_dir, deploy_dir)\n```\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "Use tax_all(prices)" in text
    for body in ("DEFAULT_RATE", "already_paid", "copytree"):
        assert body not in text, body


def test_the_fifth_reviews_bypasses_are_closed(tmp_path):
    """A C or YAML string looks like markup; a `~~~` fence right under a line
    of the same length looks like an underline; a keyword argument whose value
    is a name is a body line."""
    (tmp_path / "m.py").write_text(
        "def tax_all(prices):\n    total = sum(prices) * TAX_FACTOR\n    return total\n\n\n"
        "def upload(session, data):\n    return session.post(\n"
        "        url=UPLOAD_ENDPOINT_V2,\n        timeout=UPLOAD_TIMEOUT_SECONDS,\n    )\n\n\n"
        "def ci():\n    return '''\n- name: migrate\n  run: python manage.py migrate --fake-initial\n"
        "- name: test\n'''\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        "Use tax_all(prices)\n~~~~~~~~~~~~~~~~~~~\ndef tax_all(prices):\n"
        "    total = sum(prices) * TAX_FACTOR\n    return total\n~~~\n\n"
        "upload(session, data) posts it.\n\n```python\nsession.post(\n"
        "    url=UPLOAD_ENDPOINT_V2,\n    timeout=UPLOAD_TIMEOUT_SECONDS,\n)\n```\n\n"
        "ci() runs:\n\n```yaml\n- name: migrate\n  run: python manage.py migrate --fake-initial\n"
        "```\n", encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "m.py"), str(tmp_path))
    assert "upload(session, data) posts it." in text
    for body in ("TAX_FACTOR", "UPLOAD_ENDPOINT_V2", "--fake-initial"):
        assert body not in text, body


def test_a_hash_inside_a_string_is_not_a_comment():
    assert spec_draft._normal('x = "a #b"  # note') == 'x="a#b"'


def test_the_second_reviews_weak_criterion_cases():
    for fine in ("Works when the list is empty and the total is zero",
                 "Completes without error on an empty file and the report says 0 rows",
                 "Completes for every file in the folder and the folder is empty after"):
        assert spec_draft.weak_criterion(fine) is None, fine


def test_the_neutral_question_keeps_literals_and_hides_code():
    """A second _LITERAL, for weak_criterion, replaced the first at import:
    True, False, None and negative numbers were taken for code and dropped,
    and `'(' in sys.version` was taken for a quoted value and shown to the
    spec agent. Found by the review of the intent-sources experiment."""
    q = {"function": "f", "question": "Your tests pass whether it is `True` or `False`. "
         "Your tests pass whether it is `-1` or `None`. "
         "Here `'(' in sys.version` decides it. What should it be?"}
    text = spec_draft.neutral_question(q)
    for value in ("True", "False", "-1", "None"):
        assert value in text, value
    assert "sys.version" not in text


def test_no_module_level_name_in_spec_draft_is_assigned_twice():
    """The class of bug behind the test above: the later assignment wins
    silently, for every function that reads the name."""
    import ast
    tree = ast.parse(open(spec_draft.__file__, encoding="utf-8").read())
    names = [t.id for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)]
    names += [n.name for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    twice = sorted({n for n in names if names.count(n) > 1})
    assert not twice, twice


def test_a_keyword_only_default_on_a_signature_line_is_named():
    """pywho's question about `include_packages` reached the spec agent with no
    content: its line starts with "*,", which the parameter pattern cannot
    read. Found by the review of the intent-sources experiment."""
    source = ("def inspect_environment(\n"
              "    *, include_packages: bool = True, include_pip: bool = True\n"
              ") -> dict:\n    return {}\n\n"
              "def scale(\n    x, *, factor: int = 2, offset: int = 0\n):\n    return x\n")
    qs = [{"line": 2, "code": "*, include_packages: bool = True, include_pip: bool = True",
           "change": "bool True -> False, line 2"},
          {"line": 7, "code": "x, *, factor: int = 2, offset: int = 0",
           "change": "int 2 -> 3, line 7"}]
    named = [q.get("parameter") for q in spec_draft.with_parameters(qs, source)]
    assert named == ["include_packages or include_pip", "factor"]


def test_a_changelog_never_crowds_out_a_docs_page(tmp_path):
    """A changelog names the module's functions in every entry; ranked by
    mentions it took the whole budget and the docs/ page read before was lost."""
    (tmp_path / "pricing.py").write_text(PRICING, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text("apply_discount(100, 0) returns 100.0.\n",
                                              encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "".join(f"- {n}: apply_discount(1, 2) changed, again.\n" * 4 for n in range(400)),
        encoding="utf-8")
    text = spec_draft.docs_text(str(tmp_path / "pricing.py"), str(tmp_path))
    assert "--- docs/api.md ---" in text
    assert text.index("docs/api.md") < text.index("CHANGELOG.md")


def test_which_top_level_names_are_skipped():
    skip = spec_draft._ROOT_SKIP.match
    for name in ("README.md", "README_es.md", "README.zh-CN.md", "LICENSE", "LICENSE-MIT.md",
                 "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"):
        assert skip(name), name
    for name in ("requirements_spec.md", "requirements-design.md", "constraints_and_limits.md",
                 "SECURITY_MODEL.md", "support.md", "CHANGELOG.md", "LLM_GUIDE.md", "CLAUDE.md"):
        assert not skip(name), name


def test_a_default_is_named_only_when_the_change_points_at_one():
    """The change gives a line, not a column: with a=1, b=-1 and a lambda
    holding 1 on one line, the flipped 1 could be any of them. ydnatl's
    index=-1 has its 1 flipped and is named."""
    source = ("def f(\n    a=1, b=-1, key=lambda x: x + 1\n):\n    return a\n\n"
              "def pop(\n    self, *, index: int = -1\n):\n    return index\n")
    qs = [{"line": 2, "code": "a=1, b=-1, key=lambda x: x + 1", "change": "int 1 -> 2, line 2"},
          {"line": 7, "code": "self, *, index: int = -1", "change": "int 1 -> 2, line 7"}]
    named = [q.get("parameter") for q in spec_draft.with_parameters(qs, source)]
    assert named == [None, "index"]


def test_a_one_line_def_names_a_default_only_when_the_change_points_at_one():
    """The one-line def took the first default equal to the flipped value, even
    when the value could be inside another default. Found by the second review."""
    cases = [("def f(a=1, b=-1, key=lambda x: x + 1):\n    return a\n", "int 1 -> 2", None),
             ("def f(a=True, b=not True):\n    return a\n", "bool True -> False", None),
             ("def f(a=None, b=(None,)):\n    return a\n", "NoneType None -> 0", None),
             ("class C:\n    def m(self, a=1, b=2):\n        return a\n", "int 1 -> 2", "a")]
    for source, change, expected in cases:
        line = 2 if source.startswith("class") else 1
        code = source.splitlines()[line - 1].strip()
        q = spec_draft.with_parameters([{"line": line, "code": code,
                                         "change": f"{change}, line {line}"}], source)[0]
        assert q.get("parameter") == expected, (source, q.get("parameter"))


def test_changelog_name_variants_rank_last_and_conduct_variants_are_skipped():
    assert spec_draft._CHANGELOG.match("Changelog-old.md")
    assert spec_draft._CHANGELOG.match("CHANGELOG_v1.md")
    assert not spec_draft._CHANGELOG.match("newsletter_design.md")
    assert spec_draft._ROOT_SKIP.match("code-of-conduct.md")
