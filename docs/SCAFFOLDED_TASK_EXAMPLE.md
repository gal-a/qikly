# A scaffolded task, start to finish

```bash
qikly --example
```

That puts the whole example in your project, ready to run:

| Written to | What it is |
|---|---|
| `my_metrics.py` | The module you already have. Four functions, no implementation: scaffold reads signatures, never bodies. Each body carries a `TODO` saying what is expected there |
| `inputs_private/config/tasks/MY_METRICS_VERIFY.yaml` | What `qikly --scaffold my_metrics.py` writes, with the two human sections filled in. Tests the code you already have, so it carries a `seed:` block pointing back at the module |
| `inputs_private/config/tasks/MY_METRICS.yaml` | The same, as `qikly --scaffold my_metrics.py --fresh` writes it. A fresh implementation of the same interface, so no `seed:` block |
| `inputs_private/data/MY_METRICS/input_01.csv` | Sample input data, first file |
| `inputs_private/data/MY_METRICS/input_02.csv` | Sample input data, second file |

It makes the `inputs_private/` layout first if you have not run `--init`,
and leaves out that command's blank `MY_FIRST_TASK` starter, so the
example is the only task in your project.

It never overwrites, so running it twice is safe and your edits survive. Then:

```bash
qikly --validate --tasks MY_METRICS_VERIFY    # free, no model call
qikly --tasks MY_METRICS_VERIFY
```

`--validate` reports the task clean, with nothing left to fill in. That is
the one way this differs from scaffolding your own module: scaffold leaves
`requirements` and `acceptance_criteria` as `TODO`, because neither can be
derived from code, and here they are written so you can read a finished
pair. [The quick
start](QUICK_START_ON_YOUR_OWN_DATA.md#getting-the-two-halves-right) has
the rule for telling the two apart.

## Why these files exist

Nothing here is illustrative. Everything in the two YAML files that scaffold
decides is the output of `qikly --scaffold` run on `my_metrics.py`: the task
id, the module path, the signatures, the output path and the `seed:` block.
`tests/test_scaffold_examples.py` regenerates both files and fails if any of
that drifts, so what you open is what scaffold writes today rather than what
it wrote once. What it cannot regenerate is `requirements` and
`acceptance_criteria`, which are written here rather than left as `TODO`,
and a second test holds them to having nothing left to fill in.

The copies that ship live under [`src/qikly/inputs_public/examples/`](../src/qikly/inputs_public/examples),
laid out the way a real project is rather than as a flat folder of samples, so
the paths you read there are the paths `--example` writes them to. They
sit under `examples/` rather than beside the bundled tasks deliberately: a
scaffolded pair breaks two rules the bundled tasks keep. `MY_METRICS_VERIFY`
ends in the suffix reserved for scaffolding, and the pair shares one data
folder where bundled ids map one to one. Keeping it out of the bundled task
list also keeps `qikly --validate` quiet for everyone who never asked for the
example. Once `--example` copies it in, it is an ordinary task in your
project like any other, and a bare `qikly` with no `--tasks` will run it.

## What to look at in the two task files

They differ in one thing that matters. `diff` them and almost everything is the
task id and the paths derived from it. The real difference is the last block:
`MY_METRICS_VERIFY.yaml` ends with

```yaml
seed:
  implementation: "my_metrics.py"
```

and `MY_METRICS.yaml` ends with a comment saying there is no `seed:` block, so
a run writes the implementation itself. That one block is the whole difference
between "check this code" and "write this code and check it".

Both arrive with `requirements` and `acceptance_criteria` written, which is
the one thing scaffold cannot do for your own module. Scaffold could read
plausible criteria out of an implementation, and deliberately does not:
criteria derived from code can only describe what that code already does,
which is a bar it passes by construction. So when you scaffold your own
module those two sections arrive as `TODO`, each carrying an `e.g.` showing
the shape of a useful answer, and the pair here is what a filled in version
looks like.

Read the criteria against the requirements above them. Every one names a
boundary value, and none of them restates a decision: that a humidity of 100
is the last usable one follows from the requirement that the range is 0 to
100, and could not be guessed from it by someone who had not been told where
the range ends.

## About the sample data

The `inputs:` list in a scaffolded task names one file,
`inputs_private/data/MY_METRICS/input_01.csv`, because scaffold cannot know
how many you have. Add the rest yourself; the example names both of its
files, which is what that looks like once you do.

Look at what is in them, because it is the part people get wrong. Between the
two files there are readings that are clean, a missing temperature, a
non-numeric temperature, a humidity of exactly 100 and one above it, a
temperature of exactly 0.0, a negative temperature, and a malformed
timestamp. Every one of those is the boundary named by one of the six
acceptance criteria, and a test in `tests/test_scaffold_examples.py` fails if
a criterion loses the row that reaches it. That is deliberate: **a criterion
no row can trigger is a criterion nothing checks.**
A suite written against data containing only clean readings will pass whatever
the code does about bad ones, and report nothing about the rule you cared most
about. Two thirds of the faults this project planted in its own research went
unnoticed for exactly that reason.

So when you copy your own data in, check that something in it reaches every
criterion you wrote. These two files are sample rows, not a template: replace
them wholesale with a real sample of your own.
