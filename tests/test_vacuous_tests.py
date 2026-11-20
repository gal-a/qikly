"""
Generated tests that can never fail, refused before a run uses them.

On jambo the test agent called clear_ref_cache(namespace=None) and then wrote
`assert True`, so a planted fault in that exact behaviour escaped. Run over
13,111 generated test files on disk, the check flagged 22, every one a test
whose only check was an always-true assert; none hid a check in a helper.
"""
from qikly.agent_tools.vacuous_tests import describe
from qikly.orchestrator.orchestrator import _validate_generated_tests


def test_a_test_whose_only_check_is_assert_true_is_flagged():
    src = ("def test_clears():\n"
           "    c = make()\n"
           "    c.clear_ref_cache(namespace=None)\n"
           "    assert True\n")
    assert describe(src).startswith("test_clears can never fail")


def test_an_always_true_constant_of_any_kind_is_flagged():
    assert describe("def test_a():\n    assert 1\n")
    assert describe("def test_b():\n    assert 'ok'\n")


def test_a_real_assert_beside_assert_true_is_not_flagged():
    src = "def test_a():\n    assert f() == 2\n    assert True\n"
    assert describe(src) is None


def test_a_test_with_no_assert_is_not_flagged():
    """It still fails if the call raises: a "runs without error" test."""
    assert describe("def test_a():\n    f()\n") is None


def test_raises_fail_and_mock_checks_count_as_checks():
    assert describe("def test_a():\n    with pytest.raises(ValueError):\n"
                    "        f()\n    assert True\n") is None
    assert describe("def test_b():\n    if f():\n        pytest.fail('x')\n"
                    "    assert True\n") is None
    assert describe("def test_c():\n    m.assert_called_once()\n    assert True\n") is None
    assert describe("def test_d():\n    if f():\n        raise AssertionError\n"
                    "    assert True\n") is None


def test_assert_false_is_a_check():
    assert describe("def test_a():\n    if f():\n        assert False\n    assert True\n") is None


def test_methods_of_a_test_class_are_checked():
    src = "class TestX:\n    def test_a(self):\n        assert True\n"
    assert describe(src).startswith("test_a can never fail")


def test_the_validator_refuses_the_file_and_says_why():
    """The refusal goes back to the test agent, which writes the file again."""
    src = "from mod import f\n\n\ndef test_a():\n    f()\n    assert True\n"
    error = _validate_generated_tests(src, "integration")
    assert "cannot fail" in error and "test_a" in error


def test_unparsable_source_is_left_to_the_syntax_check():
    assert describe("def test_a(:\n") is None
