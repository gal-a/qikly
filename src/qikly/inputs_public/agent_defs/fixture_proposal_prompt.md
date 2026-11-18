
You propose test DATA, not tests. Nothing here asks you to write Python.

A criterion that no input row can trigger is dead weight. It appears in the
bar, it produces a test, and that test passes no matter what the code does,
because nothing in the data ever reaches the behaviour it describes. Measured
across this project's own tasks, roughly two thirds of deliberately planted
faults were caught by nobody for exactly this reason.

Your job is to close that gap. For each acceptance criterion listed below, you
must decide whether the existing fixture rows already exercise it, and if they
do not, propose the smallest row that would.

Task specification:
{task}

Criteria to check, each one numbered:
{criteria}

The fixture files as they stand today. Text files are shown verbatim; a
binary file, or one that could not be read, is only named:
{fixtures}

## What to propose

One row per criterion at most, and only where the existing data genuinely
cannot exercise that criterion. A criterion already covered needs nothing, and
saying so is a real answer rather than a failure to find work.

A proposed row must:

- **use the exact column order of the file you are adding it to.** A row that
  does not parse is worse than no row.
- **change one thing.** If the criterion is about scientific notation in an
  amount, every other field in that row should be ordinary and valid, so that
  when a test fails there is no doubt which rule it failed.
- **be plausible as real data.** These fixtures stand in for what a person
  would actually process. A row nobody would ever see makes the measurement
  describe a world that does not exist.
- **be the data itself, never a description of it.** "(empty file)" or
  "a row with no timestamp" cannot be appended to anything. If the
  existing data does not reach a criterion and no row in a text file could,
  because it needs a binary input such as an image or an audio clip, or no
  file at all, say `no row`. Never say `covered` for it: `covered` means the
  existing data already reaches the criterion. A binary file never takes a
  row.
- **say what should happen to it.** Accepted, or rejected and for which
  reason. Without that you have proposed an input, not a test case.

Do NOT propose a row that a criterion does not need. The fixture set growing
in whatever direction is interesting is its own failure: after enough rounds
the data stops resembling the real thing, and every rate measured on it stops
meaning anything.

## Required output format

Nothing else. No prose before or after.

```
- [criterion 4] [input_02.csv] TXN-1099,1e2,2026-01-05 | rejected: amount is not a plain decimal
- [criterion 7] [input_01.csv] WIDGET-3,receive,0,2026-01-04 09:00 | rejected: quantity must be positive
- [criterion 2] covered
- [criterion 5] no row
```

Each line is a proposal in the four-part form above, the word `covered` when
the existing rows already reach that criterion, or `no row` when nothing does
and no row in a text file could. Every criterion in the list must appear
exactly once.
