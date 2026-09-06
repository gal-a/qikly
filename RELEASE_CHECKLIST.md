# Release checklist

Run this before every PyPI upload. It exists because every bug found in this
project so far was found by someone looking, not by anything watching, and a
checklist is the cheapest way to make looking systematic.

The rule: **the wheel is the artefact, not the source tree.** A source tree has
every file whether or not the wheel ships it, so anything verified only in the
working directory is not verified.

## 1. The suite passes

```bash
pytest -q
```

No API key should be set, and none is needed. Every test in `tests/` runs
offline, and `conftest.py` fails any test that opens a socket. A suite that
needs credentials gets skipped in CI, and a skipped suite catches nothing.

## 2. The central claim still holds

```bash
pytest tests/test_withholding.py -q
```

Called out separately because it is the one test whose failure invalidates the
project rather than the build. If the acceptance criteria reach the coding
agent, a passing run stops being evidence of anything. Do not release on a
failure here, and do not "fix" it by changing the test.

## 3. Build, and install into a clean environment

First check no experiment is running. The research scripts write throwaway task
configs such as `CALC_TAX_EFI.yaml` into `inputs_public/config/tasks/` and
delete them when the run ends, so a wheel built mid-sweep ships them as though
they were bundled tasks.

```bash
git status --short   # must be clean; no *_EFI, *_EFR, *_CONV, *_ARM*, *_BASE
```

```bash
rm -rf dist build
python -m build

python -m venv /tmp/fresh
/tmp/fresh/bin/pip install dist/*.whl
```

Then confirm the packaged data actually shipped:

```bash
/tmp/fresh/bin/python -c "import qikly, os; p=os.path.dirname(qikly.__file__); \
  print(os.path.exists(os.path.join(p,'inputs_public/config/settings.yaml')), \
        os.path.isdir(os.path.join(p,'inputs_public/agent_defs')), \
        os.path.isdir(os.path.join(p,'inputs_public/config/tasks')))"
```

Three `True`s. A missing `package-data` entry is invisible from the source tree
and fatal on a user's machine.

## 4. The demo runs end to end

```bash
cd /tmp && /tmp/fresh/bin/qikly --demo
```

From a directory that is **not** the repository, so a path bug that silently
resolves against the source tree has nowhere to hide. It should finish in about
thirty seconds and write only inside its own output directory.

## 5. No stale names

```bash
grep -rIn "v_and_v\|v-and-v\|test_qikly\|test-qikly" --exclude-dir=.git --exclude-dir=outputs --exclude-dir=build --exclude-dir=dist --exclude-dir=.pytest_cache --exclude-dir=__pycache__ --exclude=ci.yml --exclude=CHANGELOG.md --exclude=RELEASE_CHECKLIST.md .
```

Must return nothing. The three excluded files name the old project on
purpose, so without them the check always matches itself. Also check the
places grep does not reach: the PyPI project
description, the GitHub repository name and topics, and the URLs in
`pyproject.toml`.

## 6. Version and changelog

- `pyproject.toml` `version` and `src/qikly/__init__.py` `__version__` agree.
- `CHANGELOG.md` has an entry for this version.
- The git tag matches.
- PEP 440 normalises `1.01` to `1.1`, so write `1.0.1` and mean it.

## 7. Numbers in the documentation still match the runs

Any figure in `README.md` or `docs/` that came from a measurement should still
be reproducible from `outputs/reports/`. When a run contradicts a documented
number, the document changes, not the number.

## 7b. Write the release title for the user, not the changelog

The GitHub release **title** is printed in every user's terminal, by the
version check, the next time they run anything:

```
qikly 0.3.0 is available + <your title here> (you have 0.1.0)
```

That one line is the only channel this project has to reach people who have
already installed it, and it is deliberately the only one: the version check
reads public indexes and never fetches text from a server the maintainer
controls, because a mechanism that prints whatever the maintainer decides
later is not a version check.

So the title has to earn its place. Say what changed and whether to hurry:

```
  good   Security fix: patches could be written outside the output directory
  good   Convergence figures corrected after re-measurement, see CHANGELOG
  bad    v0.3.0
  bad    Various improvements and bug fixes
```

Anyone can open the release and confirm the title matches what shipped, which
is what makes it a claim rather than an announcement.

## 8. Upload

Do not upload by hand. Push the tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/release.yml` takes it from there. It refuses to publish
unless the tag agrees with the version in `pyproject.toml`, runs the tests on
the exact tree being published, builds both artefacts, installs the wheel into
a clean virtualenv and checks every console script resolves and no experiment
leftovers reached the bundled tasks. Then it uploads through PyPI's trusted
publishing, exchanging the workflow's own short-lived identity for an upload
credential. **No API token exists anywhere**, so there is none to leak, and
nothing can publish `qikly` except that workflow on that repository.

The one-time PyPI setup is in the workflow's header comment and has to be done
before the first tag or the upload step will fail with no publisher configured.

Uploading by hand still works if the workflow is broken, and then `twine check
dist/*` first: it catches a malformed long description, which PyPI rejects
only after upload, and a rejected version number cannot be reused.

## After release

Install from PyPI in yet another clean environment and run the demo once more.
That is the only check that exercises the actual published artefact rather than
a local build of it.
