# research/

**Not part of the installed package.** Only `src/qikly/` ships in the
wheel, so if you arrived here via `pip install` you do not have these files and
do not need them. They are the harnesses that produced the measurements in
[../docs/DESIGN_2_PERFORMANCE.md](../docs/DESIGN_2_PERFORMANCE.md), kept so those numbers can be reproduced
and disputed rather than taken on trust.

## Published, or not

Not all of these are public. A published figure needs its harness visible or
it is asking to be taken on trust, which is the one thing this project is
against. Work still in progress is different: an unfinished measurement read
by a stranger is a claim nobody made.

So each file below is marked, and the split is enforced rather than
remembered:

  **public**   backs a number that has been published, including one that was
               published and then withdrawn, and travels with the repository so
               anyone can rerun or dispute it
  **private**  the open refinement question. Held back until its results are
               settled enough to publish deliberately, not by default

`tests/test_research_publication.py` fails if a file here is unclassified, so
a new harness cannot become public simply by existing. The public branch is
built by excluding the private ones; see `MAINTAIN.md` in the private
repository for the command.

Run them from the repository root:

```bash
python research/mutation_test.py --all
```

| Script | What it measures |
|---|---|
| **public** `mutation_test.py` | Fault detection. Injects a known fault into an implementation its own suite accepts, re-runs the suite, and records whether it noticed. **Its own headline detection rate is withdrawn**, and the withdrawal is the reason the harness is here. An earlier figure was quoted from a run whose report was not timestamped and was later overwritten, and a second claim from the same period, that `>` to `>=` survived all 22 suites, did not survive re-checking either: see `recheck_gt.py`. Reports are timestamped now. Nothing this script has produced is currently cited as a public number, and it ships so that the next one can be disputed rather than trusted. |
| **public** `backanalysis.py` | Cross-execution agreement. Runs an implementation retained from one run against a suite retained from a different run of the same task. Produces the 950 verdicts. |
| **private** `false_rejection.py` | **Does the suite refuse code that is correct?** The measurement missing every time this research stalled: detection, escapes and cross-arm all score "stricter" and "wrong more often" identically, so none of them can turn "tighter" into "better". Needs a `reference:` block in the task naming a human-written implementation that no agent ever sees. Integration and system stages only, since unit tests bind to an implementation's own helper names. No model calls. |
| **private** `shared_substrate.py` | **Both bars, the same code, the same planted faults. No effect, and a mechanism instead:** 25 pairs, 1,724 identical faults. Each suite is fitted to the implementation it converged alongside, the initial arm gaining 15 faults at home and the refined arm 19, and on a hand-written reference neither arm ever saw the refined suite is behind in 6 of 7 pairs. Before the suites are held to the same test count the refined arm's own code shows p = 0.007, which is the number the four earlier designs would have published. Every positive result this project has produced was withdrawn for one reason: the two arms were compared on different artifacts, so suite size, sample size or mutable surface could explain the gap instead of the bar. Here one implementation is chosen, one fault set is planted in it, and both arms' suites are shown exactly those mutants, so a larger suite gets no extra chances and neither arm can expose more surface. The baseline is per test rather than per suite, because every archived arm suite refuses code it was not written for and a whole-suite gate would discard all of them: keep the tests that pass on clean code, and a fault is caught when one of those flips. Scores each pair on its own initial code, its own refined code, and the task's reference where one exists, since a result that holds on only one substrate is a fact about that implementation. No model calls: runs entirely from preserved artifacts. |
| **private** `strictness.py` | **Is the refined bar stricter?** Runs both arms' implementations over the same fixture rows and compares their verdicts, so the direction of every disagreement is explicit: initial accepts and refined rejects means refinement tightened that row. Replaces the cross-arm check in `escaped_faults.py`, which counted a looser suite rejecting stricter code as the looser bar being strict and therefore recorded symmetry even when refinement worked. Reads accepted counts as the primary signal, since row identity breaks exactly where the two arms normalise differently. No model calls: runs from preserved artifacts. |
| **private** `escaped_faults.py` | The same question measured as escaped faults rather than a detection rate, with one implementation per arm instead of one shared. **No measurable difference:** 4 tasks across 5 seeds, 16 converged pairs. Escaped arithmetic faults 108 against 105, escaped validation faults 60 against 62, sign test 0.607 and 0.581. The code growth that motivated the metric did not hold: the refined arm was larger in 9 of 16 pairs, minus 25% to plus 31%. Use `--merge` to pool seed runs, which reports the commit each pair came from. **Cross-arm rejection is the measure to read first, and it must be read per test:** the 5 to 0 result recorded here was taken when the refined suite had more than twice the tests, so it cannot separate a stricter bar from a longer one. Use `--initial-batch` to hold both arms to the same size, and check the run did not report NO TESTS COLLECTED before reading anything. |
| **private** `refined_vs_initial.py` | Whether a suite built from refined criteria detects more injected faults than one built from the initial draft. **No measurable difference:** 5 tasks, 125 injected faults, both suites caught 68, disagreeing about 6 split three and three. Paired difference 0.0 points, 95% CI -3.8 to +3.8. |
| **private** `sweep_experiment.ps1` | The paired experiment that tested whether running ten tasks concurrently degrades convergence. It does not: 60% either way. |
| **public** `stage_breakdown.py` | Where a sweep's runs stopped, stage by stage. The aggregate report says how many runs converged; this says how many cleared integration and system, which is the 83% quoted in `README.md` and `docs/DESIGN_2_PERFORMANCE.md` and the source of the 19-point unit-stage gap the argument rests on. That figure was in the documents for a week with nothing behind it, which is the situation `MAINTAIN.md` exists to prevent, so it is derived here and `tests/test_published_figures.py` fails if the documents drift from it. Selects runs by the aggregate's own task keys: `AGG_RUNLOG` reads like an internal artifact and is in fact one of the ten tasks, and dropping it moves the figure to 86%. No model calls. |
| **public** `stats_helpers.py` | Wilson intervals, the exact sign test, the paired bootstrap. Every interval quoted anywhere came through here, so it travels with the figures it produced. No measurement of its own. |
| **private** `recheck_gt.py` | Re-checks a specific historical claim, that `>` to `>=` survived all 22 suites, against preserved artifacts. The claim did not reproduce and was withdrawn; this is the tool that withdrew it. Kept for the record rather than for use. |
| **private** `criteria_count_backanalysis.py` | Counts criteria against generated suite size across archived runs. Produced the finding that refinement adds 54% more criteria while the suite gets 6% smaller, which is why batching exists. Part of the open question. |

## Why these are separate from the tool

The tool converges code against a bar. These ask whether the bar was any good,
which is a different question and one the tool cannot answer about itself. They
read archived runs from `outputs/` and make no model calls, except
`refined_vs_initial.py`, which must generate criteria and converge
implementations before it has anything to compare.

## A caution that applies to all of them

One run is an artifact, not a rate. Every number these produce is an estimate
from a sample, and the same task with the same seed converges on some runs and
not others. Use `run_all --repeat N` and report an interval before treating any
output here as a property of the tool. A criteria change that looked like a
clear improvement once measured 5 out of 10 against 6 out of 10 before it, well
inside the noise.

## Fixture rows added for the refinement experiment

`MERGE_SALES` and `MERGE_STOCK` carry rows chosen to exercise the criteria the
refinement loop actually produces. Before these, the refined bar described
inputs the sample data did not contain, so a test derived from it could not
fail on any implementation and the whole comparison was blind to whatever the
extra criteria were worth.

**This table is here and not in the task YAML on purpose.** The coding agent
reads that file with only the `acceptance_criteria` section removed, so a
comment there explaining what each row is for would hand back the answer key
the whole design exists to withhold.

| Row | Criterion it makes testable |
|---|---|
| `TXN-1008,$75.25` | amount accepted with a leading dollar sign |
| `TXN-1009,99999999999.00` | no upper bound on a monetary amount |
| ` txn-1001 ` in the second file | deduplication is case sensitive and does not strip whitespace, so a transaction present in both overlapping exports is counted twice |
| `TXN-1010,...,01/09/2026` | several competing date formats accepted with no single standard |
| `TXN-1011,...,2099-12-31` | implausibly far future date accepted |
| `WIDGET-1,RECEIVE,...` | transaction type matched case sensitively |
| `GADGET-2, ship ,...` | transaction type matched without trimming |
| `BOLT-5,rcv,...` | domain abbreviation rejected rather than normalised |
| `NUT-9,receive,0` | a receive of exactly zero passes a `qty < 0` check |
| `WID GET-7` | SKU with internal whitespace passes a truthiness check |
| 100 character SKU | no maximum length on an identifier |
| `...,2026-01-02T09:30:00Z` | timestamp with a zone marker normalised inconsistently |

Each row has an unambiguous correct handling under the task's existing
requirement to "apply reasonable, strict real-world validation", so neither
arm is asked to satisfy an arbitrary rule that fights what the model correctly
knows about the world. That failure mode produces a stuck loop rather than
slow convergence, and it has cost this project a run before.

**Results from before these rows were added are not comparable with results
after.** Every pair records the commit that produced it, so a merge across the
change is reported rather than silently averaged.
