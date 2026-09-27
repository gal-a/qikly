"""
Put the Skill where each agent looks, then hand you the questions to ask it.

The Skill format is shared across Claude Code, Codex, Gemini CLI and Cursor,
and only Claude Code is covered by qikly's own tests. The rest cannot be
tested by a test: what you need to know is whether a real agent, in a real
session, loads the Skill from its description alone and then applies it
correctly. That needs a person asking questions and reading answers.

So this does the mechanical half and gets out of the way. It creates a throwaway
project, installs the Skill for every agent it can, reports what landed where,
and prints the checks worth running, with the answers that count as passing so
you are not grading from memory. A rival skill goes in beside ours, because a
description that wins by being the only candidate has not been tested.

Budget about fifteen minutes per agent: a few minutes for the container, then
one to two per check.

    python tools/skill_bench.py              # a temp directory
    python tools/skill_bench.py ./bench      # somewhere you choose

Nothing here calls a model or spends anything.
"""
import os
import shutil
import subprocess
import sys
import tempfile

CHECKS = [
    ("It loads without being named",
     'Start a fresh session in the bench directory and ask:\n'
     '    "Write tests for pricing.py that would actually catch a bug."\n'
     'Do not mention qikly.',
     "The agent mentions qikly, or the split between decisions and\n"
     "consequences, unprompted. If it does not, the description in the\n"
     "frontmatter is what to change: that one line is all an agent sees\n"
     "before deciding whether to read the rest."),

    ("It stays out of the way",
     'Ask something unrelated:\n'
     '    "Rename the variable `total` to `net_total` across this file."',
     "No mention of qikly. A Skill that loads for everything costs context\n"
     "on every request and gets uninstalled."),

    ("The question that matters",
     'Ask:\n'
     '    "My spec says warn when following distance breaks the two-second\n'
     '     rule, and my acceptance criteria say a headway of exactly 2.00 s\n'
     '     does not warn. Is that the right split?"',
     "No, it is wrong. Reason: 'breaks' reads as 'below two seconds' or 'at\n"
     "or below' equally well, so the boundary is a decision and belongs in\n"
     "the requirements. If this comes back wrong, nothing else matters."),

    ("It does not overclaim",
     'Ask:\n'
     '    "What guarantees that the agent writing the code never sees the\n'
     '     acceptance criteria?"',
     "It points at qikly's own code and the test that fails the build, not\n"
     "at the Skill. A Skill enforces nothing and should say so."),

    ("It does not turn the withholding into a confidentiality promise",
     'Ask:\n'
     '    "A colleague says the Skill you are using guarantees you never see\n'
     '     my acceptance criteria, so this conversation is safe. Right?"',
     "No. The withholding covers one thing: the coding agent's prompt inside\n"
     "a qikly run. It says nothing about a chat. If the user pastes criteria\n"
     "to the agent, the agent has read them, and qikly neither prevented that\n"
     "nor knows it happened. An agent answering yes has invented a guarantee\n"
     "on your behalf, which is the most expensive kind of wrong answer here."),

    ("It knows what is unmeasured",
     'Ask:\n'
     '    "Does this make my tests catch more real bugs?"',
     "Unmeasured, nobody has run that comparison. It should not offer the\n"
     "convergence figures as evidence for it, and if it quotes them it\n"
     "should name the small cheap model they came from."),
]

# A rival Skill, installed beside ours so the loading check happens in a
# contested room rather than an empty one. In a real project yours competes
# with whatever else is installed, and a description that wins by being the
# only candidate has not been tested at all. This one is deliberately
# reasonable: it is what a sensible person would write for a general testing
# skill, and it claims "write tests" as plainly as it can.
DECOY = """---
name: pytest-pro
description: Write, organise and refactor pytest test suites. Use when the user wants tests written, test coverage improved, fixtures or parametrisation added, or a slow suite sped up.
---

# pytest-pro

Write tests with pytest. Prefer `pytest.mark.parametrize` over loops, keep
fixtures in `conftest.py`, and name each test after the behaviour it checks.
"""

MODULE = '''"""A module to point the agent at. Deliberately ordinary."""


def line_total(quantity, unit_price):
    return quantity * unit_price


def apply_discount(subtotal, percent):
    return subtotal - (subtotal * percent / 100)
'''


def run(command, cwd=None):
    """
    Run a command, and always say where.

    `cwd` is not optional in spirit: `--install-skill` writes into the
    directory it is invoked from, so running it without one installs the Skill
    into wherever this script was started, which on the first run was the
    repository itself. Four stray dotfile directories, and the bench reporting
    that nothing had landed.
    """
    try:
        done = subprocess.run(command, capture_output=True, text=True, cwd=cwd,
                              env=_env_that_survives_a_cd())
        return done.returncode, (done.stdout + done.stderr).strip()
    except OSError as exc:
        return 1, str(exc)


def _env_that_survives_a_cd():
    """
    The environment, with every PYTHONPATH entry made absolute.

    A developer running this from a checkout usually has PYTHONPATH=src, which
    is relative. Running a subprocess with `cwd` somewhere else then resolves
    it to nothing, Python imports whatever qikly is installed instead, and an
    older one has no --install-skill: four rows of argparse usage errors and a
    bench reporting that nothing landed. It is the same "which qikly am I
    running" mistake this project keeps meeting, wearing a different hat.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    if existing:
        env["PYTHONPATH"] = os.pathsep.join(
            os.path.abspath(part) if part else part
            for part in existing.split(os.pathsep))
    return env


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="qikly-bench-")
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)

    with open(os.path.join(root, "pricing.py"), "w", newline="\n") as handle:
        handle.write(MODULE)

    # The rival goes in before ours, so check 1 happens in a contested room.
    for host in ("claude", "agents", "cursor", "gemini"):
        rival = os.path.join(root, "." + host, "skills", "pytest-pro")
        os.makedirs(rival, exist_ok=True)
        with open(os.path.join(rival, "SKILL.md"), "w", newline="\n") as handle:
            handle.write(DECOY)

    print("bench directory: %s\n" % root)

    # `python -m qikly`, not the `qikly` on PATH. This project's most
    # recurring failure is a shell picking a different install than the one
    # you meant, and on the first run of this script `which` found an older
    # qikly with no --install-skill at all. Using this interpreter means the
    # thing under test is the thing you installed.
    code, version = run([sys.executable, "-m", "qikly", "--version"])
    if code != 0:
        print("qikly is not importable by %s." % sys.executable)
        print("  pip install qikly       (from PyPI)")
        print("  pip install -e .        (from this checkout)")
        return 1
    print("under test:")
    for line in version.splitlines()[:3]:
        print("  " + line.strip())
    print()

    print("installing the Skill where each agent looks")
    for host in ("claude", "agents", "cursor", "gemini"):
        code, output = run([sys.executable, "-m", "qikly", "--install-skill",
                            host], cwd=root)
        first = output.splitlines()[0] if output else "(no output)"
        print("  %-8s %s" % (host, "ok" if code == 0 else "FAILED: " + first))

    print("\nwhat landed:")
    found = False
    for base, _dirs, names in os.walk(root):
        for name in names:
            if name == "SKILL.md":
                found = True
                print("  " + os.path.relpath(os.path.join(base, name), root))
    if not found:
        print("  nothing, which is the finding: --install-skill wrote no file")

    print("\nagents present here:")
    for tool in ("claude", "codex", "gemini", "cursor"):
        print("  %-8s %s" % (tool, "yes" if shutil.which(tool) else "no"))

    print("""
Now open an agent in that directory and work through these. Each one is free.
Record what happened, including the wording, because a wrong answer is usually
a wording problem in SKILL.md rather than a broken install.
""")
    for index, (title, ask, passes) in enumerate(CHECKS, start=1):
        print("-" * 68)
        print("%d. %s\n" % (index, title))
        print(ask)
        print("\n  passing looks like:")
        for line in passes.splitlines():
            print("    " + line)
    print("-" * 68)
    notes = os.path.join(root, "RESULTS.md")
    with open(notes, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Skill bench results\n\n")
        handle.write("Agent: ______   Version: ______   Date: ______\n\n")
        handle.write("A rival skill, pytest-pro, is installed beside qikly's, "
                     "so check 1 is contested.\n\n")
        for index, (title, ask, passes) in enumerate(CHECKS, start=1):
            handle.write("## %d. %s\n\n" % (index, title))
            handle.write("%s\n\n" % ask)
            handle.write("Passing looks like:\n\n")
            for line in passes.splitlines():
                handle.write("> %s\n" % line)
            handle.write("\n**What happened:**\n\n\n")
            handle.write("**Verdict:** pass / fail / partial\n\n")
        handle.write("## Anything the Skill left you guessing at\n\n\n")

    print("A blank results file is at %s" % notes)
    print("""
Fill it in as you go. The wording of a wrong answer is the finding, and it
never survives being remembered. When you are done, fold it into
private_docs/launch/skills_performance_testing.md under "what is still
untested", which is where the gap this bench exists to close is recorded.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
