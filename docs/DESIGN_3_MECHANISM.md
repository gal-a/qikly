<!--
One of three. See MAINTAIN.md: these three files, README.md, docs/index.html
and the investor deck move together. A number changed here has to change in
all of them.
-->

# How it is built, and how to use it

**Part 3 of three.** [Part 1](DESIGN_1_CASE_STUDY.md) makes the case and shows
one repair end to end. [Part 2](DESIGN_2_PERFORMANCE.md) reports what was
measured. This part is the architecture: what separates it from the
alternatives, the five agents, and the command to run for whichever parts of a
task file you already have.


---

**This is part 3 of three.**

| | | |
|---|---|---|
| [1. The case](DESIGN_1_CASE_STUDY.md) | [2. How well it works](DESIGN_2_PERFORMANCE.md) | **3. How it is built** (you are here) |

## What makes this different

**The tests come from the standard, not from the code.** This is the one that matters most. Every other AI test generator in this space derives its tests from an implementation that already exists: it reads the code to decide what to assert, which produces an excellent regression harness that locks in current behaviour. qikly writes the integration and system suites from the acceptance criteria **before any implementation exists**, so there is nothing for the standard to be shaped by. That is why a green suite here carries information: the tests describe what the code should do, not what it already does.

**The withholding is a mechanism you can watch, not a promise.** The criteria are cut out of the file in code, before the FIX and PATCH prompts are assembled, so no representation of them exists in the coding agent's context. `qikly --explain <MY_TASK>` prints what test generation receives, what the coding agent receives, and the difference between them, from a plain install with no API key. A test fails the build if any call site lets a criterion through, including one added next year by someone who has never read this page.

**What you get is an executable suite you keep.** Real pytest files, plus JUnit XML for whatever tracks tests where you work. Read them, run them, put them in continuous integration, and when one fails in six months it fails for a reason you can inspect and argue with. A suite is a durable asset in a way a model's verdict is not: a verdict cannot be re-run against tomorrow's commit.

**It helps with writing the standard, not just checking against it.** `--scaffold` turns code you already have into a task file, `--criteria-from` reads criteria straight out of the ticket that already holds them, `--generate-criteria` drafts a first bar from requirements alone, `--check-criteria` looks for a requirement and a criterion that no implementation could satisfy at once, and the refinement loop reviews converged code to propose criteria the first draft missed. Whether that last step produces a measurably *sharper* bar is an open question this project is still working on.

**Every run is reproducible, and the whole trail is kept.** A run records
the provider, the model, the settings and the version that produced it, next to
every failing test, every FIX with its stated root cause, and every PATCH as a
diff. You can read back exactly why a line of code exists: which assertion
forced it, what the model concluded, and what it changed. That record is what
makes a convergence rate a measurement rather than an anecdote, it is what let
three of this project's own positive results be withdrawn on inspection, and it
survives a run that never converges. Nothing here asks you to take a number on
faith.

### "Why not just use two different models?"

It is the first thing most people ask, and it does help a little. It does not reach the underlying issue, though, because both models still read the same criteria and so both still write to them. Where the criteria say "reject malformed rows" and never define malformed, two models resolve that ambiguity from the same sentence, and the implementation is still built around the resolution the tests will check for. Two models is also a habit rather than a mechanism: nothing checks they stayed different, and a settings change a year from now undoes it with no test to notice.

Withholding removes the channel rather than the coincidence, so it holds whichever model is writing. The two compose nicely, incidentally, since qikly picks a provider and model per agent role: you can withhold *and* use two models.

## The mechanism

A task file has **three** parts, and the cut runs between the third and the
first two:

1. **`requirements`** is the vague part: what a real specification looks like before anyone sharpens it.
2. **`interface`** is the contract as a description rather than code, the function signatures and where the module will live. Both agents read it.
3. **`acceptance_criteria`** is the sharp part: specific, objectively checkable rules, including the boundary values and edge cases a vague spec leaves open.

The test generation agent receives all three. The coding agent receives the
first two, **with the acceptance criteria removed in code before the prompt is
built**. It is not instructed to ignore them. It cannot be persuaded, prompted,
or induced into seeing them, because no representation of them exists in its
context.

Everything else follows from that asymmetry. A run works through three stages,
`integration` then `system` then `unit`:

1. **Integration and system tests are generated first**, from the spec alone,
   before any code exists. They cannot see an implementation because there is
   not one yet.
2. **The coding agent writes the implementation**, from the spec minus the
   criteria.
3. **pytest runs.** On failure the model produces a **FIX** (failure summary,
   root cause, plan, and the files it intends to touch) and then a **PATCH**
   (a unified diff of only those files), applied all or nothing. Repeat until
   the stage passes or the budget is spent.
4. **Unit tests are generated last**, once real code exists for them to name.
   This is the only stage allowed to see the implementation.
5. **Clearing a stage re-runs the earlier ones**, so a later fix cannot
   silently break something that already passed.

Two things are worth noticing about step 3. The reasoning and the diff are separate LLM calls, which makes the reasoning independently auditable and restricts the diff's context to the files the reasoning identified. And the FIX is generated from the failing test's *output* alone. Not the test source, not the criteria, not a hint. The same feedback a developer sees in their terminal.

There is no separate "write the initial implementation" step anywhere. The first run happens against an empty source tree, fails on a collection error, and that failure feeds the same FIX and PATCH cycle as every later repair. The first line of code and the hundredth are produced by one mechanism.

### The five agents

Everything above is done by five agents, each with its own definition file in
`inputs_public/agent_defs/` and its own entry under `agents:` in
`settings.yaml`, so any of them can be pointed at a different model without
touching the others. Two of them exist because a single agent doing both jobs
is the failure this project is about.

| Agent | Settings key | Reads | Never reads | Produces |
|---|---|---|---|---|
| **Coding agent** | `code` | requirements, interface, and the text of whatever test just failed | the acceptance criteria, and the test source | a FIX, the reasoning and the files it intends to touch, then a PATCH, a unified diff of only those files |
| **Test-writing agent** | `test`, or `test_integration` / `test_system` / `test_unit` | requirements, interface, and every acceptance criterion in full | the implementation, except at the unit stage, which is written last and exists to name real functions | one pytest file per stage |
| **Criteria drafter** | `criteria` | the requirements alone | any implementation, and any existing criteria | a first draft of the bar, only when `--generate-criteria` asks for one |
| **Criteria reviewer** | `review` | the specification, the current criteria, and a finished implementation | nothing withheld: this is the one agent shown everything at once | proposed additional criteria, each tagged with a category, for a human to accept or reject |
| **Fixture proposer** | `fixtures` | the requirements, the criteria, and the fixture files as they stand | the implementation, and the criteria it is not asked about | for each criterion nothing currently reaches, one row that would, written to a proposal file for a human to accept |

The coding agent runs far more often than the others, once per repair attempt,
which is why it is the one where a cheaper model pays for itself. The reviewer
is the one asked to find what nobody wrote down, which makes it the likeliest
to be worth a stronger model. Both are one line in `settings.yaml`.

The fixture proposer is the newest and the only one that suggests changing the
*inputs* rather than the code or the bar, which is why it is the only one whose
output never lands anywhere automatically. A criterion nothing can trigger
produces a test that passes whatever the code does, and in this project's own
measurements roughly two thirds of deliberately planted faults were missed by
every suite for that reason: the bar was unmeasurable rather than wrong. But a
row is harder to review than a sentence, because it is only right or wrong
relative to the criterion it was proposed for, and a fixture set that grows in
whatever direction a model finds interesting stops resembling the data you
actually process. So proposals go to a file, capped per round, each row printed
under the criterion it exists to reach, and the file reports what share of your
data a machine has written so the drift is visible in aggregate rather than one
plausible row at a time.

## Using it

A word first on how this was built, because it is not incidental to the subject. I architected the tool's objectives and its orchestration, and I guided the research: which experiments to run, which results to believe, and which of my own claims to discard when the numbers did not support them. **The code itself was largely written and tested by Claude Opus 5.0, across many iterations of review, correction and rework.**

That feels worth stating plainly in a post about not letting one model mark its own homework. The separation this tool enforces is the same separation I relied on while building it: the measurements decided what was true, not the author of the code, and several of the conclusions below are ones I did not want.

```bash
pip install qikly
export GEMINI_API_KEY=...
qikly --demo
```

The demo runs one task end to end in an output directory and prints what it built. That takes about thirty seconds. It writes nothing outside that directory.

### Which command to run

A task file is one YAML file with three parts, and the split above is a split
between them:

1. **`requirements`** what the code must do, in the words a person would use.
   The coding agent reads this.
2. **`interface`** the contract as a description rather than code: the function
   signatures and the dotted path where the module will live. Both agents read
   it, and neither is handed an implementation, because when the integration
   and system tests are written there is not one yet.
3. **`acceptance_criteria`** what counts as correct, each one checkable and
   naming its boundary value. **Only test generation reads this.**

Which command you want depends on which of the three you already have, and the
full table is in
[README.md](https://github.com/gal-a/qikly#which-command-depends-on-which-parts-you-already-have).
The short version: `qikly --explain <MY_TASK>` to see the split for yourself,
`qikly --demo` to watch a whole run, `qikly --init` to start a task from
nothing, and `qikly --scaffold <FILE>.py` to start one from code you already
have.

### What you already have decides how you use it

A task file has three parts, and which of them you already have decides both
what qikly does for you and which command you run. The full table, with the
exact command for each starting point, is in
[README.md](https://github.com/gal-a/qikly#which-command-depends-on-which-parts-you-already-have).
The four that matter most, most valuable first:

1. **You have #2 and code somebody else wrote, and you want that code
   verified.** Something else produced the implementation. Point `--scaffold`
   at it and it reads the real signatures into the interface for you, leaving
   the requirements and the criteria yours to write. The suite is then written
   from criteria the implementation's author never saw. A suite generated from
   the same context as the code is a model agreeing with itself, and agreement
   is not evidence. This is the use no other tool in this space covers.

2. **You have #1, #2 and #3, and no code.** A specification exists and an
   implementation does not. You get a first implementation plus the suite that
   justifies it, and nothing is drafted on your behalf. Everything lands in
   `outputs/` for review; nothing is written to your source tree.

3. **You have #1 and #2, and want a first draft of the bar.**
   `--generate-criteria` drafts #3 from the requirements alone, or
   `--criteria-from` lifts it out of the ticket where you already wrote it.
   Then the run proceeds as above, and the draft is yours to correct.

4. **You have everything and want it run unattended.** Non-zero exit on any
   non-convergence, so a scheduler or CI job can run many specifications and
   keep the reports as artifacts. There is a GitHub Action, and JUnit XML for
   whatever tracks tests where you work.

## Now it's your turn to test it on your specification

The engine is open source under Apache 2.0, because the central claim is one nobody should take on faith. The whole argument rests on the coding agent genuinely never seeing the bar, and that is something you can test and verify rather than just accept.

Read the four prompt files, read the function that strips `acceptance_criteria` out of the specification before the prompt is built, and watch a run do it.

That verification is the point of publishing the engine at all.

*Try it in thirty seconds:*

```bash
pip install qikly
export GEMINI_API_KEY=...
qikly --demo
```

Then do the thing that actually tests the idea: write one specification of your own, split it into `requirements` and `acceptance_criteria`, and read the criteria the tool derives against the ones you would have written by hand. If it finds a gap you missed, that is the argument. If it does not, I want to know which specification broke it.

Issues and results, welcome and wanted:
[github.com/gal-a/qikly/issues](https://github.com/gal-a/qikly/issues)

---

## Appendix: reference

### Example tasks

Ten tasks ship with the tool, in four domain families.

| Family | Task | What it does |
|---|---|---|
| `CALC_*` arithmetic and precision | `CALC_TAX` | Per-line order tax; stresses rounding and currency precision |
| | `CALC_DISCOUNT` | Discount amounts; validation versus computation edge cases |
| | `CALC_CALENDAR` | Date-range charge from a monthly rate; calendar arithmetic, leap years |
| `ETL_*` string and format validation | `ETL_EMAIL` | Validates and normalises contact records with an email field |
| | `ETL_ADDRESS` | Postal addresses; deduplicates across two files |
| | `ETL_NAME_SPLIT` | Splits a full-name field into first, last and suffix |
| `MERGE_*` combining two sources | `MERGE_SALES` | Two sales exports with overlapping ranges; cross-file dedup |
| | `MERGE_STOCK` | Inventory transactions into per-SKU stock; cross-file ordering |
| | `MERGE_CONTACTS` | Contact records from two systems; conflict resolution by recency |
| `AGG_*` event-stream aggregation | `AGG_RUNLOG` | Summarises append-only JSONL run logs |

Every task ships with `requirements`, an `interface`, and a full set of
`acceptance_criteria`, so each one is a worked example of the task format
as well as something to run.

### Supplying your own code or tests

The loop takes three inputs, and each can be yours or generated, independently
and in any combination. `seed.implementation` points the tool at code you
already have, so the run skips generating a first implementation and goes
straight to testing and repairing yours. `seed.tests` keeps a suite you already
trust, so the loop repairs the code against your tests rather than its own.

That last combination is the one worth naming, because it is the strongest use
of the tool: **your suite, its code.** The bar was written by a person and the
implementation has to satisfy it without ever having read it.

Setup, the exact YAML, and what `--scaffold` writes are in
[README.md](https://github.com/gal-a/qikly#bringing-acceptance-criteria-you-have-already-written).

### Measuring rather than producing

```bash
python -m qikly.orchestrator.run_all --repeat 10
```

Repeats the whole sweep N times and writes one aggregate report to `outputs/reports/`. Concretely, that report contains:

| Output | What it is |
|---|---|
| Convergence rate per task | Converged runs over total, with a 95% confidence interval, so a task at 6/10 is reported as a range rather than as "60%" |
| Per-stage pass rates | How often integration, system and unit each cleared, which is what identifies the blocking stage |
| Right-censored runs | Budget-exhausted runs counted separately from failures, because "did not finish in 10 attempts" is not the same fact as "cannot be done" |
| Stall signatures | Non-converging runs grouped by the tests they persistently failed, which is what turns a pile of stalls into a short list of recurring subjects |
| Cycle counts | FIX-to-PATCH cycles per run, so cost per converged task is visible |

The point is that it emits **intervals and groupings, not a single headline number.** A rate without an interval invites exactly the mistake described below.

Use `--repeat` when making a claim. Use a single run when you want the output. That distinction has already caught us out: a criteria change we were confident about looked like a fix, and ten repeated runs showed 5 out of 10 against 6 out of 10 before, no improvement at all and well inside the noise.

### Watching a run live

```bash
python -m qikly.orchestrator.live_view
```

Tails the current run's transaction log and renders it as it happens: which stage, which iteration, which tests failed, and what the model did about it.
