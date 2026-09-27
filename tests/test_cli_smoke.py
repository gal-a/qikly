"""
Every free command, actually run, in a throwaway directory.

Three crashes in this change set reached a user-facing command while the suite
stayed green, and they had one thing in common: every test called the function
directly and none went through argparse.

    qikly --score-suite        AttributeError: 'Namespace' has no 'seed'
    qikly --install-skill all  FileNotFoundError out of makedirs
    release_check              ValueError out of int(), on a pre-release tag

A unit test cannot see any of those, because the bug is in the wiring between
the parser and the handler. This runs the real command line in a subprocess
and asserts the one thing a user cares about: it did not fall over.

## What counts as failure here

A Python traceback. Not a non-zero exit: plenty of these commands exit non-zero
for good reasons, and `--validate` on a deliberately broken task should. A
traceback means nobody handled it, which is a different thing and always a bug.

## Why subprocesses rather than calling main()

Because argparse, `sys.argv`, the working directory and the environment are all
part of what broke. Calling `main(["--score-suite"])` in-process would have
passed while the real command died.

No model is called and nothing is spent: every command here is on qikly's own
free list.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

TRACEBACK = "Traceback (most recent call last)"

# The free commands, and the flag combinations the guard is supposed to catch.
# Each is (arguments, what the exit code may be).
COMMANDS = [
    (["--version"], {0}),
    (["--help"], {0}),
    (["--explain", "CALC_TAX"], {0}),
    (["--validate"], {0, 1}),
    (["--validate", "--tasks", "CALC_TAX"], {0, 1}),
    (["--validate", "--json"], {0, 1}),
    (["--init"], {0}),
    (["--example"], {0}),
    (["--install-skill"], {0}),
    (["--install-skill", "agents"], {0}),
    (["--install-skill", "all"], {0}),
    (["--install-skill", "--force"], {0}),
    (["--install-skill", "cursor", "--dry-run"], {0}),
    (["--install-mcp", "--dry-run"], {0, 1}),
    (["--mcp-config"], {0}),
    (["--score-suite", "--tasks", "NOT_A_TASK"], {0, 1}),
    (["--score-suite", "--tasks", "CALC_TAX", "--score-mutants", "1",
      "--score-seed", "3"], {0, 1}),
    (["--trends"], {0, 1}),
    # Flag combinations the attachment guard rejects. A refusal is correct;
    # a traceback is not.
    (["--fresh"], {2}),
    (["--force"], {2}),
    (["--demo-dir", "somewhere"], {2}),
    (["--install-skill", "bogus-agent"], {2}),
    (["--score-mutants", "4"], {0, 1, 2}),
]


def _run(arguments, cwd):
    environment = dict(os.environ)
    # An absolute path, because the subprocess runs somewhere else and a
    # relative PYTHONPATH silently resolves to nothing, which is how a test
    # ends up exercising whichever qikly is installed instead of this one.
    environment["PYTHONPATH"] = SRC
    # Pin the project root to the throwaway directory. Without this, a
    # subprocess with the repo on PYTHONPATH resolves the repo as its project
    # (paths.py rule 3, the clone case), so `--score-suite` found the real
    # CALC_TAX outputs and spent five minutes scoring them for real, against
    # the tree this test must not touch.
    environment["QIKLY_PROJECT_ROOT"] = cwd
    # No key, so nothing can spend even if a command were wired wrongly.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "qikly"] + arguments,
                          cwd=cwd, env=environment, capture_output=True,
                          text=True, timeout=300)


@pytest.mark.parametrize("arguments,codes",
                         COMMANDS,
                         ids=[" ".join(c[0]) for c in COMMANDS])
def test_a_free_command_does_not_fall_over(arguments, codes, tmp_path):
    done = _run(arguments, str(tmp_path))
    output = done.stdout + done.stderr

    assert TRACEBACK not in output, (
        "%s crashed:\n%s" % (" ".join(arguments), output[-2000:]))
    assert done.returncode in codes, (
        "%s exited %d, expected one of %s\n%s"
        % (" ".join(arguments), done.returncode, sorted(codes), output[-1500:]))


def test_the_command_under_test_is_this_checkout(tmp_path):
    """
    The guard on the guard. If PYTHONPATH is not reaching the subprocess, every
    test above is exercising whichever qikly is installed, and would pass while
    saying nothing about this code.
    """
    done = _run(["--version"], str(tmp_path))
    assert SRC.lower() in done.stdout.lower(), (
        "the subprocess is running a different qikly:\n%s" % done.stdout)


def test_a_broken_task_is_reported_rather_than_raised(tmp_path):
    """
    `--validate` is recommended as a pre-commit hook, so it meets whatever is
    on disk, including files nobody would write on purpose.
    """
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "BROKEN.yaml").write_text("task_id: [unclosed\n", encoding="utf-8")

    data = tmp_path / "inputs_private" / "data" / "BROKEN"
    data.mkdir(parents=True)
    # A NUL byte, which crashed the reachability check through csv.reader.
    (data / "input_01.csv").write_bytes(b"a,b\n1\x002,3\n")

    done = _run(["--validate"], str(tmp_path))
    assert TRACEBACK not in (done.stdout + done.stderr), (
        "validate crashed on a malformed task:\n%s" % (done.stdout + done.stderr))
