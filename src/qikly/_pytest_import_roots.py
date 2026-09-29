"""
A pytest plugin qikly loads into its own test subprocess, and nowhere else.

## The problem it exists for

`python -m pytest` puts the working directory at the front of `sys.path`. The
working directory is the project root, which is where the user's own code
lives. So when a task's implementation is seeded as a package, the original
`mypkg/` at the project root **shadows the copy the run installed** into
`outputs/agent_src/code/<task_id>/mypkg/`.

Everything then looks like it is working and none of it is. The generated
suite imports the user's own package, the coding agent repairs a copy nobody
imports, every patch applies cleanly and no test outcome ever changes. On the
run that found this, four tests failed identically for eleven iterations while
correct patches landed each time: the file on disk said `"reason": "quantity"`
and the assertion read `'quantity is not usable'`, which was the untouched
original. A user would see ten iterations of spend and a passing-looking diff
against code that was never under test.

## Why a plugin rather than a conftest.py

A `conftest.py` written into the generated tests directory would work, and it
was the first design. It was dropped because `seed.tests` lets a user install
their own suite into that directory, a `conftest.py` of theirs may already be
sitting there, and there is only one such filename. Every resolution to that
collision involved either overwriting a file the user wrote or editing it in
place, and a test harness that rewrites your files to fix its own import order
is a worse bargain than the bug.

Nothing is written anywhere for this. The plugin is named on pytest's command
line with `-p` and reads one environment variable, both of which are set only
for a run whose implementation is a seeded package. For every other run the
flag is absent, the variable is unset, and this module is never imported.

## Why the paths go in front

They have to beat the working directory, which is the entry doing the
shadowing, and it is first. Anything appended, `PYTHONPATH` included, sits
behind it and changes nothing, which is why `PYTHONPATH` alone did not fix
this.
"""
import os
import sys


ENV_VAR = "QIKLY_IMPORT_ROOTS"


def _install(value):
    """Put each root at the front of `sys.path`, first one first.

    Reversed because each insert goes to position 0, so inserting the list
    backwards leaves it in the order it was given. Any existing copy of a
    root is removed rather than duplicated, so a re-import cannot slowly grow
    `sys.path` across a run's many pytest invocations.
    """
    roots = [r for r in (value or "").split(os.pathsep) if r.strip()]
    for root in reversed(roots):
        resolved = os.path.abspath(root)
        while resolved in sys.path:
            sys.path.remove(resolved)
        sys.path.insert(0, resolved)
    return [os.path.abspath(r) for r in roots]


def pytest_configure(config):
    """
    pytest's own hook, and deliberately not module-level code.

    An earlier version called `_install` on import. An audit on 2026-09-29
    showed that claim about "never imported otherwise" to be simply wrong:
    `run_tests.py` imported this module to read its name, `orchestrator.py`
    imports `run_tests`, and every qikly invocation imports the orchestrator.
    So `QIKLY_IMPORT_ROOTS` left in a shell, which the tests of this very
    feature export, reordered `sys.path` in the CLI's own process on any
    command at all, `--version` included.

    A hook cannot do that. It runs only when pytest has actually loaded this
    as a plugin, which is only when qikly put `-p` on the command line, and
    it runs before collection, which is before any test module is imported.
    Importing this module now has no effect whatsoever.
    """
    _install(os.environ.get(ENV_VAR))
