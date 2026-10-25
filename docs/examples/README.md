# Worked examples of the three steps

Two small projects to try `qikly --score`, `--scaffold` and `--tasks` on.
Each has a `README.md`, which is what qikly's spec agent reads to draft the
task file, and holds its task files three ways under `task_files/`.

| Example | What it shows |
|---|---|
| [`pricing/`](pricing/) | One module, `pricing.py`, with two passing tests |
| [`shop_folder/`](shop_folder/) | A package of two modules, one importing the other, run as a folder |

These are not qikly's bundled tasks. Nothing here is run by qikly, and
nothing here is a task until you scaffold it in your own copy.

## Try one

Copy the example folder somewhere outside this repository, leaving out
`task_files/`, set a key such as `GEMINI_API_KEY`, then run the steps from
inside the copy:

```bash
qikly --score pricing.py              # shop_folder: qikly --score shop
qikly --scaffold pricing.py           # drafts inputs_private/config/tasks/PRICING_VERIFY.yaml
# read the draft, especially anything marked CHECK, and change what you disagree with
qikly --validate pricing.py           # free
qikly --tasks pricing.py              # about $0.002 on Gemini
qikly --take-tests pricing.py         # the new tests, run on your own pricing.py
```

For the folder example, use `shop` in place of `pricing.py` in every step:
`--scaffold shop` writes one task file per module, `PRICING_VERIFY.yaml` and
`RULES_VERIFY.yaml`, each seeded with the whole package so `from .rules
import MAX_RATE` works in qikly's copy.

## The README is the spec agent's source

With a key set, `--scaffold` has a spec agent draft the `requirements` line
and an answer to each question from the project's README and the module's
docstrings. It never reads the code, so it writes what the code should do,
not what it does. Each answer says where it came from:

```yaml
  #? What should apply_discount(100, 100) do?
  #? Answer below drafted by qikly from your README or docstrings: "...so a rate of 100 or more is rejected with ValueError". Keep it, or change it.
  - "apply_discount(100, 100) raises ValueError"
```

or, where nothing written decides it, `#? CHECK: your docs don't say. The
answer below is qikly's guess from what the module is for. Read it before you
run.`, for you to read first. `pricing.py` accepts a rate of exactly 100,
so that drafted answer is what step 3 finds: the copied tests fail on it.

## Answering what the draft leaves

What the documentation cannot decide is left as a TODO. Replace it with any
of these, with or without quotes, or leave it, and a run skips it:

```yaml
  - 2                                          # option 2, where qikly lists options
  - 1: 0.0                                     # option 1, with your value
  - keep                                       # what your code does now, where one is shown
  - apply_discount(100, 100) raises ValueError # or your own sentence, naming a value
```

A sentence of your own that has a colon and a space in it needs its quotes,
as any YAML string does. `qikly --validate` prints each short answer as the
criterion it becomes.

## The three versions in `task_files/`

- `PRICING_VERIFY.yaml` is the file `--scaffold` writes without a key: every
  answer a TODO, and the `requirements` line marked `TODO: MODIFY THIS:`.
- `PRICING_VERIFY.drafted.yaml` is the file it writes with a key, as the spec
  agent drafted it from the README, run on 2026-10-22 with Gemini. In
  `pricing/` it drafted all six answers, one marked `CHECK`.
- `PRICING_VERIFY.answered.yaml` is the no-key file answered by hand: by
  number, by number and value, and with `keep`, quoted and not.
  `shop_folder/`'s also answers one question with a sentence, and its
  `RULES_VERIFY.answered.yaml` leaves one as TODO, to show a run skips it.

Your own answers can differ: they are decisions about what the code should
do. The dates and line numbers in the `#?` notes are from the run that wrote
them, and a spec agent's draft can differ from run to run and model to model.
