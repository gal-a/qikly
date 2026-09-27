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

@pytest.mark.parametrize("target", ["all", "cursor", "gemini", "agents"])
def test_the_install_message_reads_as_english(target, tmp_path):
    """
    `all` and `auto` are targets, not agents, and both got substituted as one.

    The line was built as "That is the path %s documents for skills", which
    reads correctly for a real agent and produced "the path all documents for
    skills", then, one release later, "the path auto documents for skills".
    The same defect twice, so the message is now assembled from the hosts
    actually written and never from what was asked for.

    Nothing caught the first one because every test called the installer
    directly and none read what a user would see.
    """
    done = _run(["--install-skill", target], str(tmp_path))
    output = done.stdout + done.stderr

    for leaked in ("path all documents", "path auto documents",
                   "in all,", "in auto,"):
        assert leaked not in output, (
            "a target name reached the prose where an agent name belongs:\n%s"
            % output[-600:])
    assert "Skill written to" in output, output[-400:]
    if target != "claude":
        assert "we would like to hear" in output, (
            "a path other than Claude's should say what is and is not known "
            "about it:\n%s" % output[-400:])

# The six options that are supposed to start a run when given on their own.
# Everything else must either do its own job and stop, or be refused by the
# attachment guard for having nothing to attach to.
#
# Adding a flag here is a decision that it may spend money unaccompanied. If
# the test below fails for a new flag, the question is which of the two it is,
# and the answer is almost always the guard.
STARTS_A_RUN = {
    "--tasks",              # the ordinary way to run named tasks
    "--demo",               # a run in a throwaway directory
    "--resume",             # continues a run that stopped
    "--generate-criteria",  # writes criteria, which is a model call
    "--dry-run",            # a run that stops before applying patches
    "--review-patches",     # a run that pauses at each patch
}


def _every_option():
    """One minimal invocation per option the parser accepts."""
    import argparse

    sys.path.insert(0, SRC)
    from qikly import cli

    captured = {}

    def grab(self, *a, **k):
        captured["parser"] = self
        raise SystemExit(0)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(argparse.ArgumentParser, "parse_args", grab)
        with pytest.raises(SystemExit):
            cli._parse_args()
    finally:
        monkey.undo()

    for action in captured["parser"]._actions:
        if not action.option_strings:
            continue
        flag = action.option_strings[0]
        if flag in ("-h", "--help", "--version"):
            continue
        if action.nargs in (0, "?") or isinstance(action, argparse._StoreTrueAction):
            yield flag, [flag]
        elif action.choices:
            # A real choice, never a placeholder. Probing `--by x` made
            # argparse reject the value and exit 2 before the option ever
            # reached the code being tested, so this test passed for --by
            # while `qikly --by week` fell straight through to a real, billed
            # run. A guard that cannot see the thing it guards is worse than
            # no guard, because it is also reassuring.
            yield flag, [flag, str(sorted(action.choices)[0])]
        elif action.type is int:
            yield flag, [flag, "3"]
        else:
            yield flag, [flag, "x"]


def test_no_option_starts_a_run_on_its_own_unless_it_is_meant_to(tmp_path):
    """
    The enumeration, because three separate audits each found one of these by
    reading and none of them found all three.

    `--score-mutants`, `--artifacts-url` and `--json` each did nothing on their
    own, were in no dispatch branch, and were missing from the guard that
    refuses an option with nothing to attach to. So control fell through to the
    ordinary run, and with a provider key set each would have started a real,
    billed run over every task. One was reproduced by an audit that spent money
    doing it.

    Eyeballing a list of forty options finds one at a time. This runs them.

    Then a fourth, `--by`, got past the first version of this test, because
    that version probed every value-taking option with the literal string "x".
    For an option with `choices`, argparse rejects "x" and exits before the
    code under test is reached, so the test saw a refusal and called it a pass.
    It now probes with a value the option actually accepts.

    The signature is the same in every case: with no key set, a flag that
    reaches the run path dies at the provider check, and a flag that does its
    own job never gets there.
    """
    offenders = []
    for flag, arguments in _every_option():
        if flag in STARTS_A_RUN:
            continue
        done = _run(arguments, str(tmp_path))
        if "LLM configuration error" in (done.stdout + done.stderr):
            offenders.append(flag)

    assert not offenders, (
        "these options start a real run on their own, which spends money when "
        "a provider key is set: %s\nEither add each to the attachment guard "
        "in cli.py, or, if it really is meant to run unaccompanied, to "
        "STARTS_A_RUN with a reason." % ", ".join(sorted(offenders)))


def test_the_options_that_may_start_a_run_still_can(tmp_path):
    """
    The other half, so the guard cannot be made to pass by refusing
    everything.
    """
    for flag in sorted(STARTS_A_RUN):
        arguments = [flag, "x"] if flag == "--tasks" else [flag]
        done = _run(arguments, str(tmp_path))
        assert "LLM configuration error" in (done.stdout + done.stderr), (
            "%s no longer reaches a run, so either it was guarded by mistake "
            "or it belongs out of STARTS_A_RUN:\n%s"
            % (flag, (done.stdout + done.stderr)[-400:]))
