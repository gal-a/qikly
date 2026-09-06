<!--
One of three. See MAINTAIN.md: these three files, README.md, docs/index.html
and the investor deck move together. A number changed here has to change in
all of them.
-->

# How well it works: three sweeps, and the results we withdrew

**Part 2 of three.** [Part 1](DESIGN_1_CASE_STUDY.md) makes the case that the
agent writing the code should never see the acceptance criteria, and shows one
repair end to end. This part asks the harder question: does it work, how often,
and how much of that is measurable?

Everything below is from runs on `gemini-3.5-flash-lite`, a small cheap model
chosen so that repeated sweeps were affordable. Treat the figures as a floor
rather than a ceiling. Where a measurement did not survive scrutiny, it is
reported as withdrawn rather than removed.


---

**This is part 2 of three.**

| | | |
|---|---|---|
| [1. The case](DESIGN_1_CASE_STUDY.md) | **2. How well it works** (you are here) | [3. How it is built](DESIGN_3_MECHANISM.md) |

## How well it works

Three claims, in descending order of how much weight they can carry.

### One you can check yourself, with no statistics at all

**The coding agent never receives the acceptance criteria.** Not "is instructed
not to look at them", and not a convention someone has to remember: the criteria
are removed before the FIX and PATCH prompts are assembled, and a test in the
repository fails the build if any call site lets one through.

```bash
qikly --explain CALC_TAX
```

It prints the task file twice, once as each agent receives it, and the
difference between them: eleven acceptance criteria on one side, twelve lines
cut before the other side is handed the file. No API key, no model call, about
a second, and it works from a plain `pip install`.

That shows the criteria being removed once, for one task. The test suite
checks something stronger: that no call site anywhere in the codebase can pass
a criterion to the coding agent, so the removal cannot be undone by a future
change. If you have cloned the repository rather than installed the package,
you can run it:

```bash
python -m pytest tests/test_withholding.py -v
```

That takes a few seconds and needs no API key, no sample size and no
confidence interval. It is the strongest claim here precisely because it is not
a measurement: it is a property of the code, and it cannot rot.

### It converges, and the rate reproduces

Measured on `gemini-3.5-flash-lite`, a small cheap model chosen to make repeated
sweeps affordable, so treat these as a floor rather than a ceiling.

**Roughly 8 runs in 10 finish with the code passing every integration and system
test. Roughly 6 in 10 pass everything including unit tests.**

The reason those are round numbers is that they were measured three times.

| Sweep | Runs | Integration + system | Integration, system and unit |
|---|---|---|---|
| 14 August | 427 | 80% | 59% |
| 30 August, same tasks and settings | 140 | 87% | 67% |
| 31 August, after correcting the benchmark | 400 | 83% | 64% |

The third sweep is the interesting one, and the reason is what happened between
the second and the third. Asking a separate agent which criteria no input row
could trigger turned up unreachable rules in eight of the ten tasks, from one
in `CALC_CALENDAR` to seven of thirteen in `MERGE_CONTACTS`. A criterion
nothing can reach produces a test that passes whatever the code does, so part
of every bar was not lower, it was absent. Thirty-one rows were added, and the
whole sweep was taken again.

The prediction was that convergence would fall, because the bar had genuinely
become enforceable. **It did not move.** 64% sits between the two earlier
figures and inside both intervals. Either the added rows exercise behaviour the
implementations were already getting right, or the difference is smaller than
this measurement can see, and separating those needs fault injection rather
than convergence. That experiment is not run.

Three independent sweeps agreeing is worth more than any one number's decimal
places, so the decimal places are not quoted.

One thing about a rate like this is worth internalising before you run anything:
**a single run is an artifact, not a rate.** The same task with the same seed
converges on some runs and exhausts its budget on others. To make a claim about
how often anything converges, repeat the sweep and read the interval.

### Nearly the whole gap between those two numbers is the unit stage

This is the most stable finding here and the most useful one, because it tells
you where runs actually fail. It held at about twenty points across both sweeps.

The reason is structural rather than mysterious. The unit suite is the largest,
so there is more to satisfy. It runs last, when the earlier stages already pass
and regression re-checks force them to keep passing, so a fix has the least room
to move. And it is the one stage whose tests are written with sight of the
implementation, so it can assert on incidental internal structure rather than on
required behaviour.

That last point deserves emphasis: **the only stage where the blindness is
broken is also the hardest stage.** Whether that is cause or coincidence is
testable, and untested.

### What explains the variation

The variation in the convergence rates is not due to size because every task has 6 to 7 spec requirements, 10 to 13 criteria, 3 interface functions and 2 input files.

Three things drive the difference:

1. *Carried state of a task.* Whether row N's correctness depends on the rows before it. The three `CALC_*` tasks are row-independent and average 78%. The three `MERGE_*` tasks all carry state and average 46%.
2. *Cross-file coupling.* Whether two input files can be concatenated or must genuinely be interleaved. `MERGE_STOCK` must merge-sort by timestamp before computing anything; concatenation produces plausible, wrong answers.
3. *Conflict with the model's priors.* Where a criterion asks for a convention the LLM would otherwise resolve differently.

### When a run stalls

A run that exhausts its budget exits non-zero, names the blocking tests, and
keeps the complete record. **There is no path by which it reports success on
code its own tests reject**, and in several hundred measured runs there has
never been such a case.

Stalls are usually near misses rather than wreckage: most of the blocking stage
is already passing, and a large share fail exactly one test. They also cluster.
The exact failing test names almost never repeat, but the *subjects* do, so
what you get is a short list of nameable problems rather than a diffuse failure
rate.

**Three of the four causes are fixed by editing text, not by buying a bigger
model.** They live in the specification or the bar rather than in the coding
agent, which means most stalls are within your control and cheap to resolve.
The signature of each, and what to do about it, is in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Is the bar any good?

This is the question that matters, and the tool is built to answer it with
evidence rather than assertion.

A programme of work is running on exactly this: cross-testing implementations
against other runs' suites, planting faults in code a suite has already accepted
to see whether it notices, and asking whether automatically refined criteria
catch more than a first draft. Those results will be published once substantial
user data has accumulated and been carefully analysed, because a figure earned
across many real specifications is worth far more than one earned across ten
example tasks.

One finding from that work is already solid enough to act on today, because it
is a mechanism rather than a rate.

**A suite that never tests the boundary cannot detect an error at the boundary**,
no matter how many other cases it covers. Change a `>` to a `>=` in code a
generated suite has already approved:

```python
# the code the suite accepted
if quantity > 100:
    reject(row, "quantity too large")

# the same code with one character changed
if quantity >= 100:
    reject(row, "quantity too large")
```

Those two versions disagree about exactly one input, `quantity == 100`, and
agree about every other input in the universe. Suites generated for this task
tested 5, 50 and 250:

| Test input | Original | Mutated | Suite can tell? |
|---|---|---|---|
| 5 | accept | accept | no |
| 50 | accept | accept | no |
| 250 | reject | reject | no |
| **100** | **accept** | **reject** | **yes, but no test used 100** |

Adding more tests at 5, 50 and 250 would not help. Only a test at exactly 100
would. What this says is that the generated suites were testing that the logic
works, not that it stops in the right place, which is the difference between a
test written to demonstrate behaviour and a test written to catch a mistake.

**And it tells you exactly what to fix, in your own file, today.** A criterion
phrased "reject quantities above 100" invites a test at 250. A criterion phrased
"100 is accepted and 101 is rejected" forces a test at the boundary. The blind
spot is in how the criteria are worded, which you control, rather than in the
model, which you do not.

## Where the bar comes from

Everything above assumes a human wrote the criteria. The harder question is whether the tool can write them itself, because that is the expensive half of QA.

The procedure goes as follows: draft initial criteria from spec requirements alone; converge a code implementation against that draft in an isolated workspace; then give a reviewing agent the specification, the current criteria, *and the finished implementation*, and ask what the code does that none of the criteria constrain?

The reviewer is looking for a specific thing: the gap between "passes what is currently tested" and "actually correct". These are places where the validation is looser than it appears, where one code path applies a normalization and another does not, or where a boundary condition is handled correctly only by accident rather than by design. Each such finding becomes a new criterion, tagged with an appropriate category.

Before trusting a drafted bar on a task where you have not written one, there is a way to find out what it would have cost you on a task where you have:

```bash
qikly --compare-criteria <MY_TASK>
```

It drafts criteria from that task's requirements alone, then reports them against the ones you wrote, treating yours as the ground truth. Output is covered, partial and missed, with every gap quoted in full and the drafted criteria that match nothing of yours listed separately, since those are either noise or a rule you know and never wrote down. The matching is a model's reading rather than a measurement, and says so: two criteria can mean the same thing in different words. It also says nothing about test quality, because two bars can describe the same rule and produce suites that catch different faults, which is the whole reason this project measures a bar by fault detection rather than by its text.

*Currently, the tool only makes additions.* It appends criteria and never modifies or removes one.

**This constrains the machine, not you.** The criteria live in your YAML file. You can rewrite one, delete one, or throw the whole set out, at any time, exactly as you would edit any other file you own. Nothing is locked. What the *system* cannot do is remove a criterion by itself.

The reason is narrow and worth stating plainly. The tool's success condition is "all criteria satisfied". If the tool could also edit the criteria, then the cheapest way to satisfy a failing criterion is to delete it, and every run would converge by definition. Success would stop meaning anything. Append-only is what keeps a passing run evidence of something rather than evidence of nothing.

So the answer to "we let it add criteria that may be wrong and can never be fixed?" is no, on two counts. A proposed criterion is never adopted automatically: a human reads it and accepts it, because a drafted bar is a proposal, not ground truth. And once adopted, it is yours to correct like any other line in the file.

The extension not yet built is letting the tool *propose* a removal, with the evidence for it, for a human to accept or reject through a normal gate such as a pull request, keeping the superseded criterion in the history rather than erasing it. The line that matters is between proposing and enacting, not between adding and removing.

### Does refining the criteria make the suite catch more?

**An open question, and an active one.** Refinement reliably *grows* the bar:
54% more criteria, and `CALC_TAX` goes from 12 to 26 across three rounds. Growth
and improvement are different things, so the question worth answering is whether
the grown bar catches more real defects.

Measuring that is a genuinely interesting experimental problem, and most of the
work so far has gone into the apparatus rather than the answer. Comparing two
bars means holding everything else constant: the code, the fault set, the suite
size, and the substrate each suite is judged on. Each of those took a round to
get right, and the current design controls all four.

The remaining piece is fixture coverage. In a fault-injection comparison a
planted fault can only be caught if some input row reaches the behaviour it
changes, which is exactly what the [fixture proposal agent](#the-five-agents)
was built to close. Results will follow once substantial user data has
accumulated and been carefully analysed.

Refinement is shipped and usable today. A quantified claim about how much it
sharpens the bar is what the work above will produce.

## Should the specification iterate too?

No, and that is a deliberate design decision worth explaining.

The spec requirements are the fixed point everything is judged against. A system permitted to rewrite its own goal can always satisfy a failing test by weakening what was asked. That is the same failure mode append-only prevents on the criteria side, and automating both ends would remove the last thing making convergence meaningful.

The legitimate version is different and worth building: when the review finds behaviour no criterion constrains, it is often because *the specification was ambiguous there*. Reporting "your spec does not say what happens when X, and the implementation chose Y" is a proposal to a human, not a self-edit. For a real team that may be the most valuable thing the tool produces.

## In summary

- **An agent that writes its own tests is grading its own homework.** At temperature zero with identical inputs it is provably vacuous: the same model that wrote the bug writes the test that blesses it.
- **The fix is structural, not procedural.** The coding agent never receives the acceptance criteria. Not "is told not to look", but never has them in its context.
- **You can verify that in one command.** `qikly --explain <MY_TASK>` prints what each agent is given and the difference between them. No API key, no model call, no sample size. From a clone, `pytest tests/test_withholding.py` additionally proves no call site can leak one, including a call site added next year. Both are properties of the code rather than benchmark results, so neither can go stale.
- **It converges, and the rate reproduces.** Roughly 8 runs in 10 pass every integration and system test, roughly 6 in 10 pass everything including unit tests, measured three times on a small cheap model, the third after correcting the benchmark itself. Every run that does not converge exits non-zero and names its blocking tests, and none has ever reported success on code its own tests rejected.
- **Nearly the whole gap between those two figures is the unit stage**, which is also the only stage whose tests are written with sight of the code.
- **How you word a criterion decides how sharp the test is, and that is yours to control.** A suite tests the boundary when the criterion names the boundary: "100 is accepted and 101 is rejected" produces the test that "reject quantities above 100" leaves to chance. This is the highest-leverage thing you can do in your own file.
- *Whether automatic criteria refinement produces a measurably sharper bar is the open question, and an active one.* It grows the bar reliably, and the experiment design to quantify the rest is built.

The measurement programme continues alongside the tool, and its results will be published once substantial user data has accumulated and been carefully analysed. Figures earned across many real specifications, from many people, are worth considerably more than figures from ten example tasks. What is published here has already survived an independent re-measurement; the rest will meet the same bar before it joins it.
