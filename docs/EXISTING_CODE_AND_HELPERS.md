# Pointing qikly at code you already have

What qikly can see, what it can change, and what happens when the defect turns
out to be somewhere it may not write. Split out of [FAQ.md](FAQ.md) because the
answer outgrew a FAQ entry.

The YAML for everything below is in
[TASK_FILE_REFERENCE.md](TASK_FILE_REFERENCE.md); this page is the reasoning.

## qikly does not go looking for your code

There is no discovery step. qikly does not scan your repository and work out
what is available, so it will not find your driver or parser classes on its
own. What the test-writing agent targets is what the task file's `interface`
block declares, plus the requirements and the acceptance criteria. You describe
the surface.

Two things make that less manual than it sounds:

- **`qikly --scaffold path/to/module.py`** reads the real signatures out of a
  file you point it at and writes the `interface` block for you.
- **`seed.implementation`** points the run at code you already have, and
  **`seed.tests`** keeps a suite you already trust, per stage, so the loop
  repairs code against your tests rather than against generated ones.

## Can the tests import my other classes once they exist?

Yes, with one condition. Each stage runs as `python -m pytest` from your
project root, which puts the project root on `sys.path`. So a package sitting
at the project root, or one installed into the same virtualenv, imports
normally from both the generated tests and the generated implementation.

A package in a subdirectory that is not on the path does not. The run stops
with `no test ran: the module could not be imported`, and no amount of
iterating fixes it because the problem is the path rather than the code. Put
the directory on `PYTHONPATH`, or `pip install -e .` your own package.

## What it can read, and what it can change, are decided by the seed

`seed.implementation` takes a directory as well as a file. A directory is
treated as a package: it is copied in under its own name and becomes
importable by that name, so `from mypkg.money import to_cents` resolves as it
does in your own tree.

| | Inside the seed | Outside it |
|---|---|---|
| Imports at runtime | Yes | Yes, if on `sys.path` as above |
| The coding agent **sees the source** | Yes | No. It reasons about them from their behaviour |
| The coding agent **may write** to them | Yes | No |

**The seed is the boundary you choose, and that is deliberate.** qikly does not
follow your imports and decide for itself which of your files an agent may
rewrite: the transitive closure of a real package has no natural edge, and "it
rewrote a shared module I never named" is a worse outcome than naming a folder.
So put inside the seed what you want worked on, and leave a vendor library, or
a large shared module you do not want touched, outside it.

## When the defect is outside the seed

A test that fails because your `utils.py` is wrong does fail, correctly, which
is the point. But the agent cannot patch a file outside the seed, so left to
itself it would either stop without converging or change a module it does own
to work around a defect that is somewhere else.

From 0.5.5 a run says which of those happened, rather than leaving you to infer
it from a patch history:

- **At the start**, if the task's module imports anything local it may not
  write, one line names those files. It is information, not a warning: they
  import and run normally, and most of the time they are fine.
- **When a run stops without converging**, the message names the file instead
  of ending at "exceeded 10 attempts".
- **When a run passes but a failure along the way was traced into one of those
  files**, it says so, because a green suite reached that way may be green
  because the code was bent around a defect that is still there. **This is the
  one worth reading twice.**

**Nothing here stops or slows a run.** A project with shared helpers is normal,
and runs in one converge exactly as before. The guard only speaks up.

If it was not what you wanted, the fix is usually one line: seed the package
that holds `utils.py` instead of the single module.

## `--score-code` has no such limit

It neither writes code nor calls a model. Point it at a package and it plants
faults throughout it, helpers included, and tells you which ones your suite
noticed. No task file, no seed, nothing of yours modified.

## One thing worth knowing before you start

The loop reruns pytest on every iteration, so it suits the deterministic layer
best. Protocol parsing is a good fit: bytes in, structured records out, driven
from recorded captures. Code talking to live hardware is better left behind the
test doubles you already have, because a suite that needs a rig attached is a
suite the loop cannot rerun freely.
