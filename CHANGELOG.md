# Changelog

Versions follow [semantic versioning](https://semver.org). Version strings are
PEP 440 normalised, so they are written `1.0.1` rather than `1.01`, which
packaging tools would read as `1.1`.

## Unreleased

### Changed
- **`docs/DESIGN.md` is now three documents**, because one 7,500-word article
  asked a reader to finish the argument, the evidence and the architecture in
  one sitting to get any of them. Nothing was cut.
  - [`design_1_case_study.md`](docs/design_1_case_study.md), the argument and
    one `CALC_TAX` repair followed end to end.
  - [`design_2_performance.md`](docs/design_2_performance.md), three sweeps,
    the benchmark defect corrected between them, and the withdrawn results.
  - [`design_3_mechanism.md`](docs/design_3_mechanism.md), the five agents, the
    FIX and PATCH separation, and the reference appendix.

### Removed
- **Azure OpenAI provider.** Three providers ship: Gemini, OpenAI, Anthropic.
  Azure was a near-duplicate of the OpenAI path with an extra endpoint variable,
  and every SDK carried is somebody else's release schedule to track. It is in
  the git history and can come back when someone asks for it.

### Fixed
- **The Anthropic provider was broken.** `anthropic` SDK 1.x removed
  `temperature` from `messages.create()`, so any run with `LLM_PROVIDER=anthropic`
  raised `TypeError` before a request was sent. Anthropic now has no determinism
  lever at all, and the docs say so.
- **A non-GNU `patch` is now told apart from a failed hunk.** Apple and BSD ship
  an implementation that rejects `--fuzz`, without which no generated diff can
  apply; the run used to spend its whole budget regenerating patches that could
  never land.
- The missing-`patch` error now names how to install one, per platform.

## 0.3.0

First public release, and the first version number that will ever appear on
PyPI. This project was developed privately for months, and 0.3.0 as its first
public version says the tool has been well exercised: 848 offline tests in the
tree you clone, a seven-environment CI matrix, and end-to-end runs on Ubuntu,
Windows and macOS. Some bugs will still be there, so feedback on this first
public release is very welcome.

It goes backwards from the 1.1.0 in the private repository on purpose.

**On the `research/` files named below.** Five ship and eight do not, and the
entries here describe what a measurement found rather than what you can rerun.
`research/README.md` labels every harness public or private and says why; if a
file mentioned in this changelog is not in your copy, that is the reason and
not a packaging fault. The ones that ship are `backanalysis.py`,
`mutation_test.py`, `stage_breakdown.py`, `stats_helpers.py` and the README.

`1.x` promises a stable public API. `--init`, `--scaffold`, `--resume`,
`--check-criteria` and `--version` were all added in the two days before this
release, and the command surface is going to keep moving. Under semantic
versioning `0.y.z` says exactly that: anything may change. Nothing had been
published, so no version number was ever claimed and this costs nobody an
upgrade.

The tags `v1.0.1` and `v1.0.2` stay in the private history. What follows is
everything in them.


A fresh `pip install qikly` is now runnable on its own, a run that dies can be
continued instead of paid for twice, and there is a measurement that can tell
a stricter suite from a wrong one.

**A new project takes one command.** `qikly --init` creates the layout, a
starter task and a fixture in whatever directory you are standing in, and
never overwrites an existing file. Before this, an installed copy had nowhere
to put a task, so PyPI was only useful to someone who had already cloned a
project layout from somewhere.

**Code you did not write takes one more.** `qikly --scaffold module.py` reads
the file and writes the task for it: module path, the real signatures of every
public function with their annotations, private helpers left out, and a
guessed entrypoint labelled as guessed. It writes `TODO` for `requirements`
and `acceptance_criteria` and will not fill them in, because criteria derived
from an implementation can only describe what that implementation already
does. A test asserts it stays that way.

**A dead run can be continued.** `--resume` keeps the suites and
implementation a previous attempt left on disk rather than regenerating them.
It reads the disk rather than trusting the flag, so resuming with nothing
there behaves exactly like a fresh run.

**A run says what it cost.** Calls and tokens per model are printed at the
end. Money is an estimate from a static price table and is labelled as one
everywhere; a model missing from the table contributes nothing rather than a
guess. `QIKLY_MAX_CALLS` caps a run by counting calls, not the estimate, so
the limit still holds when the price table goes stale.

**A rate limit no longer ends a run.** Transport failures retry with jittered
backoff and honour a provider's own requested delay. Refusals that retrying
cannot fix are raised at once, which matters because a spending cap and
depleted prepayment credits both arrive wearing a 429.

**Specifications can be checked before they are run.** `qikly --check-criteria`
asks in one model call whether any implementation could satisfy both the
requirements and the acceptance criteria. It is advisory and changes nothing,
and it exits non-zero on a contradiction so a pipeline can gate on it.

**Wrong rejections are measurable.** A task config may now name a
`reference:` implementation, written by hand and never shown to any agent.
`research/false_rejection.py` asks whether a generated suite refuses it.
Everything measured before this could say a suite was stricter; nothing could
say it was better. `MERGE_STOCK` ships a reference.

**Strictness is measured by verdict direction.** The previous cross-arm check
counted a looser suite rejecting stricter code as evidence the looser bar was
strict, so it recorded symmetry even when refinement worked. Its replacement,
`research/strictness.py`, runs the same fixture rows through both
implementations one row at a time and compares verdicts, which no difference
in suite size can influence.

**Fixes.** A project `addopts = "-q"` combined with the tool's own `-q`
suppressed pytest's count line entirely, silently zeroing a whole run's
measurement; all four pytest invocations now pass `-o addopts=`. A tree-wide
punctuation substitution had corrupted static text in all three report
modules, which now have guards. Experiment leftovers could reach the bundled
tasks directory and ship in the wheel; they are ignored and CI checks for
them. `load_target_files` failed on cross-drive paths.

**Tests.** 315 to 500, still offline, still no credentials needed.

## 1.0.2

Everything between 1.0.1 and here is collapsed into one release, because none
of it was ever published. There is no installed copy anywhere running an
intermediate version, so squashing three unreleased entries into the one that
ships is tidying rather than rewriting history.

**Renamed to qikly.** The distribution on PyPI is `qikly`, the import package
is `qikly`, and the console scripts are `qikly`, `qikly-all`, `qikly-report`,
`qikly-metrics` and `qikly-diff-criteria`. Environment variables are
`QIKLY_PROJECT_ROOT`, `QIKLY_NO_VERSION_CHECK` and `QIKLY_TRACEBACK`. A landing
page lives in `docs/` and is published at test.qikly.com.

**The package has tests.** It had none: 5,764 lines and nothing watching, which
is why every spot check turned up a bug. Now 315, all offline, about eleven
seconds. `tests/test_withholding.py` is the one that matters: no acceptance
criterion reaches the coding agent's FIX or PATCH prompt, and a new call site
cannot bypass the strip.

**Three silent bugs, each found by writing those tests.** All of the kind that
produce a plausible wrong answer rather than an error.

`_parse_counts` read the literal last line of pytest's output to find the
summary. Output is stdout and stderr concatenated, so anything a plugin wrote
to stderr landed after the summary and every count silently became 0/0. Every
number this project reports passes through that function.

`load_target_files` called `os.path.commonpath` on a path the model chose. On
Windows that raises for a path on another drive, so a FIX naming one ended the
run with a traceback instead of having its suggestion ignored. A containment
check has to fail closed.

A tree-wide replacement of em dashes turned the missing-value placeholder in
all three report modules into a bare comma and rewrote report titles and
sentences, including in the README's own limitations section. Missing values
now render as `n/a`. Static guards in `tests/test_no_text_artefacts.py` scan
every source file and every published document so it cannot happen quietly
again.

**Per-agent model routing.** The four agents and the three test stages can each
run on their own provider and model, configured under `agents:` in
settings.yaml. Fixed while building it: switching provider left `API_KEY` on
the previous provider's key.

**Test generation can scale with the bar.** `test_generation.criteria_per_batch`
splits the acceptance criteria into batches and makes one generation call per
batch, writing one file per batch. It exists because of a measurement: across
67 archived suites, refinement raised the criteria count 54% while the
generated suite got 6% smaller, so tests per criterion fell from 2.21 to 1.32.
One call appears to produce roughly a fixed amount of test code however much
bar it is handed. Default is 0, the single-call behaviour every published
number was measured under.

**Research.** `research/escaped_faults.py` measures escaped faults rather than
a detection rate, converges one implementation per arm, and checks whether each
arm's suite accepts the other arm's code. At 16 pairs across 5 seeds it still
finds no effect from criteria refinement, and two premises died on the way:
refined criteria do not reliably produce more code, and the suite does not grow
when the bar does. Documented in the README, the research index and
`docs/DESIGN.md` rather than buried.

**CI** runs the suite on Ubuntu and Windows across Python 3.10 and 3.12, builds
the wheel, installs it into a clean environment, and checks the packaged data
actually ships.

## 1.0.1

First tagged release, and the baseline the measurements in
[docs/design_2_performance.md](docs/design_2_performance.md) were taken against: 427 runs across 10 tasks in
4 problem domains, 45,261 test executions. Pin this version to reproduce them.

**Added**

- `--demo`: runs one task end to end in a throwaway `demo/<timestamp>/` project
  root and prints what it built. Writes nothing outside that directory, so a
  first run leaves the working tree untouched. Console output is saved
  alongside the run's other logs.
- `seed:` block in a task config, supplying a starting implementation or
  per-stage test suites instead of generating them. Seeded artefacts are
  installed after the workspace reset rather than instead of it, so repeated
  runs stay comparable. Seeded suites are validated before the run starts.
- Provider-conventional API key variables are accepted alongside `API_KEY`:
  `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `AZURE_OPENAI_API_KEY`.
- `docs/DESIGN.md`: the reasoning behind the tool, the measurements, and where
  it falls short.

**Fixed**

- Patch application derived its strip level from a fixed assumption that every
  diff carries `a/` and `b/` prefixes. A diff with bare destination paths had
  its first real path component stripped instead, so the patch landed in a
  parallel tree, applied cleanly, and left the implementation untouched while
  consuming an attempt. The strip level is now derived from the diff's own
  headers, and a modification resolving outside the task's code directory is
  rejected.
- Transport failures reached the user as a full traceback through several
  library layers. A dropped connection, an unresolvable host or a timeout now
  produces one actionable sentence. `QIKLY_TRACEBACK=1` restores the full stack.
- Reports are no longer attempted for a run that never wrote a log, which
  previously buried the real error under three "no transaction log found"
  messages.

**Documentation**

- README rewritten as a fast-start guide with a worked walkthrough for running
  against your own data and fixtures; the long-form material moved to
  `docs/DESIGN.md`.
- Corrected task counts and per-stage failure figures throughout. Earlier text
  described a single run of nine tasks; the figures are now from the 427-run
  sweep and the tenth task is included.
