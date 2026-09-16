# When a run does not converge

A stall is a normal outcome, not a broken tool. The run exits non-zero, names
the tests that blocked it, keeps the whole record, and ships nothing. Across
every measurement this project has taken, roughly four runs in ten stop this
way, and no run has ever reported success on code its own tests rejected.

So the question is never "why is it broken". It is which of a short list of
things is happening, and the list is short.

---

## Triage

Match what you saw to where to look. The rows are in the order to work through
them: the one change that moves convergence most, then the checks that settle
what happened, then fixes to the task file, and only then more attempts.

| What you saw | Section | What to do |
|---|---|---|
| Poor results on a provider you just set up, or on the default model | [1. Try a stronger model](#1-try-a-stronger-model) | Set `LLM_MODEL` to a mid-tier or larger model and run again |
| Any stall, before changing the task file | [2. Read what actually blocked it](#2-read-what-actually-blocked-it) | Change nothing yet: this step decides what to change. In the run's `_report.html` timeline, byte-identical patches go to [5](#5-the-same-patch-appearing-over-and-over), an import or syntax error to [3](#3-a-collection-error-means-nothing-ran), steady progress to [10](#10-give-it-more-attempts), and different patches that never fix the same test to [1](#1-try-a-stronger-model) |
| `0 passed, 0 failed, 1 error` | [3. A collection error means nothing ran](#3-a-collection-error-means-nothing-ran) | Make `interface.module` and the declared signatures match what the tests import |
| Everything suddenly worse than last week | [4. Check nothing is set that you have forgotten](#4-check-nothing-is-set-that-you-have-forgotten) | Run `qikly --trends --by week` and look for a setting that changed, such as `criteria_per_batch` |
| The same test failing every iteration, no progress | [5. The same patch appearing over and over](#5-the-same-patch-appearing-over-and-over) | Move the restriction into `requirements`, or widen the criterion to match reality |
| Stopped with a message naming two tests, each fix for one breaking the other | [6. Two generated tests disagree](#6-two-generated-tests-disagree) | Compare the two tests with the acceptance criteria. If one contradicts a criterion, run again without `--resume` so the suites are written and checked again, and leave a correct spec alone |
| A stage spends its whole budget and never gets closer | [7. Check the criteria and requirements do not contradict each other](#7-check-the-criteria-and-requirements-do-not-contradict-each-other) | Run `qikly --check-criteria --tasks <MY_TASKS>` and correct whichever statement is wrong |
| Tests check arbitrary values rather than the boundary | [8. Check the criteria name values, not adjectives](#8-check-the-criteria-name-values-not-adjectives) | Run `qikly --validate` and rewrite each flagged criterion as a value: "100 is accepted and 101 is rejected" |
| A test passes whatever the code does | [9. Check your fixtures can reach every criterion](#9-check-your-fixtures-can-reach-every-criterion) | Run `propose_fixtures` and add the input rows it suggests |
| Steady progress, then the budget ran out | [10. Give it more attempts](#10-give-it-more-attempts) | Raise `orchestrator.max_retries_per_stage` (default 10), only when the report shows progress |
| Integration and system pass, unit does not | [11. Expect the unit stage to be where it fails](#11-expect-the-unit-stage-to-be-where-it-fails) | Expected. Accept it, or leave the unit stage out with `orchestrator.test_order` |

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
It is [3](#3-a-collection-error-means-nothing-ran) or
[5](#5-the-same-patch-appearing-over-and-over).

## 3. A collection error means nothing ran

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

## 4. Check nothing is set that you have forgotten

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

## 5. The same patch appearing over and over

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

## 6. Two generated tests disagree

```
Stopped on stage 'system' after 4 attempts: the last three patches alternated
between the same two diffs. [...] The failing tests alternate between
test_run_headway_two_second_rule_warning and test_integration_pipeline_flow in
the 'system' and 'integration' suites: each fix for one breaks the other [...]
```

Each patch makes one test pass and the other fail, because the two tests expect
different results for the same input. No code can pass both, so more attempts
cannot help, and the fault is in the tests rather than the specification. In
the run behind this section, an integration test warned at exactly 2.00 seconds
of headway and a system test did not, against a criterion saying exactly 2.00
seconds raises no warning.

The same mistake can also be made identically in both suites. Then they agree
with each other and still contradict the criterion, the run fails without this
message, and the place to look is the same: each test's comparison at every
limit the criteria state.

An opt-in check, `check_suites: true` under `test_generation` in settings,
looks for these before any code is written and rewrites a suite once. Measured
on one task it found every wrong suite but did not raise convergence, and a
wrong finding once led a correct suite to be rewritten wrong, so it is off by
default.

**Fix:** compare the two named tests with the acceptance criteria. If one
contradicts a criterion, run again without `--resume`, so the suites are written
and checked again. Do not change a specification that is already right: this is
the one stall where the spec is not the problem.

To check suites already on disk without a run, one model call per task:

```bash
python -m qikly.orchestrator.tuning.check_suites --tasks <MY_TASKS>
```

## 7. Check the criteria and requirements do not contradict each other

```bash
qikly --check-criteria --tasks <MY_TASKS>
```

One model call per task, and it changes nothing. A criterion that no
implementation could satisfy alongside the requirements produces a stage that
spends its entire budget discovering that the slow way. It exits non-zero on a
contradiction, so a pipeline can gate on it.

## 8. Check the criteria name values, not adjectives

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

## 9. Check your fixtures can reach every criterion

```bash
python -m qikly.orchestrator.tuning.propose_fixtures --tasks <MY_TASKS>
```

A criterion that no input row can trigger produces a test that passes whatever
the code does. The bar is not lower; part of it is absent.

Eight of the ten tasks bundled with qikly had at least one before this was run
on them, from one in `CALC_CALENDAR` to seven of thirteen in `MERGE_CONTACTS`.
Assume yours do too.

It writes proposals to a file and never edits your data.

## 10. Give it more attempts

`orchestrator.max_retries_per_stage` in `config/settings.yaml`, default 10.

Worth raising when the report shows steady progress that simply ran out of
room. Not worth raising when it shows the same patch repeating: that run will
fail identically with a hundred attempts, and cost ten times as much doing it.

## 11. Expect the unit stage to be where it fails

About twenty points of the gap between "passes integration and system" and
"passes everything" is the unit stage, consistently, across every sweep this
project has run.

The reason is structural rather than mysterious: the unit suite is the largest,
runs last, and is the only one written with sight of the implementation.
[design_2_performance.md](https://github.com/gal-a/qikly/blob/main/docs/design_2_performance.md#nearly-the-whole-gap-between-those-two-numbers-is-the-unit-stage)
has the full explanation.

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
