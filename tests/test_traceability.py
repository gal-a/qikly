"""
Reading the criterion a generated test says it came from.

Experiment 4 of the refinement plan, built 2026-09-16. Six experiments had
compared two suites in aggregate and found nothing, and an aggregate cannot
separate a bar that adds nothing from a bar the generator ignores. The
measured 54%-more-criteria-6%-smaller-suite result says the second happens,
so the per-criterion number is the one worth having.

The marker is written by a model, so the parser has to be tolerant about
shape and strict about meaning. These pin the distinctions that matter:
no marker, a marker saying "none", and a marker naming criteria are three
different findings and must never collapse into each other.
"""
from qikly import traceability as tr


# ------------------------------------------------------ the marker ----

def test_a_plain_marker_reads_its_index():
    assert tr.criteria_in_docstring("Does a thing.\n\nCriteria: 3") == [3]


def test_several_indices_read_in_order_without_duplicates():
    assert tr.criteria_in_docstring("Criteria: 7, 3, 3") == [3, 7]


def test_the_singular_spelling_and_odd_spacing_still_parse():
    """The line is model-written, so shape varies and meaning must not."""
    for text in ("Criterion: 4", "criteria:4", "- Criteria : 4", "# criteria - 4"):
        assert tr.criteria_in_docstring(text) == [4], text


def test_no_marker_is_not_the_same_as_a_marker_saying_none():
    """
    The distinction is the whole point. No marker is a generator that ignored
    the instruction; "none" is a deliberate statement that the test came from
    the requirements. Collapsing them would report full labelling of a suite
    nothing labelled.
    """
    assert tr.criteria_in_docstring("Does a thing.") is tr.UNTRACED
    assert tr.criteria_in_docstring(None) is tr.UNTRACED
    assert tr.criteria_in_docstring("Criteria: none") == []
    assert tr.criteria_in_docstring("Criteria: requirements only") == []


def test_a_marker_with_no_number_counts_as_unlabelled():
    """
    Prose that opens with the word is not a claim. Treating it as a
    deliberate "none" would overstate how much of the suite was labelled,
    which is the one number this whole measurement rests on.
    """
    assert tr.criteria_in_docstring("Criteria: see the specification") is tr.UNTRACED


# ------------------------------------------------------- the source ----

SUITE = '''
def test_rejects_zero_quantity():
    """Zero is invalid.

    Criteria: 1
    """
    assert True


def test_total_reconciles():
    """Criteria: 2, 3"""
    assert True


def test_reads_both_files():
    """Criteria: none"""
    assert True


def test_unlabelled():
    """Nobody said where this came from."""
    assert True


def helper_not_a_test():
    """Criteria: 1"""
    return None
'''


def test_only_test_functions_are_traced():
    traced = tr.trace_source(SUITE)
    assert "helper_not_a_test" not in traced
    assert traced["test_rejects_zero_quantity"] == [1]
    assert traced["test_total_reconciles"] == [2, 3]
    assert traced["test_unlabelled"] is tr.UNTRACED


def test_a_file_that_does_not_parse_yields_nothing_rather_than_raising():
    """
    Generated source can be malformed, and the coverage read is advisory. It
    must never be the thing that fails a run.
    """
    assert tr.trace_source("def test_broken(:\n") == {}


# ----------------------------------------------------- the coverage ----

def test_coverage_counts_each_criterion_and_names_the_uncovered():
    result = tr.coverage({"integration/test_a.py": SUITE}, criteria_count=4)
    assert result["per_criterion"] == {1: 1, 2: 1, 3: 1, 4: 0}
    assert result["uncovered"] == [4]
    assert result["tests_total"] == 4
    assert result["tests_traced"] == 2
    assert len(result["tests_untraced"]) == 1
    assert len(result["tests_requirements_only"]) == 1


def test_an_index_past_the_last_criterion_is_reported_not_counted():
    """
    A generator naming criterion 9 of 4 has mislabelled something. Silently
    dropping it would make the suite look tidier than it is, and silently
    counting it would invent a criterion.
    """
    source = 'def test_x():\n    """Criteria: 9"""\n    assert True\n'
    result = tr.coverage({"s.py": source}, criteria_count=4)
    assert result["out_of_range"] == {"s.py::test_x": [9]}
    assert result["per_criterion"] == {1: 0, 2: 0, 3: 0, 4: 0}


def test_tests_are_labelled_with_the_file_they_came_from():
    """Two stages can both define test_rejects_zero_quantity."""
    result = tr.coverage({"integration/test_a.py": SUITE, "system/test_b.py": SUITE},
                         criteria_count=3)
    assert result["per_criterion"][1] == 2
    assert sorted(result["tests_by_criterion"][1]) == [
        "integration/test_a.py::test_rejects_zero_quantity",
        "system/test_b.py::test_rejects_zero_quantity",
    ]


# -------------------------------------------------------- the prompt ----

def test_test_generation_is_actually_asked_for_the_marker():
    """
    The parser is worthless if nothing emits the line. This pins the
    instruction to the shared prompt every stage loads, not to one stage.
    """
    from qikly.agent_api.prompts.template_loader import load_template

    text = load_template("test_agent.md")
    assert "Criteria: 3" in text
    assert "Criteria: none" in text


# ------------------------------------- markers the parser will not read ----

def test_a_marker_in_the_function_body_is_counted_as_stray():
    """
    Found on the first real run, 2026-09-17. Asked for a line at the end of
    each test, the model wrote one in the docstring and a second at the end
    of the body. `Criteria: none` there is a bare annotated name: legal
    Python that evaluates nothing, so it neither fails nor reports itself.

    Harmless while the docstring line is there too, and not harmless the day
    a model writes only the body one, because the whole suite then reads as
    unlabelled with no visible reason.
    """
    source = (
        'def test_x():\n'
        '    """Does a thing.\n\n    Criteria: 1\n    """\n'
        '    assert True\n'
        '    Criteria: none\n'
    )
    assert tr.markers_outside_docstrings(source) == 1
    result = tr.coverage({"s.py": source}, criteria_count=2)
    assert result["markers_outside_docstrings"] == 1
    # The docstring stays the single source of truth, so the stray line
    # changes no count. Double counting it would be worse than ignoring it.
    assert result["per_criterion"] == {1: 1, 2: 0}


def test_a_suite_labelled_only_in_docstrings_reports_no_strays():
    assert tr.markers_outside_docstrings(SUITE) == 0
    assert tr.coverage({"s.py": SUITE}, criteria_count=3)["markers_outside_docstrings"] == 0


def test_the_prompt_says_where_the_line_goes_and_bounds_the_indices():
    """
    Both instructions were added after the first real run wrote a stray line
    and named a criterion 9 on a task with five.
    """
    from qikly.agent_api.prompts.template_loader import load_template

    text = load_template("test_agent.md")
    assert "LAST LINE INSIDE that docstring" in text
    assert "dead code" in text
    assert "Use only positions that exist" in text


# ------------------------------- criteria and requirements are separate ----

def test_a_requirement_index_does_not_land_on_the_criteria_line():
    """
    The defect the second real run exposed, 2026-09-17. Asked only about
    criteria, gemini-3.5-flash-lite numbered into the requirements list and
    wrote `Criteria: 1, 9` on a task with five criteria and nine
    requirements, where requirement 9 was the output rule the test checked.

    Out-of-range made that one visible. A requirement index inside the
    criteria range would not be, and would credit a criterion nothing tested,
    which is the measurement silently reporting the opposite of the truth.
    Separate lines are what prevent it.
    """
    doc = "Checks the output shape.\n\nCriteria: 2\nRequirements: 9\n"
    assert tr.criteria_in_docstring(doc) == [2]
    assert tr.requirements_in_docstring(doc) == [9]


def test_a_test_labelled_only_with_a_requirement_is_not_unlabelled():
    """
    Unlabelled has to keep meaning "the generator ignored the instruction",
    because that is the failure with a different fix. A test naming only a
    requirement obeyed the instruction and said where it came from.
    """
    source = ('def test_writes_json():\n'
              '    """Shape of the file.\n\n    Requirements: 9\n    """\n'
              '    assert True\n')
    result = tr.coverage({"s.py": source}, criteria_count=5)
    assert result["tests_untraced"] == []
    assert result["tests_requirements_only"] == ["s.py::test_writes_json"]


def test_a_marker_written_one_line_below_the_docstring_is_still_read():
    """
    Both real runs put a `Criteria:` line at the end of the function body as
    well as, or instead of, in the docstring. Two prompt revisions did not
    stop it. Reading the body when the docstring says nothing keeps a
    labelled suite from reporting as unlabelled over a blank line.
    """
    source = ('def test_x():\n'
              '    """Does a thing."""\n'
              '    assert True\n'
              '    Criteria: 4\n')
    assert tr.trace_source(source) == {"test_x": [4]}


def test_the_docstring_wins_when_both_places_carry_a_marker():
    """One source of truth, so a duplicated line cannot double count."""
    source = ('def test_x():\n'
              '    """Thing.\n\n    Criteria: 1\n    """\n'
              '    assert True\n'
              '    Criteria: none\n')
    result = tr.coverage({"s.py": source}, criteria_count=2)
    assert result["per_criterion"] == {1: 1, 2: 0}
    assert result["markers_outside_docstrings"] == 1


def test_the_prompt_gives_requirements_their_own_line():
    from qikly.agent_api.prompts.template_loader import load_template

    text = load_template("test_agent.md")
    assert "Requirements: 9" in text
    assert "separately numbered list" in text


# --------------------------------- found in review before it measured ----

def test_an_ordinary_annotated_variable_is_not_read_as_a_marker():
    """
    The body fallback's first version swept the function source with the same
    regex used on docstrings, and the marker's shape is also the shape of an
    ordinary annotated variable. A test containing `criteria: int = 5` was
    credited with covering criterion 5.

    That is the silent-wrong-number failure this module exists to avoid, so
    the fallback reads the syntax tree: a marker is an annotated name with no
    assigned value, and a real variable has one.
    """
    source = ('def test_discount_threshold():\n'
              '    """Checks the discount logic."""\n'
              '    criteria: int = 5\n'
              '    assert criteria == 5\n')
    assert tr.trace_source(source) == {"test_discount_threshold": tr.UNTRACED}


def test_an_annotated_variable_without_a_value_is_still_not_a_marker():
    source = ('def test_x():\n    """No marker."""\n    criteria: int\n    assert True\n')
    assert tr.trace_source(source) == {"test_x": tr.UNTRACED}


def test_a_negative_index_is_not_read_as_a_positive_one():
    r"""`\d+` dropped the sign and turned -1 into criterion 1."""
    source = ('def test_x():\n    """No marker."""\n    assert True\n    Criteria: -1\n')
    assert tr.trace_source(source) == {"test_x": tr.UNTRACED}


def test_a_dash_between_numbers_is_reported_rather_than_guessed():
    """
    "Criteria: 3-5" is either a range or two indices and nothing can tell
    which. Expanding it invents coverage; taking the endpoints drops
    criterion 4 without saying so. Both are worse than declining to read it.
    """
    assert tr.criteria_in_docstring("Criteria: 3-5") is tr.AMBIGUOUS
    source = ('def test_x():\n    """Thing.\n\n    Criteria: 3-5\n    """\n    assert True\n')
    result = tr.coverage({"s.py": source}, criteria_count=5)
    assert result["tests_ambiguous"] == ["s.py::test_x"]
    assert result["per_criterion"] == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    assert result["tests_total"] == 1
    assert result["tests_untraced"] == []


def test_the_last_marker_line_wins_because_the_prompt_says_the_last_one():
    """search() took the leftmost, which contradicted the instruction."""
    assert tr.criteria_in_docstring("Criteria: 1\nCriteria: 2") == [2]


# ------------------------------------------------- the two call sites ----

def test_the_report_section_survives_a_result_shape_it_did_not_expect():
    """
    The guard used to wrap only the trace() call, leaving the row building
    outside it. A result missing a key raised from there, and because the
    caller wraps report generation wholesale, the run lost its entire HTML
    report rather than this one section.
    """
    from qikly.orchestrator.reports import report
    from qikly.orchestrator.tuning import trace_criteria

    original = trace_criteria.trace
    try:
        trace_criteria.trace = lambda *a, **k: {
            "criteria_count": 2, "criteria": ["a", "b"], "per_criterion": {1: 1, 2: 0}}
        assert report._coverage_section_html("T") == ""
    finally:
        trace_criteria.trace = original


def test_the_report_section_renders_a_row_per_criterion():
    from qikly.orchestrator.reports import report
    from qikly.orchestrator.tuning import trace_criteria

    original = trace_criteria.trace
    try:
        trace_criteria.trace = lambda *a, **k: dict(
            tr.coverage({"s.py": SUITE}, criteria_count=4),
            task_id="T", criteria=["first", "second", "third", "fourth"])
        html = report._coverage_section_html("T")
        assert "Criteria coverage" in html
        assert "fourth" in html
        assert "cov-none" in html, "the uncovered criterion is marked"
    finally:
        trace_criteria.trace = original


def test_the_report_section_is_empty_when_the_task_has_no_suites():
    from qikly.orchestrator.reports import report
    from qikly.orchestrator.tuning import trace_criteria

    original = trace_criteria.trace
    try:
        trace_criteria.trace = lambda *a, **k: None
        assert report._coverage_section_html("T") == ""
    finally:
        trace_criteria.trace = original


def test_the_cli_maps_suites_on_disk_to_a_task_s_criteria(tmp_path, monkeypatch):
    """
    The integration point both call sites depend on, including the
    explain.build() lookup, which nothing else exercised.
    """
    from qikly import explain
    from qikly.orchestrator.tuning import trace_criteria

    stage = tmp_path / "integration"
    stage.mkdir()
    (stage / "test_a.py").write_text(SUITE, encoding="utf-8")
    monkeypatch.setattr(explain, "build",
                        lambda task_id: {"criteria": ["one", "two", "three", "four"]})

    result = trace_criteria.trace("T", str(tmp_path))
    assert result["task_id"] == "T"
    assert result["per_criterion"] == {1: 1, 2: 1, 3: 1, 4: 0}
    assert result["uncovered"] == [4]


def test_the_cli_returns_nothing_when_there_are_no_suites(tmp_path):
    from qikly.orchestrator.tuning import trace_criteria

    assert trace_criteria.trace("T", str(tmp_path)) is None
