# Task file reference

The parts of working on your own data that you look up rather than read
through. The path to a first run is [the quick start](https://github.com/gal-a/qikly/blob/main/docs/QUICK_START_ON_YOUR_OWN_DATA.md); this is what it
deliberately leaves out.

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

