# Quick start on your own data

From nothing to a first run on your own module. Try the bundled demo, then
follow the five steps. Everything after them is reference: which command fits
what you already have, the task file field by field, criteria you already wrote
elsewhere, seeding your own code or tests, and the fixture rows a criterion
needs before it can be checked at all.

## Try it first

Requires **Python 3.10+** and **GNU `patch`** on `PATH`. On Windows it ships
with Git under `usr\bin\patch.exe`, which the tool finds on its own. **On macOS
you have to install it:** the system `patch` is Apple's BSD one, which rejects
the options qikly sends, so no generated diff will apply.

```bash
brew install gpatch     # macOS only
```

qikly looks for `gpatch` before `patch`, so nothing else is needed afterwards
and your system `patch` is left alone.

```bash
pip install qikly
export GEMINI_API_KEY=...     # or API_KEY, or your provider's own variable
qikly --demo
```

On Windows, in PowerShell, where `export` is not a command:

```powershell
pip install qikly
$env:GEMINI_API_KEY = "..."
qikly --demo
```

Other providers, and how to set a key so it survives a new terminal, are in
[docs/PROVIDER_KEY_SETUP.md](https://github.com/gal-a/qikly/blob/main/docs/PROVIDER_KEY_SETUP.md).

`--demo` runs one task end to end in a throwaway `demo/<timestamp>/` directory
and prints what it built and where. It writes nothing outside that directory,
so a first run leaves everything else untouched. About 30 seconds.

For the same thing on vehicle sensor data rather than an order pipeline:

```bash
qikly --demo --tasks ADAS_HEADWAY
```

`ADAS_HEADWAY` checks following distance from forward-radar samples. Its
requirements give the limits and the two-second rule; its withheld criteria
pin what happens exactly at each limit, including that a gap of zero metres is
not a measurement.

From a clone instead:

```bash
pip install -r requirements.txt
python run.py --demo
```

`run.py` is a shim around `src/qikly/cli.py`, the same entry point the
installed `qikly` command calls, so a clone and an install run identical
code.

## Your own module, start to first run

1. **Scaffold a task from the module.**

   ```bash
   qikly --scaffold your_module.py
   ```

   It reads the real function signatures and writes
   `inputs_private/config/tasks/<NAME>_VERIFY.yaml`, a task that tests the code
   you already have, then prints what to do next. For a fresh implementation
   of the same interface instead, add `--fresh`.

2. **Put your input data where the task says.** Its `inputs:` list names the
   files a run reads, such as `inputs_private/data/<NAME>/input_01.csv`.
   Scaffold does not create them, so copy a real sample of your data there.
   Until you do, `qikly --validate` reports `input file not found`.

3. **Write the two sections only you can write.** `requirements` holds the
   decisions and `acceptance_criteria` the consequences; the rule for telling
   them apart is under [Getting the two halves right](#getting-the-two-halves-right).
   Already written them in a page or a ticket? This takes the criteria from it:
   `qikly --scaffold your_module.py --from-doc feature.md`. Replace the
   remaining `TODO` lines too, and check the entrypoint scaffold marks as
   guessed.

4. **Check it, for free.**

   ```bash
   qikly --validate --tasks <NAME>_VERIFY
   ```

   No model call and no cost. Without `--tasks` it also checks every bundled
   example. It checks that the file parses, that every input
   path exists, that no `TODO` placeholder is left, that criteria name values
   rather than adjectives, and that no requirement restates a criterion.

5. **Run it.**

   ```bash
   qikly --tasks <NAME>_VERIFY
   ```

   Start reading at `outputs/reports/iterations/<task>_<timestamp>_report.html`.

   A `_VERIFY` task tests code you already have, which qikly did not write, so
   it cannot enforce that the code's author never saw your acceptance criteria.
   It evidences what it can: the run opens by asking git whether this task file
   was last changed before that code's first commit, and prints the answer with
   what it does not show. A commit date is not a writing date, and criteria
   settled first is the precondition of the opposite problem, someone coding to
   the bar. So read it as corroboration, and read the bad answer, criteria
   revised after the code landed, as the question it is.

**Tried it?** [Tell us what happened](https://github.com/gal-a/qikly/discussions/6), whether it worked, stalled
or never got past install.

**Keeping the suite?** Add the badge to your project's README, so the people
reading it know the tests were written by an agent kept apart from the code:

```markdown
[![tested with qikly](https://img.shields.io/badge/tested_with-qikly-2b8f95)](https://test.qikly.com/?ref=badge)
```

### Step 1 from inside VS Code

With the qikly MCP server connected (setup in
[docs/mcp.md](https://github.com/gal-a/qikly/blob/main/docs/mcp.md)), ask Copilot
in agent mode:

> Use the qikly_scaffold MCP tool on `src/your_module.py`, and save the task it
> returns under `inputs_private/config/tasks/`.

It returns the same task the command writes, one that tests the code you
already have, and says which filename to save it as. Steps 2 to 5 are the same,
and `qikly_validate` runs step 4 from the chat at no cost.

## You probably do not have to write the task file by hand

The criteria usually exist already, in a feature page or a ticket, and the
interface exists in the code. qikly reads both.

```bash
# a markdown page, a ticket export, or a .feature file
qikly --criteria-from feature.md --task-id MY_TASK

# straight from Jira: needs JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
qikly --criteria-from-jira PROJ-412 --task-id MY_TASK

# both halves at once: criteria from the page, interface from the module
qikly --scaffold src/metrics/band.py --from-doc feature.md
```

Bullet lists, a headed `Acceptance Criteria` section and Gherkin `Scenario:`
blocks are all understood. Your page stays the source of truth and nobody
retypes anything.

**One section is never filled for you: `requirements`.** The coding agent reads
it, and a feature page usually restates its own acceptance criteria in the
prose above them, so lifting requirements across would hand the criteria to the
one agent that must never see them. `qikly --validate` warns if what you write
there restates a criterion.

## Which command depends on which parts you already have

A task file is one YAML file with three parts, and the split above is a split
between them:

1. **`requirements`** what the code must do, in the words a person would use.
   The coding agent reads this.
2. **`interface`** the contract, and a description rather than code: the
   function signatures and the dotted path where the module will live. Both
   agents read it, and neither is handed an implementation to read from it.
   When the integration and system tests are written there is not one yet.
3. **`acceptance_criteria`** what counts as correct, each one checkable and
   naming its boundary value. **Only test generation reads this.**

"Spec" below means 1 and 2 together, which is what the coding agent is given.
A tick means you already have that part.

One thing the three parts do not say, and it matters: **test generation never
reads the implementation either.** Integration and system tests are written
before any code exists, from the specification alone. The unit stage is the
single exception, written last from the code that just cleared the earlier
stages, because unit tests have to name real functions.

| Where you are starting | #1 | #2 | #3 | Run | What happens |
|---|:-:|:-:|:-:|---|---|
| Before anything else: see what is withheld | | | | `qikly --explain <MY_TASK>`<br>e.g. `qikly --explain CALC_TAX` | Prints a task file twice, once as each agent receives it, and the difference between them. No API key, no model call, about a second. **You get:** the acceptance criteria on one side and the same file with them cut out on the other, which is the claim everything else rests on. Add `--html` for the same as a page you can share. |
| Just looking | | | | `qikly --demo` | A bundled task end to end in a throwaway folder. Thirty seconds, under a cent. **You get:** a working implementation, three test suites, and the full record of every FIX and PATCH, in a directory you can delete. |
| Code someone else wrote, and you want **that code** verified | | Y | | `qikly --scaffold <MY_MODULE>.py` | Scaffold reads the real signatures out of the file you point it at and fills in **#2** for you. **#1** and **#3** stay yours to write: criteria read out of an implementation can only describe what that implementation already does, which is a bar it passes by construction. **You get:** one task file that tests the code you already have. Add `--fresh` for one that writes a fresh implementation of the same interface instead. |
| You know what it must do, not yet how to check it | Y | | | `qikly --init` | Creates the directory layout and one starter task to edit. Its criteria show the habit that matters most: name the value, not the quality. "100 is accepted and 101 is rejected" forces a test at the boundary; "amounts must be reasonable" does not. **You get:** a task file to fill in, with your fixtures where a run will look for them. |
| Same, but you want a first draft of the bar | Y | Y | | `qikly --tasks <MY_TASKS>`<br>`--generate-criteria` | Drafts **#3** from **#1** alone, then runs. **You get:** a first draft of the bar written into your task file for you to correct, plus the implementation and suites. |
| You have written all three | Y | Y | Y | `qikly --tasks <MY_TASKS>` | Everything you wrote is used, and nothing is drafted on your behalf. **You get:** an implementation, integration, system and unit suites, a convergence report, and a run summary recording the model and settings that produced them. |
| You have all three but doubt they agree | Y | Y | Y | `qikly --check-criteria`<br>`--tasks <MY_TASKS>` | One model call asking whether any implementation could satisfy the description, **#1** and **#3** at once, and whether any two of **#3** agree with each other. Advisory, and exits non-zero on a contradiction so a pipeline can gate on it. **You get:** a list of the pairs that cannot both hold, before spending a stage budget on them. Two criteria setting different numbers on the same quantity are always reported, since that is a typo rather than a tighter bar. |
| A previous run stopped before finishing | Y | Y | Y | `qikly --tasks <MY_TASKS>`<br>`--resume` | Generating the tests and the first implementation already cost model calls, and they are still on disk. This keeps them and picks up where it stopped, instead of paying for them twice. **You get:** the same outputs as a full run, without paying for the parts already built. |

`<MY_TASKS>` is one task_id or several separated by commas. A task_id is a
filename under `inputs_private/config/tasks/` without the `.yaml`:
`--tasks CALC_TAX`, `--tasks CALC_TAX,MERGE_SALES`, or omit it to run every
task found. `<MY_TASK>`, singular, takes exactly one.

`QIKLY_MAX_CALLS=200 qikly` stops at a call limit rather than a bill.

`--scaffold` reads the module path and the real signatures of every public
function straight out of the file, because they are already there. It leaves
`requirements` and `acceptance_criteria` for you, and that is deliberate:
criteria derived from an implementation can only describe what that
implementation already does, and a bar that agrees with the code by
construction is the exact failure this tool exists to prevent.

## Writing a task by hand

Nothing is written into the package, and nothing is written into your source
tree.

### 1. Make the two directories

Anywhere you want to work. The presence of `inputs_private/` is what marks a
directory as your project.

```bash
mkdir -p inputs_private/config/tasks
mkdir -p inputs_private/data/MY_TASK
```

Or let `qikly --init` create both, plus a starter task to copy.

Until one of those exists, there is nothing marking your directory, and the
fallback in [Where things live](#where-things-live) applies. From a
`pip install -e` checkout that fallback finds the checkout itself, so a run
started in an empty directory writes its outputs there instead of where you
are standing. Make the directory first, or set `QIKLY_PROJECT_ROOT` to say
exactly where you mean.

### 2. Drop your fixture data in

Plain input files, whatever your code should read. CSV, JSON, JSONL, anything.

```bash
cp ~/somewhere/orders_jan.csv inputs_private/data/MY_TASK/input_01.csv
cp ~/somewhere/orders_feb.csv inputs_private/data/MY_TASK/input_02.csv
```

Names are up to you, but they must match what you write in the task's
`inputs:` list below. The generated program opens these **by literal relative
path from your project directory**, so the path in the task file is the path
that gets executed. That is also why the bundled fixtures are copied into
`inputs_private/data/` on first run rather than resolved from inside the
package: the generated code has no way to ask where the package lives.

Fixtures are never overwritten once present, so an edited file stays edited.

### 3. Write the task file

`inputs_private/config/tasks/MY_TASK.yaml`. The filename must match `task_id`.

```yaml
task_id: "MY_TASK"                    # letters/digits/underscore, not starting with a digit
task_name: "Order line-item tax"

description: "Read two CSV files of order line items, validate them, compute
  tax per line, and write the result to a single JSON output alongside a
  reason for every rejected line."

inputs:                               # literal paths, opened by the generated code
  - "inputs_private/data/MY_TASK/input_01.csv"
  - "inputs_private/data/MY_TASK/input_02.csv"

outputs:
  - "outputs/data/MY_TASK/output.json"

interface:                            # what test generation targets
  module: "outputs.agent_src.code.MY_TASK.calc"
  integration_functions:
    - "extract(input_path) -> list[dict]  # reads one input file, returns raw rows"
    - "transform(rows) -> dict  # validates and computes; returns {\"accepted\": [...], \"rejected\": [...]}"
    - "load(data, output_path) -> None  # writes the result as JSON"
  system_entrypoint: "run_calc(input_paths, output_path) -> None  # extract each path, then transform -> load"

requirements:                         # THE DECISIONS. The coding agent sees only this.
  - "Read both CSV files listed in inputs and combine their rows before validation"
  - "Validate each row: order_id, item_price, quantity, tax_rate"
  - "Apply strict, real-world data-quality validation; reject anything malformed or out of range"
  - "For each valid row compute subtotal, tax owed, and line total as currency amounts"
  - "A rejected row is not silently dropped: record it with a brief, specific reason"
  - "Write a single JSON object with two keys, \"accepted\" and \"rejected\""

acceptance_criteria:                  # THE CONSEQUENCES. Withheld from the coding agent.
  - "All computed currency amounts are rounded to two decimal places using round-half-up, not banker's rounding and not truncation"
  - "For every accepted row, the reported total equals the reported subtotal plus the reported tax, exactly, to the cent"
  - "A tax_rate of exactly 0 is valid: the computed tax is 0.00 and the total equals the subtotal"
  - "Each rejected row names the specific field that caused rejection, not a generic message"
```

`interface.module` is a dotted path under `outputs.agent_src.code.<task_id>.`,
which is where the implementation gets written. Pick the final component
freely; the rest is fixed by where outputs live.

### 4. Run it

```bash
qikly --tasks <MY_TASKS>        # or: python run.py --tasks <MY_TASKS>
```

Discovery is automatic; there is no registry to update. Results land in
`outputs/`, and `outputs/reports/iterations/MY_TASK_<timestamp>_report.html`
is the place to start reading.

### Getting the two halves right

This matters more than anything else in the file, and one question settles
most of it.

**`requirements` holds the decisions.** Anything a person chose that could have
gone another way: a threshold, a unit, a measurement convention, an exemption.
Nobody can guess a decision, so the coding agent has to be told.

**`acceptance_criteria` holds the consequences.** What must be true if those
decisions were implemented correctly: the exact boundary, the identity that has
to hold, the case a careless reading gets wrong. They are withheld because they
are the exam.

> **Given only the requirements, could two competent developers legitimately
> disagree about this line?** If yes, it is a decision and belongs in
> `requirements`. If no, it is a consequence and belongs in
> `acceptance_criteria`.

| In `requirements`, because it is a decision | In `acceptance_criteria`, because it follows |
|---|---|
| Keep at least 2.5 m from the vehicle ahead, measured centre to centre | At exactly 2.5 m, no violation is raised |
| Amounts are currency, rounded to the nearest cent | For every accepted row, total equals subtotal plus tax, exactly |
| Dates are written YYYY-MM-DD | 2026-02-30 is rejected, because it is not a real date |

**The gap between them is the entire mechanism**: with nothing withheld, both
sides read the spec identically and every test passes first try, which proves
nothing.

**Both mix-ups have a signature. Learn to read them.**

**A decision in `acceptance_criteria`** is withheld from the one agent that
needed it, so the coding agent has to guess a choice nobody told it. It does
not produce a harder test, it produces repetition, in one of two shapes. Either
the same test fails while the FIX and PATCH come back near identical each time,
because nothing the agent can see would lead it anywhere else, or two tests
disagree and each patch makes one pass and the other fail. Restrict street
suffixes to three valid values and the model keeps widening them, since
everything it knows says "Boulevard" is a suffix.

Sometimes, though, the agent simply guesses right and the run goes green. That
is the worse outcome, because nothing then tells you a decision was in the wrong
half. On a bundled task whose criteria alone settled whether exactly 2.00
seconds of headway raises a warning, three runs in ten converged anyway. Do not
rely on the loop to find these for you; apply the question above when you write
the spec. [TROUBLESHOOTING.md](https://github.com/gal-a/qikly/blob/main/docs/TROUBLESHOOTING.md#5-the-same-patch-appearing-over-and-over)
has the diagnosis for the repeating case.

**A consequence in `requirements`** is the quieter mistake. Both agents read the
same boundary value, so the test that checks it passes on the first attempt and
proves nothing. The rest of the suite is unaffected and still bites, which is
what makes it easy to miss: the run looks entirely normal. Nothing fails, and
nothing was learned about that boundary.

Only a person can fix either one, by moving the line into the other half. The
loop cannot: it can tighten a bar the code already attempts, and it cannot tell
you a line is in the wrong place.

**To see a task that follows the rule,** run `qikly --explain CALC_TAX`. Its
requirements say amounts are "currency amounts rounded to the nearest cent",
and the withheld criteria pin what that already means, down to a float result
of 434.99999999999994 reporting as 435.00. More in
[docs/design_3_mechanism.md](https://github.com/gal-a/qikly/blob/main/docs/design_3_mechanism.md#using-it).

## Bringing acceptance criteria you have already written

Most teams have not got a blank page here. If you work in Jira, Linear, Azure
DevOps or a design doc, the rules are usually already written down, because the
process asks for them before any code is cut. A ticket routinely looks like
this:

```
PROJ-412  Merge overlapping sales exports

Description
  Combine two CSV exports into one file...

Acceptance Criteria
  - A transaction in both files at the same amount appears once
  - A negative or missing amount is rejected, naming the field
  - Dates must be YYYY-MM-DD
```

Those bullets are exactly what `acceptance_criteria` wants. Save the ticket to
a file and read them out:

```bash
qikly --criteria-from ticket.md                    # print as YAML
qikly --criteria-from ticket.md --task-id MY_TASK  # write into that task
qikly --criteria-from ticket.md >> inputs_private/config/tasks/MY_TASK.yaml
```

It understands plain bullet lists, an "Acceptance Criteria" heading in a longer
document, and Gherkin `Scenario:` blocks with Given/When/Then. Only the criteria
section is read, so pasting a whole ticket does not turn its description into
part of the bar. Only YAML goes to stdout, so the third form above appends a
valid block.

**It will not invent criteria from prose.** A file with no list and no scenarios
returns nothing and says so. A rule that nobody wrote is precisely the invented
standard this tool exists to argue against, and once it is in the file it looks
like every other line.

There is no API token and no vendor integration involved. Copying the ticket
into a file is the whole of it.

**Read what comes out before you run.** Criteria lifted from a ticket are a
draft: tickets are written for people, who fill in gaps that a test cannot. The
criteria are the standard everything else is judged against, so they are worth
a minute of your attention.

## Supplying your own acceptance criteria, code or tests

The loop takes three inputs. **Each one can be yours or generated,
independently and in any combination.**

| Input | Default | To supply your own |
|---|---|---|
| **Acceptance criteria** | Yours | Already the default: write `acceptance_criteria` in the task file, as above, or lift them from a ticket with `--criteria-from` (below). Omit it and add `--generate-criteria` to have a first draft written for you instead. |
| **Implementation** | Generated | `seed.implementation` in the task file. |
| **Test suites** | Generated | `seed.tests`, per stage. |

### Auto-generating acceptance criteria

A task with no `acceptance_criteria` still runs, with a warning rather than an
error, because running one deliberately is a legitimate thing to do. What you
lose is the point of the exercise: test generation has only `requirements` to
work from, the coding agent has nothing sharper to fail against, and the run
usually converges on the first attempt without exercising the loop at all.

`--generate-criteria` writes a first draft from the requirements alone into
`inputs_private/config/tasks/<task_id>.yaml` before the run starts. It is
opt-in, it never touches a task that already has criteria, and it says what it
wrote rather than editing your files quietly. Pointed at a bundled example it
writes your own overriding copy and leaves the packaged original alone.

**A generated bar is a draft, not ground truth.** It was written from the same
requirements the coding agent reads, so a case it did not think to demand is
not being withheld from anyone: the two halves agree because they came from one
source, which is the failure mode this whole tool argues against.
`--compare-criteria` scores a generated bar against yours when you want that
difference measured rather than assumed.

The optional `seed:` block:

```yaml
seed:
  # A file or a directory, copied into outputs/agent_src/code/<task_id>/.
  # A single file keeps its own name, which must match interface.module.
  implementation: "seeds/MY_TASK/calc.py"

  # Per stage. Seeding a stage suppresses generation for that stage only.
  tests:
    integration: "seeds/MY_TASK/test_integration.py"
    unit: "seeds/MY_TASK/unit/"
```

Paths are relative to your project directory. Both keys are optional.

**`seed.implementation` is how you point this at code you already have.** The
run skips generating a first implementation and goes straight to testing and
repairing yours. `--scaffold` writes this block for you by default, and `--fresh` writes a
task without it, for a new implementation of the same interface. **`seed.tests` keeps a suite you already trust**, so the loop
repairs the code against your tests rather than its own. Mixing works and is
often what you want: seed the integration stage with your suite and let the
tool generate unit tests against whatever code results.

Three things to know:

- **Seeded test suites are checked before the run starts.** Every file must
  parse, and at least one must be named `test_*.py` and contain a `def test_*`
  function. A problem raises immediately rather than retrying, since there is
  no second sample to draw from a file you wrote.
- **Seeds are installed after the workspace reset, not instead of it.** Every
  run still begins from one declared state, so repeated runs stay comparable
  and no run inherits the previous one's residue.
- **A seeded run measures something different from an unseeded one.** Do not
  pool them in a single rate. The orchestrator prints a NOTE on every seeded
  run to keep that visible.

## Where things live

Task specs and shared defaults are read from `inputs_private/` in your project
directory if present, otherwise from the copies bundled inside the package, so
a fresh install runs immediately. Resolution is **per file**: dropping one task
spec into `inputs_private/config/tasks/` overrides exactly that task and leaves
everything else in place. Nothing is ever written back into the package.

| Path | Contents |
|---|---|
| `config/tasks/<task_id>.yaml` | One task, as above. |
| `data/<task_id>/` | That task's fixture data. |
| `config/settings.yaml` | Retry budget, stage order, patch size limit. A private copy is overlaid section by section, so state only what you change. |
| `agent_defs/*.md` | The prompts. `code_agent.md` and `test_agent.md` are the two system prompts; the rest are per-mode fragments. Not per-task: editing these changes every task's behaviour. |

## Proposing fixture rows

A criterion no input row can trigger produces a test that passes whatever the
code does. Across this project's own measurements roughly two thirds of
deliberately planted faults were missed by every suite for that reason: the bar
was unmeasurable rather than wrong.

```bash
python -m qikly.orchestrator.tuning.propose_fixtures --tasks <MY_TASKS>
```

A separate agent reads your criteria and your fixture files and says, for each
criterion, either `covered` or here is the smallest row that would reach it.
The answer goes to `outputs/reports/fixture_proposals/`, laid out with each row
printed under the criterion it exists to reach so you judge the two together.

**It never edits a fixture.** To accept a row, paste it into the named file and
append `  # proposed`. To reject one, do nothing. Two reasons for the gate,
neither about the model being untrustworthy. A row is only right or wrong
relative to its criterion, so it is harder to review than a sentence. And a
fixture set that grows in whatever direction a model finds interesting stops
resembling the data you actually process, at which point every rate measured on
it describes a world that does not exist. The report is capped at eight
proposals per round and prints what share of your rows a machine has written,
so that drift is visible in aggregate rather than one plausible row at a time.

You can of course add rows by hand at any time, and always could. This exists
because noticing *which* criteria have no data behind them is the tedious part.

The refinement loop does this for you on what it adds. When
`refine_acceptance_criteria` finishes with new criteria, it asks for rows the
same way, lists the new criteria first in the report, and logs how many have no
data that reaches them, so a sharper bar does not arrive partly unmeasurable.
It still applies nothing.

