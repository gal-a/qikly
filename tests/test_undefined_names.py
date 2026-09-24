"""
A generated test that cannot pass, caught before the coding agent pays for it.

`_validate_generated_tests` exists because a broken test file makes the coding
agent "burn its entire attempt budget on a failure it structurally cannot fix".
It caught syntax errors and files with no tests, and missed the case that
actually turned up in output:

    rows = [...]
    records = transform(records)

`rows` is built and never used, and `transform` is handed a name that does not
exist yet. NameError on every run, the same failure text every iteration, and
nothing for a repair to act on.

Measured on 37 runs of the worked example: 4 failed, and this check flags the
generated file in every one of the four while flagging nothing in the other 509
real generated files on disk. That ratio is the point. A false positive throws
away a usable suite and spends another generation call, so the check is written
to stay quiet wherever the answer is not obvious, and every exclusion below is
there because a real file needed it.
"""
import pytest

from qikly.agent_tools.undefined_names import describe, undefined_uses


def test_the_defect_this_was_written_for():
    source = (
        "def test_negative_temperatures_are_usable():\n"
        "    from mod import transform\n"
        "    rows = [{'temp_c': '-1.0'}]\n"
        "    records = transform(records)\n"
        "    assert len(records) == 1\n"
    )
    problems = undefined_uses(source)
    assert problems, "the case this module exists for was not flagged"
    assert problems[0][1] == "records"
    assert "records" in describe(source)


def test_a_correct_test_is_not_flagged():
    source = (
        "def test_fine():\n"
        "    from mod import transform\n"
        "    rows = [{'temp_c': '-1.0'}]\n"
        "    records = transform(rows)\n"
        "    assert len(records) == 1\n"
    )
    assert undefined_uses(source) == []
    assert describe(source) is None


def test_a_comprehension_binds_its_own_target():
    """
    The exclusion that matters most.

    Written without it, the check flagged 86 of 509 real generated files, and
    nearly every one was a `for r in ...` inside an `all(...)`. Rejecting a
    usable suite costs a generation call and a second sample, so the wrong
    direction here is expensive.
    """
    source = (
        "def test_reasons_name_a_field():\n"
        "    result = {'rejected': [{'reason': 'temp_c missing'}]}\n"
        "    assert all('temp_c' in r['reason'] for r in result['rejected'])\n"
        "    names = [x['reason'] for x in result['rejected']]\n"
        "    assert names\n"
    )
    assert undefined_uses(source) == []


def test_a_lambda_binds_its_own_arguments():
    source = (
        "def test_sorting():\n"
        "    rows = [{'day': '2026-01-02'}, {'day': '2026-01-01'}]\n"
        "    ordered = sorted(rows, key=lambda row: row['day'])\n"
        "    assert ordered[0]['day'] == '2026-01-01'\n"
    )
    assert undefined_uses(source) == []


@pytest.mark.parametrize("body", [
    # A loop may bind on one pass what it reads on the next.
    "    for row in rows:\n        total = total + 1\n    assert total\n",
    # A branch may bind on the path not taken first.
    "    if rows:\n        found = 1\n    assert found\n",
    # try/except binds in one arm and reads in another.
    "    try:\n        value = 1\n    except Exception:\n        value = 2\n    assert value\n",
    # with-as binds a name the enclosing statement does not show.
    "    with open('f') as handle:\n        data = handle.read()\n    assert data\n",
])
def test_control_flow_is_left_alone_rather_than_guessed_at(body):
    """
    Where evaluation order is not plain, this reports nothing.

    Every one of these is legal Python that a flat read of the statements
    would call a use before assignment. Being quiet here is what keeps the
    false positive rate at zero on real output, and it is a deliberate trade:
    a genuine defect inside a loop goes to pytest instead.
    """
    source = "def test_something():\n    rows = [1]\n" + body
    assert undefined_uses(source) == []


def test_module_level_names_are_visible_inside_a_test():
    source = (
        "import json\n"
        "INPUT_PATH = 'inputs_private/data/T/input_01.csv'\n"
        "\n"
        "def test_reads_the_input():\n"
        "    rows = json.loads('[]')\n"
        "    assert INPUT_PATH\n"
        "    assert rows == []\n"
    )
    assert undefined_uses(source) == []


def test_one_test_does_not_lend_its_locals_to_another():
    """
    The bug the first version of this shipped with.

    Module scope was collected with a walk, and a walk descends into function
    bodies, so `records` assigned in the first test counted as a module-level
    name and the second test's use of it looked defined. The checker reported
    509 real files clean while checking almost nothing, which is the shape of
    guard this repository spends its time arguing against.
    """
    source = (
        "def test_one():\n"
        "    records = [1]\n"
        "    assert records\n"
        "\n"
        "def test_two():\n"
        "    assert records\n"
    )
    problems = undefined_uses(source)
    assert problems, "a local from another test was treated as module scope"
    assert problems[0][0] == "test_two"


def test_a_file_that_does_not_parse_is_left_to_the_syntax_check():
    assert undefined_uses("def test_x(:\n    pass\n") == []


def test_the_orchestrator_rejects_such_a_file():
    """The check is only worth having if generation actually consults it."""
    from qikly.orchestrator.orchestrator import _validate_generated_tests

    broken = (
        "def test_x():\n"
        "    from mod import transform\n"
        "    rows = [1]\n"
        "    records = transform(records)\n"
        "    assert records\n"
    )
    error = _validate_generated_tests(broken, "unit")
    assert error and "before assigning it" in error

    fine = broken.replace("transform(records)", "transform(rows)")
    assert _validate_generated_tests(fine, "unit") is None


def test_a_typo_inside_a_nested_helper_is_still_caught():
    """
    The regression this file's own fix introduced, and then undid.

    Excluding nested definitions removed a false positive and created a false
    negative: a name nothing binds anywhere, inside a nested helper, stopped
    being flagged, and it had been flagged before. A nested scope is now
    checked on its own terms instead of skipped.
    """
    source = (
        "def test_x():\n"
        "    def helper():\n"
        "        return totally_undefined_xyz\n"
        "    assert helper() == 1\n"
    )
    problems = undefined_uses(source)
    assert problems, "a typo inside a nested helper went unreported"
    assert problems[0][1] == "totally_undefined_xyz"


def test_a_nested_helper_may_read_what_the_test_binds_later():
    """
    The false positive that prompted the skip, which must stay fixed.

    A nested function resolves names when it is called, so reading something
    the enclosing test binds further down is correct Python.
    """
    source = (
        "def test_x():\n"
        "    def helper(index):\n"
        "        return rows[index]\n"
        "    rows = [1]\n"
        "    assert helper(0) == 1\n"
    )
    assert undefined_uses(source) == []


def test_a_class_body_is_a_scope_too():
    """Both directions, for a class defined inside a test."""
    fine = (
        "def test_x():\n"
        "    class Fake:\n"
        "        def get(self):\n"
        "            return payload\n"
        "    payload = 1\n"
        "    assert Fake().get() == 1\n"
    )
    assert undefined_uses(fine) == []

    typo = (
        "def test_x():\n"
        "    class Fake:\n"
        "        def get(self):\n"
        "            return undefined_in_class_xyz\n"
        "    assert Fake()\n"
    )
    assert undefined_uses(typo), "a typo inside a nested class went unreported"


def test_a_loop_in_the_test_does_not_excuse_a_nested_helper():
    """
    Control flow disables checking for the scope it appears in, not for the
    scopes nested inside it. A test with a `for` loop still has its helpers
    read.
    """
    source = (
        "def test_x():\n"
        "    for index in [1]:\n"
        "        pass\n"
        "    def helper():\n"
        "        return nope_xyz\n"
        "    assert helper()\n"
    )
    assert undefined_uses(source), "the nested helper was not checked"


def test_a_bare_class_attribute_is_not_visible_to_its_own_methods():
    """
    Python leaves a class body out of the chain its methods look through.

        class Helper:
            EXPECTED = 42
            def check(self):
                return EXPECTED      # NameError, every time

    Two separate mistakes made this read as legal. The class body's names were
    handed down to its methods as though a class were a function, and
    `_bound_by` walked into the nested class so `EXPECTED` counted as a binding
    of the test around it. That second one is the third appearance of the same
    habit in this module, after `_module_level_names` and `_loaded_by`.
    """
    broken = (
        "def test_x():\n"
        "    class Helper:\n"
        "        EXPECTED = 42\n"
        "        def check(self):\n"
        "            return EXPECTED\n"
        "    assert Helper().check() == 42\n"
    )
    problems = undefined_uses(broken)
    assert problems, "a bare class attribute read from a method went unreported"
    assert problems[0][1] == "EXPECTED"

    correct = broken.replace("return EXPECTED", "return self.EXPECTED")
    assert undefined_uses(correct) == [], "self.NAME is how a method reads it"


def test_a_class_body_can_read_its_own_earlier_names():
    """Inside the class body itself, the names are in scope."""
    source = (
        "def test_x():\n"
        "    class Helper:\n"
        "        A = 1\n"
        "        B = A + 1\n"
        "    assert Helper.B == 2\n"
    )
    assert undefined_uses(source) == []


def test_a_class_at_module_level_is_analysed_too():
    """
    It was skipped entirely: the top level loop only picked out functions, so
    a helper or a fake defined beside the tests was never read.
    """
    source = (
        "class Fake:\n"
        "    def get(self):\n"
        "        return totally_undefined_xyz\n"
    )
    assert undefined_uses(source), "a module level class went unchecked"
