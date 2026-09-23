# Quick start on your own data

From nothing to a first run on your own module. Try the bundled demo, follow
the five steps, then read the one question that decides where each line of your
specification goes. That is the whole path, and it is the whole of this page.

Everything else lives in [the task file reference](https://github.com/gal-a/qikly/blob/main/docs/TASK_FILE_REFERENCE.md): which command fits what
you already have, the file field by field, criteria you wrote elsewhere,
seeding your own code or tests, and the fixture rows a criterion needs before
it can be checked at all. Come back for those when you want them; you do not
need any of it for a first run.

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

**Install into a virtual environment**, and not only out of habit. Two reasons
specific to this tool. qikly pulls in a provider SDK, so a bare install can
upgrade a package your own project pinned. And qikly resolves where to read and
write from the environment it is running in, so "which interpreter am I in" is
a question you will want a clean answer to the first time something behaves
oddly. `qikly --version` is that answer: it prints the version, the package
directory and the interpreter together.

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install qikly
qikly --version                # which build, from where, on which Python
export GEMINI_API_KEY=...      # or API_KEY, or your provider's own variable
qikly --demo
```

On Windows, in PowerShell, where `export` is not a command:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install qikly
qikly --version
$env:GEMINI_API_KEY = "..."
qikly --demo
```

Let the install finish before running anything. The provider SDK is a long
dependency chain and pip installs qikly itself last, so there is a window where
its dependencies are present and qikly is not, which looks exactly like a
broken install.

The key is an ordinary environment variable, so it belongs to the shell rather
than to the virtual environment: set it once in that terminal and both see it,
in either order. Only `--demo` needs it. `--version`, `--explain`, `--validate`
and `--scaffold` make no model call and cost nothing.

**One key is enough, and `LLM_PROVIDER` is optional.** Gemini is the default,
so the line above is all you need. Hold a key for a different provider and no
`LLM_PROVIDER`, and qikly uses that one and prints that it did, because a tool
that silently picks a provider silently picks who gets billed. Set
`LLM_PROVIDER` when you hold more than one key and want to choose:
`gemini`, `openai` or `anthropic`. The per-provider recipes in
[docs/PROVIDER_KEY_SETUP.md](https://github.com/gal-a/qikly/blob/main/docs/PROVIDER_KEY_SETUP.md)
set it alongside the key, which is the right habit once more than one is in
play.

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
   qikly --scaffold my_metrics.py
   ```

   It reads the real function signatures and writes a task file, then prints
   what to do next.

   The name comes from the module's own filename, upper-cased, and which of two
   task files you get depends on the job:

   | Command | Writes | What that task does |
   |---|---|---|
   | `qikly --scaffold my_metrics.py` | `MY_METRICS_VERIFY.yaml` | Tests the code you already have |
   | `qikly --scaffold my_metrics.py --fresh` | `MY_METRICS.yaml` | Writes a fresh implementation of the same interface, and tests that |

   Both land in `inputs_private/config/tasks/`. The `_VERIFY` suffix is what
   keeps them apart, so scaffolding the same module both ways never overwrites
   the first file with the second. The rest of this section uses
   `MY_METRICS_VERIFY` as the example; substitute your own.

   **See what you get before you run it.**
   [`docs/examples/`](https://github.com/gal-a/qikly/blob/main/docs/examples/)
   holds the real output of both commands, run on a real module, along with
   sample data:
   [`my_metrics.py`](https://github.com/gal-a/qikly/blob/main/docs/examples/my_metrics.py),
   [`MY_METRICS_VERIFY.yaml`](https://github.com/gal-a/qikly/blob/main/docs/examples/MY_METRICS_VERIFY.yaml),
   [`MY_METRICS.yaml`](https://github.com/gal-a/qikly/blob/main/docs/examples/MY_METRICS.yaml),
   [`input_my_metrics_01.csv`](https://github.com/gal-a/qikly/blob/main/docs/examples/input_my_metrics_01.csv)
   and
   [`input_my_metrics_02.csv`](https://github.com/gal-a/qikly/blob/main/docs/examples/input_my_metrics_02.csv).
   Those two YAML files are regenerated and compared by a test, so they are
   what scaffold writes today rather than what it wrote once.

2. **Put your input data where the task says.** Its `inputs:` list names the
   files a run reads, here `inputs_private/data/MY_METRICS_VERIFY/input_01.csv`.
   Scaffold does not create them, so copy a real sample of your data there.
   Until you do, `qikly --validate` reports `input file not found`.

3. **Write the two sections only you can write.** `requirements` holds the
   decisions and `acceptance_criteria` the consequences; the rule for telling
   them apart is under [Getting the two halves right](#getting-the-two-halves-right).
   Already written them in a page or a ticket? This takes the criteria from it:
   `qikly --scaffold my_metrics.py --from-doc feature.md`. Replace the
   remaining `TODO` lines too, and check the entrypoint scaffold marks as
   guessed.

4. **Check it, for free.**

   ```bash
   qikly --validate --tasks MY_METRICS_VERIFY
   ```

   No model call and no cost. Without `--tasks` it also checks every bundled
   example. It checks that the file parses, that every input
   path exists, that no `TODO` placeholder is left, that criteria name values
   rather than adjectives, and that no requirement restates a criterion.

5. **Run it.**

   ```bash
   qikly --tasks MY_METRICS_VERIFY
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

> Use the qikly_scaffold MCP tool on `src/my_metrics.py`, and save the task it
> returns under `inputs_private/config/tasks/`.

It returns the same task the command writes, one that tests the code you
already have, and says which filename to save it as. Steps 2 to 5 are the same,
and `qikly_validate` runs step 4 from the chat at no cost.

### What a real run on your own code looks like

Not the bundled demo. This is an ordinary module that totals invoice lines,
scaffolded with `qikly --scaffold`, with the two human sections filled in by
hand. The whole run cost **$0.003** and seven model calls.

```
[stage 1/3] [iteration 1] 3/4 passed | FAILED: test_quantity_boundary_zero_and_negative
[stage 1/3] [iteration 2] 4/4 passed
[stage 2/3] [iteration 1] 0/1 passed | FAILED: test_system_entrypoint_output_structure_and_types
[stage 2/3] [iteration 2] 1/1 passed
[stage 1/3] [iteration 2-regcheck] 4/4 passed
[stage 3/3] [iteration 1] 5/5 passed
```

**Line 1 is the whole point.** The existing code validated that `qty` parsed as
a number and stopped there, so a quantity of zero or minus one went through as
a real order. One acceptance criterion said otherwise:

```yaml
acceptance_criteria:
  - "A qty of 0 is rejected and a qty of 1 is accepted; a negative qty is rejected"
```

The suite was written from that criterion before the run touched the code, and
the coding agent never saw the criterion itself. What it received was pytest's
output for the failing test: the name, the test's own source and docstring, and
the assertion error. From that it produced this patch:

```diff
         try:
             qty = int(row["qty"])
             unit = float(row["unit_price"])
+            if qty <= 0:
+                rejected.append(dict(row, reason="qty must be positive"))
+                continue
         except (ValueError, TypeError, KeyError):
```

That is a real bug in code that already existed, found by a test written from a
rule the agent repairing it could not read.

**The generated tests say where they came from**, so the suite is reviewable
rather than a black box:

```python
def test_quantity_boundary_zero_and_negative():
    """Verify that a quantity of 0 is rejected, 1 is accepted, and negative
    quantities are rejected.
    # Requirements: 2, 4
    # Criteria: 2
    """
```

**One honest note about the other criterion.** The same task asked for
round-half-away-from-zero on currency, and the test for it passed on the first
attempt against code using plain `round()`. Not because the code was right in
general, but because on this particular input the binary representation of
10.005 lands just above the halfway point and `round()` returns 30.02 anyway.
A criterion is only as good as the input that exercises it, which is the same
point as [fixture coverage](https://github.com/gal-a/qikly/blob/main/docs/TASK_FILE_REFERENCE.md#proposing-fixture-rows) further down.

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


## Everything else

The task file field by field, the four routes in, criteria you have
already written, seeding your own implementation or suite, where each
artefact lands, and fixture coverage: [task file reference](https://github.com/gal-a/qikly/blob/main/docs/TASK_FILE_REFERENCE.md).
