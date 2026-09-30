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

import qikly.mutation_score as ms

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

def test_two_mutations_that_read_the_same_are_told_apart_by_line():
    """
    A module with two 100s in it produced two report rows reading
    "int 100 -> 101", identically, and a reader handed that report cannot tell
    which line each refers to. Two rows that look the same look like a bug in
    the tool, which is the worst thing a report you hand to somebody else's
    team can do.

    Found by running the release walkthrough and reading the artefact as a
    stranger would.
    """
    sys.path.insert(0, SRC)
    from qikly.mutation_score import sites

    source = (
        "def apply_discount(subtotal, percent):\n"
        "    if percent < 0 or percent > 100:\n"
        "        raise ValueError('out of range')\n"
        "    return subtotal - (subtotal * percent / 100)\n")

    described = [text for _, _, text in sites(source)]
    assert described, "nothing to mutate in a module with two comparisons"

    # Every description says where.
    for text in described:
        assert "line " in text, "a mutation with no line: %s" % text

    # And the two 100s, which read identically without one, do not collide.
    hundreds = [text for text in described if "100 -> 101" in text]
    assert len(hundreds) == 2, hundreds
    assert len(set(hundreds)) == 2, (
        "both 100s produced the same row, so the report cannot say which line "
        "is which: %s" % hundreds)

# --------------------------------------------------- the invitation to report --
#
# Added after an audit found three defects in a function that had no test:
# it fired for qikly's own generated suites, where its wording is false; it
# printed once per task rather than once per invocation; and one of its two
# call sites could never fire.


@pytest.fixture(autouse=True)
def _forget_that_we_asked(monkeypatch):
    """Each test starts as a fresh invocation would."""
    monkeypatch.setattr(ms, "_ALREADY_ASKED", False)
    monkeypatch.delenv("QIKLY_NO_INVITE", raising=False)


def test_it_asks_when_a_suite_of_theirs_missed_something():
    assert ms._invite_a_report({"missed": ["a"], "generated": False})


def test_it_says_nothing_when_the_suite_caught_everything():
    """An invitation printed after good news is an advertisement."""
    assert ms._invite_a_report({"missed": [], "generated": False}) is None


def test_it_says_nothing_about_a_suite_qikly_wrote_itself():
    """
    `--score-suite --tasks X` scores the generated suite. There the message
    is not merely unnecessary, it is false: it offers the misses as evidence
    of what *real* suites miss, and the suite that missed them is qikly's.
    """
    assert ms._invite_a_report({"missed": ["a"], "generated": True}) is None


def test_it_asks_once_per_invocation_and_not_once_per_task():
    """
    `--score-suite` loops over every task it was given. The rule for
    unprompted output in this codebase is set by the version check: a sweep
    of ten tasks says a thing once.
    """
    result = {"missed": ["a"], "generated": False}
    assert ms._invite_a_report(result)
    assert ms._invite_a_report(result) is None
    assert ms._invite_a_report(result) is None


def test_the_opt_out_wins():
    import os
    os.environ["QIKLY_NO_INVITE"] = "1"
    try:
        assert ms._invite_a_report({"missed": ["a"], "generated": False}) is None
    finally:
        del os.environ["QIKLY_NO_INVITE"]


def test_it_survives_a_result_that_is_missing_its_keys():
    """It runs at the end of a scoring run; it must never be what fails one."""
    for result in (None, {}, {"missed": None}, {"missed": ["a"]}):
        assert ms._invite_a_report(result) is None


def test_the_ask_is_ascii_because_it_prints_to_a_windows_console():
    message = ms._invite_a_report({"missed": ["a"], "generated": False})
    assert message.isascii(), [c for c in message if not c.isascii()]

def test_the_project_root_line_is_not_shown_where_it_would_be_false(monkeypatch):
    """
    `--score-code` resolves its paths against where the command was typed and
    writes the report beside them, so the project root reaches nothing. The
    line offering QIKLY_PROJECT_ROOT as the remedy arrives at the moment a
    first-time user is working out how qikly finds their module, and answers
    a question they do not have. Every command that reads a task file still
    gets it.
    """
    import io as _io
    from qikly import cli

    monkeypatch.setattr(cli, "PROJECT_ROOT", "/somewhere/else")
    monkeypatch.setattr(cli, "INVOKED_FROM", "/where/they/are")

    reads_a_task_file = _io.StringIO()
    cli.stamp(stream=reads_a_task_file)
    assert "project root is elsewhere" in reads_a_task_file.getvalue()

    scores_their_own_code = _io.StringIO()
    cli.stamp(stream=scores_their_own_code, project_root_matters=False)
    assert "project root is elsewhere" not in scores_their_own_code.getvalue()
    # The line that does answer them survives.
    assert "run in" in scores_their_own_code.getvalue()

