# Worked examples of the three steps

Two small projects to try `qikly --score`, `--scaffold` and `--tasks` on.
Each holds its task files twice, under `task_files/`: as `--scaffold` writes
them, and as they look once answered.

| Example | What it shows |
|---|---|
| [`pricing/`](pricing/) | One module, `pricing.py`, with two passing tests |
| [`shop_folder/`](shop_folder/) | A package of two modules, one importing the other, run as a folder |

These are not qikly's bundled tasks. Nothing here is run by qikly, and
nothing here is a task until you scaffold it in your own copy.

## Try one

Copy the example folder somewhere outside this repository, leaving out
`task_files/`, then run the steps from inside the copy:

```bash
qikly --score pricing.py              # shop_folder: qikly --score shop
qikly --scaffold pricing.py           # writes inputs_private/config/tasks/PRICING_VERIFY.yaml
# answer the questions in that file
qikly --validate pricing.py           # free; shows each short answer as its criterion
qikly --tasks pricing.py              # needs an API key, about $0.002 on Gemini
qikly --take-tests pricing.py         # the new tests, run on your own pricing.py
```

For the folder example, use `shop` in place of `pricing.py` in every step:
`--scaffold shop` writes one task file per module, `PRICING_VERIFY.yaml` and
`RULES_VERIFY.yaml`, each seeded with the whole package so `from .rules
import MAX_RATE` works in qikly's copy.

## Answering a question

Each question lists what your code does beside the value in question,
numbered, and a TODO line under it. Replace the TODO line with any of these,
with or without quotes:

```yaml
  #? What should apply_discount(100, 100) do?
  #? Answer with a number, found by running your code:
  #?   1 = apply_discount(100, 100) returns VALUE   (write it as 1: the value; ...)
  #?   2 = apply_discount(100, 100) raises ValueError   (as rate 101 does now)
  - 2                                          # option 2
  - 1: 0.0                                     # option 1, with your value
  - keep                                       # what your code does now, where one is shown
  - apply_discount(100, 100) raises ValueError # or your own sentence, naming a value
```

`qikly --validate` prints each short answer as the criterion it becomes. A
sentence of your own that has a colon and a space in it needs its quotes, as
any YAML string does. A TODO you leave is skipped. Replace the `requirements` line too, marked
`TODO: MODIFY THIS:`, with what the module is for in your own words.

## The two versions in `task_files/`

- `PRICING_VERIFY.yaml` is the file as `--scaffold` wrote it.
- `PRICING_VERIFY.answered.yaml` is the same file answered: by number, by
  number and value, and with `keep`, quoted and not. `shop_folder/`'s also
  answers one question with a sentence of its own, where qikly had no
  options to offer.

In `pricing/`, the answer that matters is `apply_discount(100, 100) raises
ValueError`: the code returns 0.0 there, so the copied tests fail on it,
which is the finding. In `shop_folder/`, `RULES_VERIFY.answered.yaml`
leaves one question as TODO, to show that a run skips it and `--validate`
counts it.

Your own answers can differ: they are decisions about what the code should
do, and these are one owner's. The dates and line numbers in the `#?` notes
are from the run that wrote them.
