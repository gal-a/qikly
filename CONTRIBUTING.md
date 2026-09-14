# Contributing to qikly

The contribution that helps most is a **new example task**, especially from a
domain the ten bundled tasks do not cover. Today they are calculations,
clean-ups and merges on CSV files, plus one log summary. A task from sensor
data, finance, healthcare records or logistics shows the tool working
somewhere new, which a longer list of CSV pipelines cannot.

Found a bug, or tried it and got stuck? Use the
[install or run problem](https://github.com/gal-a/qikly/issues/new?template=install_or_run_problem.yml)
form, or tell us what happened in the
[feedback thread](https://github.com/gal-a/qikly/discussions/6).

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

## 3. The files

Everything lives under `src/qikly/inputs_public/`, named by a task id in upper
case with a family prefix: `CALC_`, `ETL_`, `MERGE_` or `AGG_`, or a new one for
a new domain.

| File | Contents |
|---|---|
| `config/tasks/<TASK_ID>.yaml` | The task: `task_id` matching the filename, `task_name`, `description`, `inputs`, `outputs`, `interface`, `requirements`, `acceptance_criteria`. Start from a bundled one: `qikly --explain CALC_TAX` prints it in full. |
| `data/<TASK_ID>/input_01.csv`, `input_02.csv` | The fixture rows. In the task file, write the `inputs:` paths as `inputs_private/data/<TASK_ID>/...`, like every bundled task: a run copies bundled fixtures there first. |
| `reference/<TASK_ID>/` | Optional. A hand-written implementation known to satisfy the criteria, as `MERGE_SALES` and `MERGE_STOCK` have. If you add one, add its checks to `tests/test_reference_implementations.py`. |

Two other places count the bundled tasks, so update them too:
`tests/test_demo_claims.py` asserts how many there are, and the docs say "ten"
in several places, including the task list in `docs/design_3_mechanism.md`.

## 4. Check it, in this order

From a clone, with `pip install -e .`:

```bash
qikly --validate --tasks <TASK_ID>         # free: structure, fixtures, placeholders, vague criteria
qikly --explain <TASK_ID>                  # free: what each agent receives
qikly --check-criteria --tasks <TASK_ID>   # one model call: criteria that contradict each other
qikly --demo --tasks <TASK_ID>             # a real run, about a cent on the default model
python -m pytest -q                        # the whole suite, offline
```

A run that does not converge is still worth sending. Say so in the pull
request: a task that stalls tells us something too.

## 5. The pull request

Include:

- the proposal issue it closes
- the provider and model the run used, and whether it converged
- where the fixture data came from

## Credit

Every accepted task is credited by name or GitHub handle in the changelog entry
for the release that ships it. You can also add the contributor badge to your
profile or README:

[![qikly task contributor](https://img.shields.io/badge/qikly-task_contributor-2b8f95)](https://test.qikly.com/?ref=contributor)

```markdown
[![qikly task contributor](https://img.shields.io/badge/qikly-task_contributor-2b8f95)](https://test.qikly.com/?ref=contributor)
```

Contributions are accepted under the project's
[Apache License 2.0](https://github.com/gal-a/qikly/blob/main/LICENSE).
