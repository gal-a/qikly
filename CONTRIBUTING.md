# Contributing to qikly

**Users are encouraged to contribute their own tasks.** A new example task is
the contribution that helps most, especially from a domain the thirteen bundled
tasks do not cover. Today they are calculations,
clean-ups and merges on CSV files, one log summary and three vehicle sensor tasks.
A task from finance, healthcare records or logistics shows the tool working
somewhere new, which a longer list of CSV pipelines cannot.

Found a bug, or tried it and got stuck? Use the
[install or run problem](https://github.com/gal-a/qikly/issues/new?template=install_or_run_problem.yml)
form, or tell us what happened in the
[feedback thread](https://github.com/gal-a/qikly/discussions/6).

Want to work on the code itself, such as tooling, CI, typing or performance?
See [Working on the code](#working-on-the-code) at the end of this page.

## 1. Propose it first

Open a [task proposal](https://github.com/gal-a/qikly/issues/new?template=task_proposal.yml):
the domain, what the module does, one example criterion and where the data
comes from. It takes a few minutes, stops two people writing the same task,
and settles the scope before you spend time on fixtures.

## 2. What makes a good task

- **One self-contained Python module that transforms data.** It reads input
  files and writes one output: the kind of code qikly is for.
- **Requirements are the decisions, acceptance criteria are the consequences.**
  For any line, ask whether two competent developers, given only the
  requirements, could legitimately disagree about it. If they could, it is a
  decision and belongs in `requirements`, because the coding agent never sees
  `acceptance_criteria`.
- **Criteria name values, not qualities.** "An order of exactly 100.00 receives
  a discount of 10.00", not "discounts are applied correctly". A named value
  forces a test at the boundary.
- **Every criterion is reachable from the fixture rows.** A criterion no input
  row can trigger produces a test that passes whatever the code does. Eight of
  the ten bundled tasks once had one, so check each criterion against the rows.
- **Data you are free to publish.** Synthetic, or openly licensed. It ships in
  the package under Apache 2.0, so no personal or company data.

## 3. Name it

The task id names its file, its data folder and every output folder a run
writes, so it has to stay unambiguous as more tasks arrive.

- **`FAMILY_SUBJECT`, in upper case.** Words joined by single underscores, at
  least two of them, at most 32 characters: `CALC_TAX`, `ETL_NAME_SPLIT`.
- **The family says what kind of task it is.** Use an existing one when it fits:
  `CALC_` for calculations, `ETL_` for clean-ups and normalisation, `MERGE_` for
  combining sources, `AGG_` for summaries. A new domain gets a new short family,
  such as `SENSOR_` or `LEDGER_`, agreed in the proposal.
- **The subject says what it works on**, specifically enough that nobody would
  pick it for a different task: `MERGE_STOCK`, not `MERGE_DATA`.
- **No clash with an existing task, even in a different case.** `Calc_Tax` and
  `CALC_TAX` cannot both exist on Windows or macOS.
- **Never end it in `_VERIFY`.** `qikly --scaffold` adds that suffix to the tasks
  it writes.
- **Claim the id in your proposal.** That is how two contributors avoid picking
  the same one.

`tests/test_bundled_task_names.py` checks every rule above, so a clash fails the
build instead of surfacing later. One conflict it cannot see: a user's own task
with the same id replaces the bundled one in their project, without a warning. A
specific subject makes that unlikely.

## 4. The files

Everything lives under `src/qikly/inputs_public/`, named by the task id from
step 3.

| File | Contents |
|---|---|
| `config/tasks/<TASK_ID>.yaml` | The task: `task_id` matching the filename, `task_name`, `description`, `inputs`, `outputs`, `interface`, `requirements`, `acceptance_criteria`. Start from a bundled one: `qikly --explain CALC_TAX` prints it in full. |
| `data/<TASK_ID>/input_01.csv`, `input_02.csv` | The fixture rows. In the task file, write the `inputs:` paths as `inputs_private/data/<TASK_ID>/...`, like every bundled task: a run copies bundled fixtures there first. |
| `reference/<TASK_ID>/` | Optional. A hand-written implementation known to satisfy the criteria, as `MERGE_SALES` and `MERGE_STOCK` have. If you add one, add its checks to `tests/test_reference_implementations.py`. |

Two other places count the bundled tasks, so update them too:
`tests/test_demo_claims.py` asserts how many there are, and the docs say "thirteen"
in several places, including the task list in `docs/design_3_mechanism.md`.

## 5. Check it, in this order

From a clone, with `pip install -e .`:

```bash
qikly --validate --tasks <TASK_ID>         # free: structure, fixtures, placeholders, vague criteria
qikly --explain <TASK_ID>                  # free: what each agent receives
qikly --check-criteria --tasks <TASK_ID>   # one model call: criteria that contradict each other
qikly --demo --tasks <TASK_ID>             # a real run, about a cent on the default model
python -m pytest -q                        # the whole suite, offline
```

The whole suite takes 8 to 12 minutes run serially. With
`pip install pytest-xdist` it runs in parallel in a few minutes:

```bash
python -m pytest -q -n auto --dist loadgroup
```

`--dist loadgroup` matters: the tests that work in the real project folder
are marked `xdist_group("project_root")` and must run on one worker, one
after another. A new test that writes to the project folder rather than to
`tmp_path` needs the same mark.

A run that does not converge is still worth sending. Say so in the pull
request: a task that stalls tells us something too.

## 6. The pull request

Include:

- the proposal issue it closes
- the provider and model the run used, and whether it converged
- where the fixture data came from

## Working on the code

The open improvement issues are listed with the
[good first issue](https://github.com/gal-a/qikly/labels/good%20first%20issue)
and [help wanted](https://github.com/gal-a/qikly/labels/help%20wanted) labels.
Comment on the one you want, so two people do not pick the same one, and ask
before starting anything large.

### Set up

Python 3.10 or newer. From a clone:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scriptsctivate
pip install -e ".[all-providers]"
pip install pytest-xdist
```

Running the tests needs no API key and no network: the suite is offline. A key
is only needed for a real run (`qikly --demo`), see
[provider key setup](docs/PROVIDER_KEY_SETUP.md).

### Run the tests the way CI does

```bash
python -m pytest -q -n auto --dist loadgroup
```

CI runs this on Python 3.10 to 3.14, on Linux, plus Windows and macOS. Keep
`--dist loadgroup`: without it, two tests that share the project folder can race
on different workers and fail for reasons that are not bugs. Serial runs take
8 to 12 minutes.

### Where things are

- `src/qikly/` is the package. `cli.py` is the entry point, `mutation.py` and
  `mutation_score.py` plant and score faults, and `orchestrator/` runs the agents.
- `tests/` mirrors it. A change to behaviour needs a test that fails without it.
- `tools/release_check.py` and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) cover
  releases. Maintainers do the release, contributors do not need to.

To see how the parts fit before you change one, read the three design documents,
in this order:

1. [The case for it, and one repair end to end](docs/design_1_case_study.md)
2. [What was measured, and the results withdrawn](docs/design_2_performance.md)
3. [How it is built](docs/design_3_mechanism.md)

### Send the pull request

- One issue per pull request, and say which one it closes.
- Keep the change small. Several small pull requests are easier to review than
  one large one.
- The tests workflow must be green. It runs on every pull request.
- If an AI assistant helped write the change, say so in the description.
- The maintainer reviews every pull request and merges it by hand. Nothing
  merges on its own.

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Credit

Every accepted task is credited by name or GitHub handle in the changelog entry
for the release that ships it. You can also add the contributor badge to your
profile or README:

[![qikly task contributor](https://img.shields.io/badge/qikly-task_contributor-2b8f95)](https://qikly.com/?ref=contributor)

```markdown
[![qikly task contributor](https://img.shields.io/badge/qikly-task_contributor-2b8f95)](https://qikly.com/?ref=contributor)
```

Contributions are accepted under the project's
[Apache License 2.0](https://github.com/gal-a/qikly/blob/main/LICENSE).
