"""
Tests for what the coding agent is allowed to read.

Two separate concerns share this module.

load_codebase decides how much of the task's code reaches the prompt. It walks
a directory that also holds archived runs under old/, and quietly including
those would feed the agent several stale copies of the same functions, which
is both expensive and confusing.

load_target_files reads paths the MODEL chose. That makes its path handling a
containment boundary, not a convenience: a FIX naming ../../../etc/passwd, or
a path on another drive, must be refused without taking the run down with it.
"""
import os

import pytest

from qikly.agent_api.code_loader import code_loader as cl


@pytest.fixture
def code_dir(tmp_path):
    """A task code directory with an archived run beside the live files."""
    d = tmp_path / "code" / "TASK"
    d.mkdir(parents=True)
    (d / "etl.py").write_text("def extract():\n    return 1\n")
    (d / "helpers.py").write_text("def norm(s):\n    return s.strip()\n")
    (d / "notes.txt").write_text("not code\n")
    old = d / "old" / "20260101_000000"
    old.mkdir(parents=True)
    (old / "etl.py").write_text("def extract():\n    return 0  # stale\n")
    return d


# ------------------------------------------------------- load_codebase ----

def test_loads_every_python_file_with_a_header(code_dir):
    text = cl.load_codebase(str(code_dir))
    assert "def extract():" in text
    assert "def norm(s):" in text
    assert text.count("# FILE:") == 2


def test_archived_runs_are_not_loaded(code_dir):
    """
    old/ holds previous iterations of the same functions. Including them would
    put several conflicting definitions of extract() in one prompt.
    """
    text = cl.load_codebase(str(code_dir))
    assert "stale" not in text
    assert "old" not in text


def test_non_python_files_are_skipped(code_dir):
    assert "not code" not in cl.load_codebase(str(code_dir))


def test_missing_directory_is_empty_rather_than_an_error(tmp_path):
    assert cl.load_codebase(str(tmp_path / "nope")) == ""


# --------------------------------------------------- load_target_files ----

def test_loads_only_the_named_file(code_dir):
    text = cl.load_target_files(str(code_dir), [str(code_dir / "etl.py")])
    assert "def extract():" in text
    assert "def norm(s):" not in text, "PATCH pays for every file it is shown"


def test_a_path_outside_the_task_directory_is_refused(code_dir, tmp_path):
    """target_files is model output, so this is a boundary and not a hint."""
    outsider = tmp_path / "secret.py"
    outsider.write_text("SECRET = 1\n")
    text = cl.load_target_files(str(code_dir), [str(outsider)])
    assert text == ""
    assert "SECRET" not in text


def test_traversal_out_of_the_task_directory_is_refused(code_dir, tmp_path):
    outsider = tmp_path / "secret.py"
    outsider.write_text("SECRET = 1\n")
    sneaky = os.path.join(str(code_dir), "..", "..", "secret.py")
    assert cl.load_target_files(str(code_dir), [sneaky]) == ""


def test_a_sibling_directory_sharing_a_prefix_is_refused(tmp_path):
    """
    TASK and TASK_EVIL share a string prefix but not a directory. A prefix
    comparison would let the second through.
    """
    good = tmp_path / "code" / "TASK"
    good.mkdir(parents=True)
    evil = tmp_path / "code" / "TASK_EVIL"
    evil.mkdir(parents=True)
    (evil / "x.py").write_text("EVIL = 1\n")
    assert cl.load_target_files(str(good), [str(evil / "x.py")]) == ""


def test_a_file_that_does_not_exist_yet_is_skipped(code_dir):
    """A FIX may name a file it is about to create. There is nothing to show."""
    text = cl.load_target_files(str(code_dir), [str(code_dir / "new.py")])
    assert text == ""


def test_one_bad_path_does_not_discard_the_good_ones(code_dir, tmp_path):
    text = cl.load_target_files(str(code_dir), [
        str(tmp_path / "elsewhere.py"),
        str(code_dir / "etl.py"),
    ])
    assert "def extract():" in text


def test_a_path_on_another_drive_is_refused_not_raised(code_dir):
    """
    On Windows os.path.commonpath raises ValueError for paths on different
    drives. Unhandled, a model that emits D:\\tmp\\x.py ends the whole run with
    a traceback instead of having its suggestion ignored.
    """
    other = "D:\\elsewhere\\x.py" if os.name == "nt" else "/elsewhere/x.py"
    assert cl.load_target_files(str(code_dir), [other]) == ""


def test_an_empty_target_list_is_empty(code_dir):
    assert cl.load_target_files(str(code_dir), []) == ""


# ------------------------------------------------- undecodable content ----

def test_a_stray_byte_in_generated_code_does_not_end_the_run(code_dir):
    """
    This reads code the model wrote. A byte that is not valid UTF-8 must reach
    the prompt as a replacement character, where the FIX/PATCH loop can act on
    it, rather than raising and ending the run. A decode error here killed one
    experiment pair outright.
    """
    (code_dir / "broken.py").write_bytes(b"def f():\n    return '\x80'\n")
    text = cl.load_codebase(str(code_dir))
    assert "def f():" in text
    assert "def extract():" in text, "one bad file must not lose the good ones"


def test_a_stray_byte_in_a_target_file_does_not_end_the_run(code_dir):
    (code_dir / "broken.py").write_bytes(b"x = '\x80'\n")
    text = cl.load_target_files(str(code_dir), [str(code_dir / "broken.py")])
    assert "x = " in text


# ------------------------------ every read of model output, not just some ----

def test_every_touch_of_the_models_diff_names_its_encoding():
    """
    A run died on byte 0x97 in a model-written diff, and the cause was two
    call sites disagreeing about encoding rather than one bad byte.

    The diff was WRITTEN with no encoding at all, so Python used the platform
    locale: cp1252 on Windows. An em dash became one byte there. It was then
    READ as strict UTF-8, which raised, losing a pair already paid for in
    model calls. A character cp1252 cannot represent would have killed the
    write instead.

    So both halves are checked. Writes must name utf-8; reads of model output
    must also tolerate a bad byte, because a broken diff is exactly what the
    FIX and PATCH loop exists to repair. Reads of human-written configuration
    stay strict on purpose: a corrupt settings file should be loud.
    """
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    unencoded_writes, strict_reads = [], []
    for directory, _dirs, files in os.walk(os.path.join(root, "src", "qikly")):
        for name in files:
            if not name.endswith(".py"):
                continue
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                text = handle.read()
            for call in re.finditer(r"open\(\s*patch_path[^)]*\)", text):
                snippet = call.group(0)
                line = text[:call.start()].count(chr(10)) + 1
                if '"w"' in snippet or "'w'" in snippet:
                    if "encoding=" not in snippet:
                        unencoded_writes.append(f"{name}:{line}")
                elif "errors=" not in snippet:
                    strict_reads.append(f"{name}:{line}")

    assert not unencoded_writes, (
        "these write the model's diff without naming an encoding, so the "
        "platform locale decides: " + ", ".join(unencoded_writes))
    assert not strict_reads, (
        "these read the model's diff with strict decoding, so one stray byte "
        "ends the run: " + ", ".join(strict_reads))
