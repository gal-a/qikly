# Worked examples of the three steps

Two small projects to try `qikly --score`, `--scaffold` and `--tasks` on,
each with the task files as they look once the questions are answered.

| Example | What it shows |
|---|---|
| [`pricing/`](pricing/) | One module, `pricing.py`, with two passing tests |
| [`shop_folder/`](shop_folder/) | A package of two modules, one importing the other, run as a folder |

These are not qikly's bundled tasks. Nothing here is run by qikly, and
nothing here is a task until you scaffold it in your own copy.

## Try one

Copy the example folder somewhere outside this repository, leaving out
`answered/`, which is the end state to compare against, then run the steps
from inside the copy:

```bash
qikly --score pricing.py              # shop_folder: qikly --score shop
qikly --scaffold pricing.py           # writes inputs_private/config/tasks/PRICING_VERIFY.yaml
# answer the questions in that file: see answered/ for one way to
qikly --validate pricing.py           # free, no key
qikly --tasks pricing.py              # needs an API key, about $0.002 on Gemini
qikly --take-tests pricing.py         # the new tests, run on your own pricing.py
```

For the folder example, use `shop` in place of `pricing.py` in every step:
`--scaffold shop` writes one task file per module, `PRICING_VERIFY.yaml` and
`RULES_VERIFY.yaml`, each seeded with the whole package so `from .rules
import MAX_RATE` works in qikly's copy.

## What `answered/` holds

The task files `--scaffold` wrote, with each TODO line replaced by an
answer, quotes kept, and the `requirements` line replaced with what the
module is for. The `#?` lines above each answer are the questions and what
the code does there now; neither agent reads them.

- `pricing/answered/PRICING_VERIFY.yaml` answers all six questions. The one
  that matters is `apply_discount(100, 100) raises ValueError`: the code
  returns 0.0 there, so the copied tests fail on it, which is the finding.
- `shop_folder/answered/RULES_VERIFY.yaml` leaves one question as TODO, to
  show that a run skips it and `--validate` counts it.

Your own answers can differ: they are decisions about what the code should
do, and these are one owner's. The dates and line numbers in the `#?` notes
are from the run that wrote them.
