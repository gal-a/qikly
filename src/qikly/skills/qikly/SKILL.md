---
name: qikly
description: Write tests that can actually fail, by withholding the acceptance criteria from the agent that writes the code. Use when someone does not trust a suite that passes. Use when they want tests written from a specification rather than from the code. Use when they ask whether a specification is testable, or want an existing suite scored by planting faults in the code. Python modules, through the qikly tool. Also use whenever qikly or spec-driven testing is mentioned.
license: Apache-2.0
metadata:
  author: Gal Arav
  homepage: https://github.com/gal-a/qikly
  version: 0.2.0
  requires: qikly >= 0.5.4
---

# qikly: tests written from a spec the coder never read

## What this is for

If you write a module and then write its tests, both come from one reading of
the same ambiguous sentences, so the tests cannot disagree with the code. The
suite goes green and the green means nothing.

**Python modules only.** qikly scaffolds from Python signatures and generates
pytest suites; this Skill says nothing about any other language, and you should
say so rather than guess if asked.

qikly splits one specification in two. Test generation reads the whole thing.
The coding agent receives the same file with the `acceptance_criteria` section
cut out, and when a test fails it sees the failure, never the criterion it
broke. That separation is enforced in qikly's own code, not by instructions in
this file, which matters: **this skill cannot keep anything hidden. The tool
does that. This skill only helps you use the tool correctly.**

**And be precise about what the withholding covers**, because a user will
eventually stretch it. It is one thing: inside a qikly run, the coding agent's
prompt is assembled without the `acceptance_criteria` section. It says nothing
about this conversation. If someone pastes their criteria to you, you have
read them, and no part of qikly prevented that or knows it happened. Say so
plainly if you are asked whether talking to you is covered.

## Install

```bash
pip install qikly
qikly --version          # version, package directory and interpreter
```

**This Skill needs qikly 0.5.4 or later**, which is where `--score-code`
arrives, alongside `--score-suite` and the reachability warning in `--validate`
from 0.5.3. Against an older install an
agent following this page will recommend a flag that does not exist, so check
`qikly --version` before trusting the command table below. The Skill's own
version is separate from the tool's: it changes when these instructions
change, not when qikly releases.

A run needs one provider key, `GEMINI_API_KEY`, `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY`. Several commands need no key and cost nothing; the table
further down says which, and when to reach for each.

**Which key is present decides how long a run takes.** On
`ANTHROPIC_API_KEY` qikly uses `claude-sonnet-5`, which thinks before every
answer, so a ten-call loop becomes minutes plus thinking tokens you are billed
for. The published figures come from `gemini-3.5-flash-lite`, fast and cheap
enough to repeat. Say which key a run will use, and what it means for the wait,
before starting it. That goes for you too: a reasoning model driving this tool
charges the user the same wait at every step, so keep the mechanical steps
mechanical.

## The one question that decides everything

Every line of a specification goes in one of two halves, and this settles it:

> **Given only the requirements, could two competent developers legitimately
> disagree about this line?**

**Yes, it is a decision.** It belongs in `requirements`, where the coding agent
reads it. Nobody can guess a choice somebody made: a threshold, a unit, a
measurement convention, an exemption.

**No, it follows.** It belongs in `acceptance_criteria`, which are withheld.
The exact boundary, the identity that must hold, the case a careless reading
gets wrong.

| In `requirements`, a decision | In `acceptance_criteria`, a consequence |
|---|---|
| Keep at least 2.5 m from the vehicle ahead, centre to centre | At exactly 2.5 m, no violation is raised |
| Amounts are currency, rounded to the nearest cent | For every accepted row, total equals subtotal plus tax, exactly |
| Dates are written YYYY-MM-DD | 2026-02-30 is rejected, because it is not a real date |

**A worked case, because this one is easy to get backwards.** A spec says
*"warn when following distance breaks the two-second rule"*, and the
acceptance criteria say *"a headway of exactly 2.00 s does not raise a
warning"*. That split is **wrong**, and the reason is the question above:
"breaks the two-second rule" reads as "below two seconds" just as naturally as
"at or below two seconds", so two competent developers can disagree about
2.00 s itself. It is a decision, and it has to move into `requirements`.
Measured on this exact task, leaving it in the criteria converged 3 runs in 10;
moving that one sentence converged 10 in 10. Read that as what it is: evidence
that the agent was guessing, not evidence that the suite got better. A run that
cannot converge is a run that proves nothing at all, which is a different
problem from a suite that converges and proves little.

Note what moving it does **not** mean. Moving a decision is a correction the
spec always needed, and it is justified by the question alone, without looking
at any code. Copying a criterion's boundary value into the requirements to get
a run green is the opposite: it tells both agents the answer, and the test that
checks it then passes first try and proves nothing.

**Both mistakes have a signature, and you should recognise them.**

A *decision* hidden in the criteria leaves the coding agent guessing something
nobody told it. It shows up as repetition: the same test failing while each FIX
and PATCH comes back nearly identical, or two tests disagreeing where every
patch fixes one and breaks the other. Sometimes it guesses right and the run
goes green, which is worse, because nothing then tells you the line was in the
wrong half.

A *consequence* left in the requirements is quieter. Both agents read the same
boundary, the test for it passes first try, and nothing was learned. The run
looks entirely normal.

**Spotting one is your job; settling it is not.** You can tell a decision from
a consequence by applying the question above to the words on the page, and you
should: say which line you think is in the wrong half and why. What you cannot
do is choose the answer. Whether a headway of exactly 2.00 s warns, whether an
empty string counts as missing, whether currency rounds half up or half even:
nothing in the specification settles those, which is what makes them decisions,
and guessing on the user's behalf puts an invented choice into their
requirements where it will look decided. Name the ambiguity, propose the
wording, ask which way they want it.

qikly's own refinement loop cannot do even the spotting: it can tighten a bar
the code already attempts, and it cannot tell you a line is in the wrong
place.

## Writing criteria that can be tested

**Name values, not adjectives.** "Reject large amounts" produces a test at some
arbitrary large number. "100 is accepted and 101 is rejected" forces the
boundary.

**Name both sides of a boundary in one criterion.** "The 250 limit is
inclusive: exactly 250 is accepted and 250.01 is rejected" is one criterion
closing one ambiguity, and it tells you exactly which two rows the data needs.

**But check first which half the boundary belongs to, because this technique
and the worked case above look identical on the page.** One rule separates
them, and it is about the requirement's own wording:

> Does the requirement already settle which side the edge falls on?

"Keep **at least** 2.5 m" settles it: at 2.5 m you comply, so a criterion
saying no violation is raised at exactly 2.5 m only spells out what was
already decided. Write it as a criterion.

"Warn when the headway **breaks** the two-second rule" does not settle it, and
neither does "rounded to the **nearest** cent" when a value lands exactly
halfway, or "reject rows where quantity is **missing**" when nobody said
whether an empty string counts. In each case the criterion would be making the
choice rather than recording it. Move the choice into the requirement, then
write the criterion for its consequence.

Words that usually settle it: at least, at most, above, below, strictly, on or
after. Words that usually do not: nearest, breaks, exceeds a limit, missing,
invalid, malformed.

**Every value you name has to exist in the data.** A criterion no input row can
trigger produces a test that passes whatever the code does. This is the most
common reason a suite measures less than it appears to.

**Then go back through the requirements and pair them.** Every decision in the
requirements should have a criterion that would catch it being implemented
wrong, and this is the step people skip: they write the decisions carefully,
write criteria for the two or three boundaries that worry them, and leave the
rest of the specification unchecked. "Line totals are quantity times unit
price" is a decision; the criterion that pairs with it is an identity, "for
every accepted row, line_total equals quantity times unit price, to the penny".
Without the pair, the agent can get the arithmetic wrong and nothing fails.

Ask it as a sweep: for each requirement, what would a wrong implementation of
this look like, and which criterion catches it? A requirement with no answer is
a requirement nothing is testing.

**And read your own requirements back against the word list above.** This
applies to wording you wrote yourself, which is where it gets missed: an agent
that writes "rounded to the nearest cent" has just created the ambiguity it
knows how to spot in somebody else's spec. If a requirement you drafted uses
one of those words, say so and ask which way the boundary falls, rather than
writing criteria that quietly avoid the case. A tie nobody decided is not a
withheld consequence, it is a decision nobody made, and it will surface as a
stalled loop later.

## The five steps, on the user's own module

```bash
qikly --scaffold my_metrics.py          # reads real signatures, writes a task file
# put a real sample of the data where the task's `inputs:` says
# fill in `requirements` and `acceptance_criteria`, using the question above
qikly --validate --tasks MY_METRICS_VERIFY    # free, no model call
qikly --tasks MY_METRICS_VERIFY               # the paid one
```

**Before that last line, check which provider key is set.** It decides the
model, and therefore the wait and the bill; see Install above. On
`ANTHROPIC_API_KEY` every call thinks before it answers, and a run of ten calls
is minutes rather than seconds. Tell the user which one they are about to spend
on before they spend it.

**A task file has a third section.** `interface` names the module and the
function signatures, and the coding agent reads it: it is how both agents agree
what to call things. Scaffolding fills it in from the real signatures, so it
rarely needs editing, but a line about the shape of the output belongs there
rather than in either half above.

`--scaffold my_metrics.py` writes a task that tests code that already exists.
Add `--fresh` for one that writes a new implementation of the same interface
and tests that. Both land in `inputs_private/config/tasks/`.

**The task id comes from the module's filename, upper-cased**, so
`pricing.py` gives `PRICING`, and the plain scaffold adds `_VERIFY` because it
tests code you already have: `PRICING_VERIFY`. `--fresh` gives `PRICING`. The
command prints the name and the path it wrote, so read that rather than
guessing.

**Never edit the user's module to make a test pass.** qikly does not, and
neither should you.

**If the project tells you to write code and tests together, say so rather
than choosing silently.** A house rule like "always write the implementation
and its tests in the same session so they stay consistent" is reasonable on its
own terms and is the exact thing this tool exists to prevent: consistency by
construction is what makes a suite unable to disagree. You cannot follow both.
Tell the user the two conflict, in one sentence, and let them decide which
applies here.

To see the whole shape first, `qikly --example` lays down a finished worked
task, module and sample data included, so you can read a filled-in pair before
writing one, in the directory you are standing in.

**`qikly --demo` is a different command and the difference matters.** It runs a
bundled task end to end in a throwaway `demo/<timestamp>/` folder that exists to
be deleted, and it is the one most people try first. A user who has just watched
it work is standing in something that looks exactly like a working project, and
the obvious next move is to start theirs there. **Never set up someone's real
project inside a demo folder.** If the user says they ran "the demo" and wants
to continue where they are, establish which of the two commands they ran before
writing anything. This has already cost a first-time user an afternoon.

## The free checks, and when to reach for each

| Command | Cost | Use it when |
|---|---|---|
| `qikly --validate --tasks X` | free | always, before any run. Catches a missing input file, a leftover TODO, a criterion made of adjectives, a requirement restating a criterion, and criteria the data cannot reach |
| `qikly --explain X` | free | to show the user exactly what each agent receives, criteria present on one side and absent on the other |
| `qikly --score-suite --tasks X` | free, and slow | after a run converges, to find what the suite would not have noticed. It plants one fault at a time in the code and reports which ones the tests missed. Free because every fault is an edit to the code's syntax tree and no model is asked anything; slow because each fault means running your whole suite again |
| `qikly --score-code PATH --score-tests PATH` | free, and slow | **for a suite qikly did not write**, which is what somebody already has before they have anything else. Point it at a module or package and the tests for it, and it reports which planted faults the tests did not notice. No task file, no run, no model call, nothing of theirs modified, and the report lands beside their code. This is usually the right first thing to run on a stranger's project |
| `qikly --check-criteria --tasks X` | one model call | when a spec may contradict itself, before spending a run on it |
| `qikly --propose-fixtures --tasks X` | one model call | when `--validate` says a criterion's values are missing from the data, to get the rows it would take |

**Read `--score-suite` beside the reachability warning it prints above the
number.** A suite cannot catch a fault in behaviour no input row exercises, so
unreachable criteria lower the score for a reason that is about the fixtures
and not about the tests. Fix the data first, then score.

**`--score-code` prints no such warning, and you must not imply it does.**
There is no task file and therefore no criteria to be unreachable, so the
report carries the score and nothing above it. The underlying problem has not
gone away: a fault that survives may be on a line no test ever executes, which
is a gap in what the tests reach rather than in what they assert. Say that to
the user rather than handing them a percentage as a verdict on their suite.

## When a run does not converge

It exits non-zero, names the tests that blocked it, and ships nothing. Read
which stage stopped first: the unit stage is last and strictest, and most
failures are there.

Then, in order:

1. **Is the loop repeating itself?** Near-identical FIX and PATCH each
   iteration means a decision is in the wrong half. Move it into
   `requirements`.
2. **Do two tests disagree,** each patch fixing one and breaking the other? The
   specification contradicts itself. `--check-criteria` finds that before a run.
3. **Can the data reach every criterion?** `--validate` now says, and
   `--propose-fixtures` drafts the rows.

Then the cheap levers: a larger model, and more attempts. And never loosen a
criterion to get green, for the reason given above.

**On macOS, if no patch ever applies**, install GNU patch: `brew install
gpatch`. The system `patch` is BSD and rejects the options qikly sends, so
every generated diff fails for a reason that looks like the model's fault.

**What the agent sees when a test fails, exactly.** pytest's output for the
failing test: its name, its own source and docstring, and the assertion error.
Not the acceptance criterion. Because a generated test's docstring usually
restates the rule it came from, a failing test does tend to give away its own
case, and the project says so rather than pretending otherwise. It does not
undo the split: the suite was written first, from criteria the coder never
read, and nothing learned afterwards changes a test already on disk. There is
a setting that narrows this, `diagnostic_feedback: staged` under `agent:` in
settings.yaml, which starts the agent at a one-line error and widens only when
a patch stops making progress. **It is off by default**, because every
published convergence figure was measured with the full traceback and nobody
has measured what starting narrow costs.

**A run prints nothing while a model call is in flight**, which on a reasoning
model can be minutes. After ten seconds it starts saying so, one line every
fifteen: `[patch] still waiting on the model, 45s`. Those lines are the
difference between slow and stalled, so pass them on rather than swallowing
them, and do not conclude a run has hung while they are still arriving.
`QIKLY_NO_PROGRESS=1` turns them off.

**To stop a run spending more than you meant**, three environment variables
bound it: `QIKLY_MAX_CALLS` and `QIKLY_MAX_TOKENS` bound one task's process,
and `QIKLY_MAX_SWEEP_TOKENS` bounds a whole sweep. Set them before a first run
on somebody's real code rather than after.

**In CI**, qikly ships a GitHub Action. A run costs a model call per attempt,
so per pull request is a budget decision rather than a technical one, and the
free checks are the ones that belong on every commit: `--validate`,
`--score-suite` for a suite qikly generated, and `--score-code` for one that
predates it, which on most real repositories is the relevant half.

## What to tell the user honestly

Roughly 8 runs in 10 produce code passing every integration and system test,
and roughly 6 in 10 pass everything including unit tests, measured over 967
runs and reproduced over 390 more. **Always say what those runs were:** a
small, inexpensive model (`gemini-3.5-flash-lite`), chosen so the sweeps could
be repeated affordably, so the figures are a floor rather than a ceiling. And
they measure convergence, whether generated code passes the generated tests,
not whether those tests catch real defects.

**Two things are settled and one is not, and they are easy to confuse.**

*Settled:* the coding agent never receives the acceptance criteria. That is a
property of the code, checkable with `qikly --explain` and held by a test that
fails the build if any call site ever leaks one. It is not a benchmark result
and cannot go stale.

*Settled:* the convergence figures above, measured and re-measured.

*Open:* whether a suite written from withheld criteria catches **more real
defects** than one written with sight of the code. That comparison has not been
run, here or anywhere. A Google team has measured the step before it, that
generating tests from a written contract rather than from the code raises bug
detection by 9.8 points (arXiv 2608.17177), which is adjacent and not the same
claim. Separately again, six experiments asked whether automatically *refining*
the criteria produces a sharper bar and none detected an effect, which is an
absence of evidence rather than evidence of absence. Three different questions.
Do not offer any of them as evidence for another.

## References, and when to open them

Do not read these by default. Each one is a full page, and everything above is
enough for a first run.

**Read `references/TASK_FILE_REFERENCE.md`** when you need a field this page
does not name, when the user already has criteria written somewhere else and
wants them imported, when they want to seed their own implementation or suite
rather than have one generated, or when you need to know where a run writes
each artefact.

**Read `references/TROUBLESHOOTING.md`** when a run has already failed and the
three questions above did not explain it. It has eleven numbered causes, each
with its own fix, and the triage table at the top maps a symptom to a number.

The repository, for anything neither covers:
<https://github.com/gal-a/qikly>
