"""
The release gate's own check, because it gates the release.

`check_skill_floor` compares the Skill's minimum qikly version against the one
being released. It is called from `release_check.py`'s main path with no
try/except around it, so anything it raises takes down the whole checklist
before the suite, the wheel or the remote are ever reached. It did exactly
that on any version carrying a pre-release or build suffix.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _check():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import release_check
    finally:
        sys.path.pop(0)
    return release_check.check_skill_floor


@pytest.mark.parametrize("version", ["0.5.3rc1", "0.5.3-beta", "1.0.0+build3",
                                     "0.10.0", "2.0.0"])
def test_a_legal_version_never_crashes_the_gate(version, capsys):
    """
    Every one of these raised ValueError out of int() and aborted the run.

    A pre-release tag is legal in pyproject.toml and nothing upstream stops it
    reaching this line, so the gate has to fail or pass rather than explode.
    """
    result = _check()(version)
    assert result in (True, False), "the gate returned %r" % (result,)
    capsys.readouterr()


def test_the_comparison_is_numeric_and_not_lexicographic(capsys):
    """0.10.0 is after 0.9.0, and a string comparison says otherwise."""
    check = _check()
    assert check("0.10.0") is True
    capsys.readouterr()


def test_a_release_below_the_floor_fails(capsys):
    """
    The case it exists for: the Skill naming a version that does not exist.

    This is expected to fail today, because the Skill requires 0.5.3 and the
    tree still says 0.5.2, which is exactly right before release day.
    """
    assert _check()("0.0.1") is False
    capsys.readouterr()
