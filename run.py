#!/usr/bin/env python
"""
`python run.py` from a git clone. Deliberately a shim: the real entry point
is src/qikly/cli.py, which is also what the installed `qikly`
command calls, so a clone and an install run the same code down to the line.

The sys.path line is what a src layout costs: with the package under src/
rather than at the repo root, it is not importable from a plain checkout.
That is the layout working as intended -- it means an installed copy can
never be shadowed by the source tree -- but a clone still has to be runnable
without `pip install -e .` first, so this puts src/ on the path explicitly.

Not shipped in the wheel: a top-level module named `run` in site-packages is
exactly the kind of name collision that nesting under qikly/ ended.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from qikly.cli import main

if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
