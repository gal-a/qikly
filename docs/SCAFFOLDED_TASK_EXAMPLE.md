# A scaffolded task, start to finish

```bash
qikly --example
```

That puts the whole example in your project, ready to run:

| Written to | What it is |
|---|---|
| `my_metrics.py` | The module you already have. Four functions, no implementation: scaffold reads signatures, never bodies. Each body carries a `TODO` saying what is expected there |
| `inputs_private/config/tasks/MY_METRICS_VERIFY.yaml` | What `qikly --scaffold my_metrics.py` writes. Tests the code you already have, so it carries a `seed:` block pointing back at the module |
| `inputs_private/config/tasks/MY_METRICS.yaml` | What `qikly --scaffold my_metrics.py --fresh` writes. A fresh implementation of the same interface, so no `seed:` block |
| `inputs_private/data/MY_METRICS/input_01.csv` | Sample input data, first file |
| `inputs_private/data/MY_METRICS/input_02.csv` | Sample input data, second file |

It never overwrites, so running it twice is safe and your edits survive. Then:

```bash
qikly --validate --tasks MY_METRICS_VERIFY    # free, no model call
qikly --tasks MY_METRICS_VERIFY
```

`--validate` will warn that `requirements` and `acceptance_criteria` are still
`TODO`. That is the example working as intended: those two sections are the
ones only you can write, and [the quick
start](QUICK_START_ON_YOUR_OWN_DATA.md#getting-the-two-halves-right) has the
rule for telling them apart.

## Why these files exist

Nothing here is illustrative. The two YAML files are the verbatim output of
`qikly --scaffold` run on `my_metrics.py`, and `tests/test_scaffold_examples.py`
regenerates them and fails if they drift, so what you open is what scaffold
writes today rather than what it wrote once.

The copies that ship live under [`src/qikly/inputs_public/examples/`](../src/qikly/inputs_public/examples),
laid out the way a real project is rather than as a flat folder of samples, so
the paths you read there are the paths `--example` writes them to. They
sit under `examples/` rather than beside the bundled tasks deliberately: a
scaffolded pair breaks three rules the bundled tasks keep. `MY_METRICS_VERIFY`
ends in the suffix reserved for scaffolding, the pair shares one data folder
where bundled ids map one to one, and both files still carry the `TODO`s that
are the whole point of an example. Keeping it out of the task list also keeps
`qikly --validate` quiet for everyone who never asked for the example.

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

Both arrive with `requirements` and `acceptance_criteria` as `TODO`, and they
stay that way on purpose. Scaffold could read plausible criteria out of the
implementation, and deliberately does not: criteria derived from code can only
describe what that code already does, which is a bar it passes by
construction.

What each `TODO` does carry is an `e.g.` showing the shape of a useful answer.
That is fixed template text, not something read out of your module, so replace
it rather than editing around it.

## About the sample data

The `inputs:` list in a scaffolded task names one file,
`inputs_private/data/MY_METRICS/input_01.csv`, because scaffold cannot know how
many you have. Add the rest yourself; the second file here is what that looks
like once you do.

Look at what is in them, because it is the part people get wrong. Between the
two files there are readings that are clean, a missing temperature, a
non-numeric temperature, a humidity above 100, and a malformed timestamp. That
is deliberate: **a criterion no row can trigger is a criterion nothing checks.**
A suite written against data containing only clean readings will pass whatever
the code does about bad ones, and report nothing about the rule you cared most
about. Two thirds of the faults this project planted in its own research went
unnoticed for exactly that reason.

So when you copy your own data in, check that something in it reaches every
criterion you wrote. These two files are sample rows, not a template: replace
them wholesale with a real sample of your own.
