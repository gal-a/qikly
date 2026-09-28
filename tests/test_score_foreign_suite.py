"""
Scoring a suite qikly did not write.

`--score-suite` read `outputs/agent_src/code/<task>/` and
`outputs/tests/<task>/<stage>/`: a converged run's own output, and nothing
else. That is the least likely thing a newcomer has, and everyone has a suite
before they have a task file. An agent given the Skill and a ten-line module
wanted exactly this, had read `--help`, could not get it, and wrote forty lines
of its own mutation harness instead.

## What these guard

The promise is unchanged in the new mode and is the whole product: no model is
called, and nothing of yours is modified. A mutation tool that edits the file
it is measuring, even briefly, is one interrupted run away from being the worst
bug this project could ship.

The second is about where things land. This process has already moved to a
resolved project root, which may be a clone of qikly somewhere else entirely,
so a report written to a relative path goes there rather than to the user. That
is not hypothetical: the first run of this feature wrote its report into this
repository's own `outputs/`.
"""
import io
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

MODULE = '''def line_total(quantity, unit_price):
    return quantity * unit_price


def apply_discount(subtotal, percent):
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    return subtotal - (subtotal * percent / 100)
'''

# Passes, and notices almost nothing: two examples and no boundary anywhere.
WEAK_SUITE = '''from pricing import apply_discount, line_total


def test_line_total():
    assert line_total(3, 10.0) == 30.0


def test_discount():
    assert apply_discount(100.0, 10) == 90.0
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pricing.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "test_pricing.py").write_text(WEAK_SUITE, encoding="utf-8")
    return tmp_path


def _run(arguments, cwd):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "qikly"] + arguments,
                          cwd=cwd, env=environment, capture_output=True,
                          text=True, timeout=600)


def _score(project, extra=()):
    return _run(["--score-code", "pricing.py",
                 "--score-tests", "test_pricing.py",
                 "--score-mutants", "6", "--score-seed", "1"] + list(extra),
                str(project))


def test_it_scores_a_project_qikly_has_never_seen(project):
    done = _score(project)
    assert "planted faults caught" in done.stdout, done.stdout + done.stderr


def test_a_weak_suite_scores_badly_which_is_the_entire_point(project):
    """
    Two examples and no boundary. If this suite scored well the feature would
    be measuring nothing, which is the failure mode it exists to detect in
    other people's suites.
    """
    done = _score(project)
    line = [l for l in done.stdout.splitlines() if "planted faults caught" in l][0]
    caught = int(line.split("]")[1].strip().split(" ")[0])
    assert caught <= 3, "a suite with no boundary tests scored well: %s" % line


def test_nothing_of_theirs_is_modified(project):
    before = {p: (project / p).read_text(encoding="utf-8")
              for p in ("pricing.py", "test_pricing.py")}
    _score(project)
    for name, text in before.items():
        assert (project / name).read_text(encoding="utf-8") == text, (
            "%s was modified" % name)


def test_the_report_lands_where_the_user_is_not_in_the_project_root(project):
    """
    The bug this feature shipped with for about ten minutes.

    qikly moves to a resolved project root at import. `write()` used a relative
    path, so the report went to that root, which in the first real run was this
    repository.
    """
    done = _score(project)
    reports = list((project / "qikly-suite-score").glob("*.md"))
    assert reports, "no report next to the code:\n%s" % done.stdout
    assert not (project / "outputs").exists(), (
        "it created an outputs/ tree in somebody else's project")


def test_the_report_names_what_the_suite_missed(project):
    _score(project)
    text = (list((project / "qikly-suite-score").glob("*.md"))[0]
            .read_text(encoding="utf-8"))
    assert "What it missed" in text
    assert "pricing.py" in text
    # The caveat about equivalent mutants is what makes a miss a question
    # rather than an accusation, and it must survive into this mode.
    assert "equivalent" in text


def test_a_directory_of_code_works_as_well_as_one_file(tmp_path):
    package = tmp_path / "src" / "billing"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "pricing.py").write_text(MODULE, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pricing.py").write_text(
        WEAK_SUITE.replace("from pricing import",
                           "from src.billing.pricing import"), encoding="utf-8")

    done = _run(["--score-code", "src/billing", "--score-tests", "tests",
                 "--score-mutants", "4", "--score-seed", "1"], str(tmp_path))
    assert "planted faults caught" in done.stdout or "not scored" in done.stdout.lower(), (
        done.stdout + done.stderr)


def test_one_flag_without_the_other_is_refused_clearly(project):
    done = _run(["--score-code", "pricing.py"], str(project))
    assert done.returncode == 2
    assert "--score-tests" in done.stderr


def test_a_path_that_does_not_exist_is_reported_not_raised(project):
    done = _run(["--score-code", "nope.py", "--score-tests", "test_pricing.py"],
                str(project))
    assert "Traceback" not in done.stdout + done.stderr
    assert done.returncode == 1


def test_the_task_route_still_takes_a_bare_task_id():
    """
    The old signature, kept because it reads naturally and was the only one
    for a release. A rename that silently broke `run("CALC_TAX")` would break
    the sweep rather than anything a test covers.
    """
    sys.path.insert(0, SRC)
    from qikly.mutation_score import Target, from_task

    target = from_task("CALC_TAX")
    assert isinstance(target, Target)
    assert target.task_id == "CALC_TAX"
    assert target.label == "CALC_TAX"


def test_a_label_from_a_path_cannot_become_a_directory():
    """`src/pricing.py` in a filename is a directory that does not exist."""
    sys.path.insert(0, SRC)
    from qikly.mutation_score import write

    result = {"task": "a/b\\c.py", "baseline": True, "caught": [],
              "missed": [], "unscorable": 0, "total": 0}
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = write(result, [], out_dir=tmp)
        assert os.path.isfile(path)
        assert os.path.dirname(path) == tmp

def test_the_saved_report_gives_advice_that_fits_the_mode(tmp_path):
    """
    The console message was made mode-aware and the report file was not, so
    the artefact a user keeps and pastes into a pull request still told them
    to converge a run they had never started.
    """
    sys.path.insert(0, SRC)
    from qikly.mutation_score import render

    foreign = {"task": "pricing.py", "baseline": False, "caught": [],
               "missed": [], "unscorable": 0, "total": 0, "generated": False}
    text = render(foreign, [])
    assert "converge" not in text, text
    assert "--score-tests" in text

    generated = dict(foreign, task="CALC_TAX", generated=True)
    assert "converge" in render(generated, [])


def test_the_workspace_count_follows_links_like_the_copy_does(tmp_path):
    """
    The count and the copy have to agree about symlinks or the size ceiling
    means nothing. Recreating links instead was tried and is worse: a link
    with an absolute target is recreated pointing at the same place, so the
    file in the copy IS the original, and a mutant written through it would
    land on the user's real source.
    """
    import ast
    import io as _io

    sys.path.insert(0, SRC)
    from qikly import mutation_score

    source = _io.open(mutation_score.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_workspace":
            body = ast.dump(node)
            assert "followlinks" in body, (
                "the count no longer follows links, so the ceiling can be "
                "bypassed by a linked directory")
            assert "symlinks" not in body, (
                "the copy recreates links again, which puts the user's real "
                "file inside the workspace")
            return
    raise AssertionError("_workspace is gone")

def test_a_directory_link_that_loops_is_refused_not_followed(tmp_path):
    """
    The cycle guard protected the count and not the copy, which protects
    nothing.

    os.walk was given a visited set and told to prune, so counting finished.
    shutil.copytree has no visited set of its own, so it followed the same
    loop until the path length ran out, and the user got a wall of nested OS
    errors instead of a sentence.
    """
    sys.path.insert(0, SRC)
    from qikly.mutation_score import _workspace, from_paths

    package = tmp_path / "a"
    (package / "sub").mkdir(parents=True)
    (package / "impl.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "test_impl.py").write_text(
        WEAK_SUITE.replace("from pricing import", "from a.impl import"),
        encoding="utf-8")

    try:
        os.symlink(str(package), str(package / "sub" / "loop"),
                   target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("this machine will not create a symlink: %s" % exc)
    if not os.path.islink(str(package / "sub" / "loop")):
        pytest.skip("the link was silently made a real directory")

    target = from_paths(str(package), str(tmp_path / "test_impl.py"))
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError) as caught:
            _workspace(target, tmp)
    assert "points back at" in str(caught.value)

def test_a_byte_order_mark_does_not_stop_it(tmp_path):
    """
    A BOM is normal on Windows and Python runs such a file happily.

    PowerShell 5.1's `Set-Content -Encoding utf8` writes one, as did older
    Notepad. Read as plain utf-8 the mark survives as U+FEFF at the start of
    line one and ast.parse rejects it, so qikly refused to score a file its own
    interpreter would import.

    scaffold.py has used utf-8-sig for exactly this reason, with a comment
    saying so, since before --score-code existed. The new reader did not, and
    it was found four hours after 0.5.4 shipped by running the release
    walkthrough on Windows.
    """
    module = tmp_path / "pricing.py"
    module.write_bytes(b"\xef\xbb\xbf" + MODULE.encode("utf-8"))
    (tmp_path / "test_pricing.py").write_text(WEAK_SUITE, encoding="utf-8")

    # The premise: Python itself is perfectly happy with this file.
    import ast
    ast.parse(module.read_text(encoding="utf-8-sig"))

    done = _run(["--score-code", "pricing.py", "--score-tests",
                 "test_pricing.py", "--score-mutants", "4", "--score-seed", "1"],
                str(tmp_path))
    output = done.stdout + done.stderr
    assert "U+FEFF" not in output, output[-400:]
    assert "planted faults caught" in output, output[-400:]
