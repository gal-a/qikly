"""
The two lines that answer "where am I and what am I running".

Both come from the same report. A first-time user ran `qikly --example`, the
tool said it had created seven files, and he could not find any of them. Three
explanations were proposed from a screenshot and all three were wrong, because
the output did not carry the two facts needed to tell them apart: which version
produced it, and which directory it was standing in.

## What each guards

`stamp()` is for the screenshot. A user reports a problem with a photo of their
terminal, and 0.4.6 and 0.5.3 used to print identically. It also names the
directory, and says so when the project root is somewhere else, which is this
project's most repeated bug shape: a sweep that wrote into the repository, a
smoke test that scored the wrong project, and this report.

`inside_a_demo()` is for the trap underneath it. `--demo` runs in
`demo/<timestamp>/` so it touches nothing of yours, which also means everything
in there is thrown away. Someone who has just watched it work is standing in
something that looks exactly like a working project.
"""
import io
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

STAMP = re.compile(r"^qikly \d+\.\d+\.\d+  "
                   r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  run in .+")


def _run(arguments, cwd):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "qikly"] + arguments,
                          cwd=cwd, env=environment, capture_output=True,
                          text=True, timeout=300)


# ------------------------------------------------------------------ stamp --

def test_the_first_line_names_the_version_the_time_and_the_place(tmp_path):
    done = _run(["--example"], str(tmp_path))
    first = done.stdout.splitlines()[0]
    assert STAMP.match(first), "the stamp is missing or reshaped:\n%s" % first


def test_it_names_the_directory_the_user_typed_in_not_the_one_it_moved_to(tmp_path):
    """
    The whole point, and the thing that made the first version useless.

    qikly changes directory to a resolved project root at import. Printing
    os.getcwd() therefore named a directory the user had never heard of, while
    `--example` wrote somewhere else entirely, which is a better way of causing
    the confusion than of fixing it.
    """
    done = _run(["--example"], str(tmp_path))
    first = done.stdout.splitlines()[0]
    assert str(tmp_path) in first, (
        "the stamp does not name where the command was run:\n%s" % first)


def test_a_project_root_somewhere_else_is_said_out_loud(tmp_path):
    done = _run(["--example"], str(tmp_path))
    assert "project root is elsewhere" in done.stdout
    assert "QIKLY_PROJECT_ROOT" in done.stdout


def test_it_stays_quiet_when_there_is_nothing_to_warn_about(tmp_path):
    """A warning on every single run is a warning nobody reads."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    environment["QIKLY_PROJECT_ROOT"] = str(tmp_path)
    done = subprocess.run([sys.executable, "-m", "qikly", "--validate"],
                          cwd=str(tmp_path), env=environment,
                          capture_output=True, text=True, timeout=300)
    assert "project root is elsewhere" not in done.stdout


def test_json_output_is_left_alone(tmp_path):
    """
    `--validate --json` is parsed by other programs, so a banner on top of it
    is a breaking change rather than a helpful line.
    """
    import json

    done = _run(["--validate", "--json"], str(tmp_path))
    json.loads(done.stdout)


# ------------------------------------------------------- the demo's folder --

@pytest.mark.parametrize("depth", [".", "outputs", "outputs/data/CALC_TAX"])
def test_a_new_project_is_refused_inside_the_demos_copy(depth, tmp_path):
    """
    Refused from anywhere inside it, not only at the top.

    The reader who has just watched the demo has usually gone into `outputs/`
    to look at what it produced, and that is where they are standing when they
    decide to start their own.
    """
    scratch = tmp_path / "demo" / "20260927_112524" / depth
    scratch.mkdir(parents=True, exist_ok=True)

    done = _run(["--example"], str(scratch))
    assert "throwaway copy" in done.stdout
    assert done.returncode == 2
    assert not (scratch / "inputs_private").exists(), (
        "it refused and created the project anyway")


def test_a_demo_inside_a_demo_is_refused_too(tmp_path):
    scratch = tmp_path / "demo" / "20260927_112524"
    scratch.mkdir(parents=True)
    done = _run(["--demo"], str(scratch))
    assert "throwaway copy" in done.stdout
    assert done.returncode == 2


def test_an_ordinary_directory_is_not_mistaken_for_one(tmp_path):
    for name in ("demo", "demo/notes", "20260927_112524", "demos/20260927_112524"):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        done = _run(["--example"], str(d))
        assert "throwaway copy" not in done.stdout, (
            "%s was treated as the demo's scratch directory" % name)


def test_the_check_is_by_shape_not_by_a_path_containing_demo():
    """
    Checked directly, because the subprocess tests cannot reach a user whose
    home directory is called `demo` or whose project lives under `demos/`.
    """
    sys.path.insert(0, SRC)
    from qikly.cli import inside_a_demo

    assert inside_a_demo(os.path.join("x", "demo", "20260927_112524"))
    assert inside_a_demo(os.path.join("x", "demo", "20260927_112524", "outputs"))
    assert inside_a_demo(os.path.join("demo", "19700101_000000"))

    assert inside_a_demo(os.path.join("x", "demo")) is None
    assert inside_a_demo(os.path.join("x", "demo", "notes")) is None
    assert inside_a_demo(os.path.join("x", "demos", "20260927_112524")) is None
    assert inside_a_demo(os.path.join("x", "20260927_112524")) is None
    assert inside_a_demo(os.path.join("x", "demo", "2026092_112524")) is None

def test_a_demo_dir_folder_is_recognised_too(tmp_path):
    """
    `--demo-dir ./try-it` produces `try-it/<timestamp>/`, with no `demo`
    component anywhere, so a check on the path's shape could never see it. And
    that is the combination the CLI's own help text recommends.

    The fix is a marker file written into every demo directory as it is made,
    so the folder says what it is rather than being guessed at.
    """
    sys.path.insert(0, SRC)
    from qikly.cli import DEMO_MARKER, inside_a_demo

    scratch = tmp_path / "try-it" / "20260927_120000"
    scratch.mkdir(parents=True)
    assert inside_a_demo(str(scratch)) is None, "nothing marks it yet"

    (scratch / DEMO_MARKER).write_text("demo", encoding="utf-8")
    assert inside_a_demo(str(scratch)) == str(scratch)
    assert inside_a_demo(str(scratch / "outputs")) == str(scratch)
    assert inside_a_demo(str(tmp_path)) is None


def test_the_demo_folder_name_is_matched_whatever_its_case(tmp_path):
    """A folder copied or renamed to `Demo` on Windows is the same folder."""
    sys.path.insert(0, SRC)
    from qikly.cli import inside_a_demo

    assert inside_a_demo(os.path.join("x", "Demo", "20260927_120000"))


@pytest.mark.parametrize("arguments", [
    ["--score-mutants", "5"],
    ["--score-seed", "3"],
    ["--score-mutants", "5", "--score-seed", "3"],
    # Found by auditing the fix for the three above, which is the point of
    # auditing a fix: the same defect in the sibling flag nobody checked.
    ["--artifacts-url", "https://ci.example.com/build/12"],
    # The third one, missed by three separate audits. --html has had this
    # check since it shipped; --json sits beside it and never did.
    ["--json"],
])
def test_a_scoring_option_alone_never_starts_a_real_run(arguments, tmp_path):
    """
    The expensive one. Neither option triggers the scoring branch on its own,
    so `qikly --score-mutants 5` fell straight through to the ordinary run
    path and began a real, billed run over every bundled task. An audit
    reproduced it by accident and spent money doing so.
    """
    done = _run(arguments, str(tmp_path))
    assert done.returncode == 2, done.stdout + done.stderr
    assert "goes with" in done.stderr
    assert "generating" not in done.stdout.lower(), (
        "a run started:\n%s" % done.stdout[:400])

def test_the_refusal_says_how_to_undo_it(tmp_path):
    """
    Someone who kept a demo folder and made it their own was otherwise blocked
    here forever by a hidden file whose name the message never mentioned.
    """
    sys.path.insert(0, SRC)
    from qikly.cli import DEMO_MARKER

    scratch = tmp_path / "demo" / "20260927_120000"
    scratch.mkdir(parents=True)
    (scratch / DEMO_MARKER).write_text("demo", encoding="utf-8")

    done = _run(["--example"], str(scratch))
    assert DEMO_MARKER in done.stdout, (
        "the way out is not named:\n%s" % done.stdout)

def test_it_says_so_before_scattering_files_through_your_home_directory(tmp_path):
    """
    A first-time user ran `--example` in his home directory and finished with
    inputs_private/, outputs/, my_metrics.py and demo/ beside Documents,
    Downloads and Dropbox, then could not tell which of two identical-looking
    trees was his project.

    Warned rather than refused: nothing here overwrites anything, and somebody
    may mean it.
    """
    home = tmp_path / "home"
    home.mkdir()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    environment["USERPROFILE"] = str(home)   # Windows
    environment["HOME"] = str(home)          # everywhere else
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)

    done = subprocess.run([sys.executable, "-m", "qikly", "--example"],
                          cwd=str(home), env=environment, capture_output=True,
                          text=True, timeout=300)
    assert "this is your home directory" in done.stdout.lower(), done.stdout
    assert "mkdir qikly-test" in done.stdout
    # Warned, not refused: the files are still created.
    assert (home / "inputs_private").is_dir(), (
        "it warned and then did nothing, which is not what a warning is")

    elsewhere = tmp_path / "a-project"
    elsewhere.mkdir()
    done = subprocess.run([sys.executable, "-m", "qikly", "--example"],
                          cwd=str(elsewhere), env=environment,
                          capture_output=True, text=True, timeout=300)
    assert "your home directory" not in done.stdout.lower(), (
        "an ordinary project directory was warned about:\n%s" % done.stdout)
