# Release checklist

**Run `python tools/release_check.py` first.** It performs every check below
that a machine can perform, and refuses to pass on a failure that has actually
happened to this project before. This document carries the reasoning; that
script carries the teeth. Run `--after` once the workflow finishes, to confirm
the three places a release lands actually agree.

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

**Test the wheel, never an editable install.** A venv made with `pip install -e .`
imports the source tree, so it reports the release version while exercising
nothing that ships. An MCP host pointed at such a venv looks verified and is
not, which nearly happened on 0.4.3. An `__editable__.qikly-*.pth` in
`site-packages` is the tell.

## 4. The demo runs end to end

```bash
cd /tmp && /tmp/fresh/bin/qikly --demo
```

From a directory that is **not** the repository, so a path bug that silently
resolves against the source tree has nowhere to hide. It should finish in about
thirty seconds and write only inside its own output directory.

## 5. No stale names

```bash
grep -rIn "v_and_v\|v-and-v\|test_qikly\b\|test-qikly\b" --exclude-dir=.git --exclude-dir=outputs --exclude-dir=build --exclude-dir=dist --exclude-dir=.pytest_cache --exclude-dir=__pycache__ --exclude=ci.yml --exclude=CHANGELOG.md --exclude=RELEASE_CHECKLIST.md .
```

Must return nothing. The three excluded files name the old project on
purpose, so without them the check always matches itself. Also check the
places grep does not reach: the PyPI project
description, the GitHub repository name and topics, and the URLs in
`pyproject.toml`.

## 6. Version and changelog

- `pyproject.toml` `version` and `src/qikly/__init__.py` `__version__` agree.
- `server.json` agrees too, in all three places the version appears there:
  the server version, the package version, and the `qikly[mcp]==` pin inside
  the `--from` argument. It is the MCP Registry listing, so a missed bump
  advertises one version and installs another. A test holds them together.
- **After the upload, republish the listing**: `mcp-publisher login github`
  then `mcp-publisher publish`, from the repository root. Nothing in CI does
  this and nothing can, since it needs a human GitHub login, so it is the one
  release step with no guard behind it. Skipping it leaves the registry, and
  therefore VS Code's MCP gallery, offering the previous version: the listing
  names a version and installs it by pin, so a stale entry installs stale
  software rather than merely looking out of date.
- **Getting `mcp-publisher`:** it is a release binary, not a pip package.
  Download the archive for your platform from the `modelcontextprotocol/registry`
  releases page and unpack it with `tar -xzf`. Run `mcp-publisher validate`
  first, which needs no login. The login token lasts about five minutes, so
  publish straight after logging in, and read "cannot publish duplicate
  version" as already listed rather than as a failure.
- The Action pins written in prose bump too: `gal-a/qikly@vX.Y.Z` in
  `README.md` and `docs/PROVIDER_KEY_SETUP.md`. Those are examples someone
  copies, so a stale one hands out a tag predating the fix they came for. The
  `@v0` in the workflow templates is the moving alias and stays as it is.
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
qikly 0.4.0 is available + <your title here> (you have 0.3.0)
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

## 7c. The landing page catches up here

`docs/index.html` is served at test.qikly.com to people running the *published*
version, so everything it names has to exist in the version they can install.
Anything that has landed on the branch but not on PyPI waits, and this is the
step where it goes in. Nothing tests that page, which is why it needs a line in
the one list that gets read before every upload.

Waiting for the next upload:

- The `ADAS_*` tasks by name, in "Who it is for" and in the use-case table. The
  page currently says which domains they serve without naming the tasks.
- Independence evidence: for code you supply, a run reports whether git says
  the criteria were settled before that code's first commit, and prints the
  bounds of that claim beside it. The use-case row for "code someone else
  wrote" is where it belongs.

Clear an item as you add it, and add one whenever something lands on the branch
that the page cannot honestly show yet.

## 8. Upload

Do not upload by hand.

**Check which remote you are pushing to before you push anything.** There are
two, and only one of them is public:

```bash
git remote -v
```

`origin` is `gal-a/qikly-initial`, which is **private**. `public` is
`gal-a/qikly`, which is the one that releases. This checklist said `origin` for
several releases and that is wrong: a tag pushed there publishes nothing and
fails silently, because the release workflow does not live in that repository.

**Push the branch before the tag, and push it to `main`.** The working branch
is `public-v2`; the repository's default branch is `main`. Pushing the branch
under its own name leaves `main` behind, and the tag still releases, so
everything looks fine while the repository every visitor sees stays on the old
version. That happened on 0.4.9 and this paragraph is why.

```bash
git push public <sha-or-branch>:main
git ls-remote --heads public        # main must now be the commit you are tagging
```

Only then tag, and push the tag to the same remote:

```bash
git tag v0.3.0
git push public v0.3.0
```

Pushing a tag whose commit is not on the remote is the 0.4.7 failure: the tag
names nothing, the workflow has no tree to build, and the tag then has to be
deleted and recreated.

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

**First, check the three places agree.** They can disagree silently, and two of
them are what other people actually consume:

```bash
git ls-remote --heads public | head -2   # main is the released commit
curl -s https://pypi.org/pypi/qikly/json | grep -o '"version":"[^"]*"' | head -1
```

and the registry listing, which has no guard at all behind it:
<https://registry.modelcontextprotocol.io/v0/servers?search=qikly> must show
the new version as latest **and** the matching `qikly[mcp]==` pin. A stale
entry there installs the old software rather than merely looking out of date.

Why `main` matters beyond tidiness: the README's images are served from
`raw.githubusercontent.com/gal-a/qikly/main/...`, so a stale `main` makes PyPI
render the new README around the old diagrams, and the CI badge reads
`?branch=main`, so it reports a run that predates the release.

**Then** install from PyPI in yet another clean environment and run the demo
once more.
That is the only check that exercises the actual published artefact rather than
a local build of it.

**Glance at the Marketplace box.** Open the release on GitHub and click Edit:
"Publish this Action to the GitHub Marketplace" has been ticked already on the
releases the workflow creates, as seen on 0.4.1, and the Marketplace page then
names the new release as its latest. Only if the box is unticked, tick it and
Update release.

The PyPI badge at the top of the README keeps showing the previous version for
up to 12 hours. shields.io caches it for that long and ignores a shorter
`cacheSeconds`, so this corrects itself and needs no action.

Then check the landing page's footer links still answer. One points at the
author's books site, which this repository does not control:

```bash
QIKLY_CHECK_LINKS=1 python -m pytest -q tests/test_landing_page_footer.py
```

In PowerShell, set `$env:QIKLY_CHECK_LINKS=1` first. If the books address has
moved, change `BOOKS_URL` in that test and the footer in `docs/index.html`
together.
