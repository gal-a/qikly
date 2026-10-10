# Findings

Specific things qikly has caught, each with what was run, what it found, and
what the result does not show. Written 2026-10-04.

Three rules bind this page. **A single run is an artifact, never a rate**, so
every number here says how many runs produced it. **Nothing claims a detection
rate**, because that would need a comparison nobody has run. And **anything
reproducible says how to reproduce it**, because a number you cannot check is
worth very little, which is the argument this whole project rests on.

---

## 1. Money rounded the wrong way, and the implementation never knew

**What was run.** A task whose acceptance criteria, written before any code
existed, stated that money rounds half up. The coding agent received the
requirements and never the criteria.

**What happened.** The implementation used Python's default, `round()`, which
rounds half to even, so 2.5 becomes 2 and 3.5 becomes 4. This is correct
Python and wrong for money. The suite, written from the criteria by a separate
agent, failed on exactly that behaviour.

**Why it is the clearest case on this page.** The criteria settled the
question, a person wrote them, and the implementation departed from them. The
test agent exercised no judgement of its own: it encoded a decision somebody
had already made.

**What it does not show.** That the same defect would have survived a suite
written the ordinary way. Nobody ran that comparison.

---

## 2. A decision nobody had made, hiding between `<` and `<=`

**What was run.** A second task, same arrangement.

**What happened.** The implementation and the suite disagreed about a boundary.
Neither was wrong, because the criteria never settled whether the threshold was
inclusive. The disagreement is what made the gap visible.

**Why it is different from the first.** Nothing here is a defect. The output is
a question for a person: should exactly the threshold value count? Without the
disagreement, whatever the implementation happened to do becomes the rule, and
nobody ever notices it was a choice.

**Across both tasks**, twenty runs, ten on each: the suite disagreed with the
implementation every time. In both, the coding agent had written down the
judgement call it was making before any suite existed. **Twenty runs on two
tasks is not a rate for qikly in general.**

---

## 3. A suite that passed everything and missed most of the planted faults

**What was run.** `pricing.py`, a small order-pricing module with a bulk
discount and VAT, and a seven-test suite written by reading the code. The suite
passed.

```
qikly --score-code pricing.py --score-tests test_pricing.py
```

**What it found.** 3 of 8 planted faults caught, the same in ten runs, five
seeded and five not. Four of the five misses were boundaries: the bulk
threshold moving from 10 to 11, `>=` becoming `>`, and `<=` becoming `<` and
`0` becoming `1` in the quantity guard, which could also be disabled outright
unnoticed. The suite exercised quantities of 2 and 20 and never 10, which is
the threshold itself.

**A correction.** Earlier versions of this page reported 4 of 8, and said the
same suite scored anywhere from 25% to 50% between runs. That spread was a
defect in the scorer, fixed in 0.5.9: two same-size faults written within one
second could reuse each other's cached bytecode, so one fault was sometimes
given another's verdict. Scores from versions before 0.5.9 should be
re-measured before they are quoted.

---

## 4. The validator that accepted a 150% tax rate

**What was run.** `CALC_TAX`, which ships with the tool. See
[design_1_case_study.md](design_1_case_study.md) for the full run.

**What happened.** The implementation accepted a tax rate above 100. The suite,
written from criteria the coding agent never saw, failed. The agent then
reconstructed the upper bound from the failing test, its source and its error,
patching `tax_rate < 0` to `tax_rate < 0 or tax_rate > 100`, without ever
being shown the criteria.

**Why it is worth reading in full.** It is the clearest example of the repair
loop working from behaviour rather than from the answer.

---

## 5. Two thirds of planted faults that no suite could have caught

**What was run.** Several rounds of planted-fault experiments comparing
refined criteria against the originals.

**What was found.** Two thirds of the planted faults were caught by neither
side, because the fixture data never exercised the behaviour they changed. A
criterion about scientific notation cannot fire on data containing none.

**Why it is here rather than hidden.** It is the reason those experiments were
weak, and most of the evidence was missing by construction rather than by
anyone's mistake. It is also why `--propose-fixtures` exists: it finds the
criteria your data cannot reach. The full record, including the withdrawals, is
in [design_2_performance.md](design_2_performance.md).

---

## What none of this shows

**Whether withholding the criteria catches more real defects than a suite
written with full sight of the code.** That comparison has not been run. It is
the open question, and it is the measurement this project is working towards.

Everything above shows that an independent suite finds disagreements, and that
each disagreement is either a defect or a decision nobody had made. That is a
smaller claim, and it is the one the evidence supports.
