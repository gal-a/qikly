# When a run does not converge

A stall is a normal outcome, not a broken tool. The run exits non-zero, names
the tests that blocked it, keeps the whole record, and ships nothing. Across
every measurement this project has taken, roughly four runs in ten stop this
way, and no run has ever reported success on code its own tests rejected.

So the question is never "why is it broken". It is which of a short list of
things is happening, and the list is short.

---

## Triage

Match what you saw to where to look.

| What the console showed | Most likely | Go to |
|---|---|---|
| `0 passed, 0 failed, 1 error` | The module will not import. No test ran at all | [4](#4-a-collection-error-means-nothing-ran) |
| The same test failing every iteration, no progress | A criterion fighting the model's priors, or a genuinely hard bug | [3](#3-the-same-patch-appearing-over-and-over) |
| Steady progress, then the budget ran out | Not enough attempts | [8](#8-give-it-more-attempts) |
| Integration and system pass, unit does not | Expected. Most stalls live here | [10](#10-expect-the-unit-stage-to-be-where-it-fails) |
| Everything suddenly worse than last week | A setting changed, not the tool | [9](#9-check-nothing-is-set-that-you-have-forgotten) |
| Poor on a provider you just set up | An entry-level model | [1](#1-try-a-stronger-model) |

---

## 1. Try a stronger model

This moves convergence more than anything else here, and it is one environment
variable.

```bash
export LLM_MODEL=gpt-4o          # or a larger model on your provider
qikly --tasks <MY_TASKS>         # e.g. --tasks CALC_TAX,MERGE_SALES
```

Every convergence figure in this project was measured on
`gemini-3.5-flash-lite`, a deliberately small and cheap model chosen so that
sweeps of hundreds of runs were affordable. Treat those figures as a floor.

An entry-level model on any provider may stall on a task a mid-tier one clears
comfortably. If you are evaluating qikly, evaluate it on a model you would
actually ship behind.

**What a bigger model buys, and what it costs.** On one CALC_TAX run,
`claude-sonnet-5` generated 44 tests against `gemini-3.5-flash-lite`'s 24, and
its suite rejected code that Gemini's suite accepted, on five tests, while
Gemini's suite accepted its code entirely. A stricter bar, in other words. It
also took 403 seconds against 31, and cost \$0.81 against \$0.005.

That trade is worth making deliberately rather than by default. A reasoning
model produces thinking tokens you are billed for and wait on, which is why the
cheapest model is the default here and why every published figure was measured
on it: a 400-run sweep costs about \$3 on the default and roughly \$320 on a
reasoning model.

**Use the cheap model to measure and the expensive one to work.** If you need a
convergence rate, take it on the default. If you need the strictest bar for one
important specification, pay for it once. One run of each is an anecdote, not a
comparison; the figures above are a single run per model.

## 2. Read what actually blocked it

Every run writes a timeline:

```
outputs/reports/iterations/<task>_<timestamp>_report.html
```

Open it in a browser. It shows every iteration, the FIX reasoning and the PATCH
diff for each failure, and, most usefully, **which patches applied cleanly and
changed nothing.** A run full of those is not a run that needs more attempts.
It is one of the next two problems.

## 3. The same patch appearing over and over

Identical diffs, not merely a repeated failure, is a specific signature: the
model is fighting something it correctly knows about the world.

Restrict a real-world field to an artificial subset, say three valid street
suffixes, and the model will keep widening the restriction back. Not out of
disobedience. Every piece of its training agrees that "Boulevard" is a street
suffix, and your criterion is the outlier. At temperature zero this does not
converge slowly; it does not converge at all.

**Fix:** widen the criterion to match reality, or move the restriction into
`requirements`, where the coding agent can read it and treat it as a given
rather than as an error to correct.

To confirm it, compare successive diffs under
`outputs/logs/patches/<task>/<timestamp>/`. Byte-identical patches mean this.
Different patches that never resolve the same test mean something else: a bug
that needs more than the failure text to fix, which is [1](#1-try-a-stronger-model).

## 4. A collection error means nothing ran

```
[MY_TASK] [stage 1/3] [iteration 3] 0 passed, 0 failed, 1 error, 0 skipped
```

No test failed, because no test ran. The module could not be imported. This is
a different problem from a wrong answer, and until it is fixed nothing else can
be assessed.

The FIX prompt is told this explicitly, and the report carries the underlying
`ImportError` or `SyntaxError`. The usual cause is a mismatch between what
`interface` declares and what the agent wrote, so check that
`interface.module` and the declared function signatures are exactly what the
tests should be importing.

## 5. Check the criteria and requirements do not contradict each other

```bash
qikly --check-criteria --tasks <MY_TASKS>
```

One model call per task, and it changes nothing. A criterion that no
implementation could satisfy alongside the requirements produces a stage that
spends its entire budget discovering that the slow way. It exits non-zero on a
contradiction, so a pipeline can gate on it.

## 6. Check the criteria name values, not adjectives

```bash
qikly --validate
```

Free, offline, and it flags criteria written as adjectives.

> "Reject large amounts" invites a test at some arbitrary large number.
> "100 is accepted and 101 is rejected" forces a test at the boundary.

This is the highest-leverage habit in writing a bar. A suite that never tests a
boundary cannot catch an error at that boundary, no matter how many other cases
it covers, and off-by-one at a boundary is among the oldest defect classes in
software.

`--validate` also catches the quiet structural mistakes: `acceptance_criteria`
written as one long string instead of a list, a `task_id` that disagrees with
its filename, and fixture paths that do not resolve. Each of those otherwise
surfaces twenty minutes and several dollars into a run.

## 7. Check your fixtures can reach every criterion

```bash
python -m qikly.orchestrator.tuning.propose_fixtures --tasks <MY_TASKS>
```

A criterion that no input row can trigger produces a test that passes whatever
the code does. The bar is not lower; part of it is absent.

Eight of the ten tasks bundled with qikly had at least one before this was run
on them, from one in `CALC_CALENDAR` to seven of thirteen in `MERGE_CONTACTS`.
Assume yours do too.

It writes proposals to a file and never edits your data.

## 8. Give it more attempts

`orchestrator.max_retries_per_stage` in `config/settings.yaml`, default 10.

Worth raising when the report shows steady progress that simply ran out of
room. Not worth raising when it shows the same patch repeating: that run will
fail identically with a hundred attempts, and cost ten times as much doing it.

## 9. Check nothing is set that you have forgotten

```bash
qikly --trends --by week
```

Convergence per task over time, from the run summaries already on disk. Every
period names the model and settings behind it, and a period where those changed
is marked.

This exists because of a specific, expensive mistake. `criteria_per_batch` in a
settings file controls how many acceptance criteria a single test-generation
call is shown. At `0` one call sees the whole bar. At `4` the bar is split into
batches and each gets its own call, so a long bar produces roughly three times
as many tests, and every run has three times as much to satisfy.

Left set from an earlier experiment, it made convergence appear to collapse
across nine tasks at once. Half a day went into diffing prompts, specs and
provider parameters before anyone looked at the override.

**A rate belongs to a tool, a model and a configuration together.** A rate that
moved when the configuration moved is not a finding.

## 10. Expect the unit stage to be where it fails

About twenty points of the gap between "passes integration and system" and
"passes everything" is the unit stage, consistently, across every sweep this
project has run.

The reason is structural rather than mysterious. Its suite is the largest, so
there is more to satisfy. It runs last, when the earlier stages already pass and
regression checks force them to keep passing, so a fix has the least room to
move. And it is the one stage whose tests are written with sight of the
implementation, so it can assert on incidental internal structure rather than on
required behaviour.

If behavioural verification is what you need, `orchestrator.test_order` in
settings can leave it out.

---

## One run is an artifact, not a rate

The same task with the same seed converges on some runs and not others. Before
concluding anything about a task, a model or a setting:

```bash
python -m qikly.orchestrator.run_all --tasks <MY_TASKS> --repeat 10 \
    --skip-eval --skip-refine
```

That writes an aggregate with a confidence interval instead of a pass count.
Ten runs is usually enough to tell a real difference from noise, and it is
worth knowing that at n=10 the intervals are wide: this project has measured
the same unchanged task at 72% and then 90% on consecutive sweeps.

If a change looks like an improvement after one run, it is not yet evidence of
anything.

---

## Still stuck

The run kept everything. `outputs/logs/transactions_<task>_<timestamp>.jsonl`
is an append-only record of every test run, every FIX, every PATCH and every
apply outcome, and it is the source of truth that the reports are rendered
from.

Issues and results are welcome:
[github.com/gal-a/qikly/issues](https://github.com/gal-a/qikly/issues).
