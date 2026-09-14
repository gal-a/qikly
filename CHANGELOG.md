# Changelog

Versions follow [semantic versioning](https://semver.org). Version strings are
PEP 440 normalised, so they are written `1.0.1` rather than `1.01`, which
packaging tools would read as `1.1`.

## Unreleased

### Fixed
- **The diagram shows on PyPI.** PyPI prints a mermaid block as source, so the
  project page showed forty lines of flowchart code where the README's diagram
  should be. The README now shows an image of the diagram, rendered from the
  one in `docs/design_1_case_study.md` by `tools/render_flow_diagram.py`, and a
  test fails when the image falls behind that source. GitHub shows the same
  image.
- **The README's example of an exact pin named `@v0.3.4`,** three releases
  old. The check for stale pins only looked for the full `gal-a/qikly@v...`
  form, so a bare `@v0.3.4` in a sentence slipped past it. It now catches both.

## 0.4.4

> Scaffolded tasks can now fix the code they test: upgrade before verifying your own module

### Added
- **`--validate` warns about scaffold placeholders left in a task.** A file
  still carrying `TODO` in its requirements, criteria or interface passed every
  other check, and a run would have sent the placeholders to the agents as the
  specification.
- **The refinement loop proposes fixture rows for the criteria it adds.**
  Refinement reads converged code and adds criteria about what that code could
  still get wrong, which is often an input the fixtures do not contain, and a
  criterion no row reaches yields a test that passes whatever the code does.
  `refine_acceptance_criteria` now runs the fixture proposer over the refined
  bar when it finishes, lists the added criteria first, and logs how many have
  no data behind them. Like `propose_fixtures` itself, it writes a report for
  review and never a fixture.

### Fixed
- **A scaffolded task could never fix the code it was testing.** `--scaffold`
  wrote `interface.module` as the file's path relative to the project, such as
  `billing`, but a run installs the code into `outputs/agent_src/code/<task>/`
  and runs pytest from the project root. So the tests imported the original
  file, the coding agent patched the copy, and no fix ever reached a test. The
  module is now `outputs.agent_src.code.<task>.<file>`, the path the bundled
  tasks already used. Found by an audit and reproduced end to end: a patched
  copy returning `PATCHED` against tests that saw `ORIGINAL`. A regression test
  now runs that same check. Affects every task scaffolded with 0.4.3 or earlier;
  change the `module:` line of one by hand to fix it.
- **The MCP `qikly_scaffold` tool and `--scaffold` named the same task
  differently**, `BILLING` against `BILLING_VERIFY`. The suffix is now added in
  one place, so they agree.
- **Scaffold's next step now runs `--validate --tasks <task>`.** Unscoped, it
  also checked every bundled example, which buried the one result that mattered.
- **The `TODO` warning matches only scaffold's own placeholders**, so a
  requirement that mentions TODO comments is no longer flagged.
- **Scaffolding a module on a different drive from the project failed on
  Windows.** `os.path.relpath` has no answer across drives and raises, so
  `--scaffold` and the MCP `qikly_scaffold` tool stopped with "path is on
  mount 'D:', start on mount 'C:'". A module on another drive is now named
  by its file, with its seed path written absolute. Found because GitHub's
  Windows runners are laid out that way, the checkout on D: and temporary
  folders on C:, and reproduced locally on a mapped drive.

### Changed
- **The VS Code install button and the Claude Code line use `uvx`.** The
  button wrote a bare `qikly-mcp`, which pip on Windows often installs off
  `PATH`, so the first click frequently produced a server that would not
  start. It now writes `uvx --from qikly[mcp] qikly-mcp`, the command the MCP
  Registry listing already uses, which needs uv and no separate pip install.
  In Claude Code the one line is `claude mcp add qikly -- uvx --from "qikly[mcp]" qikly-mcp`.
  The pip route stays documented in `docs/mcp.md`.
- **Fewer places saying the same thing.** The README's MCP section is a short
  pointer to `docs/mcp.md` rather than a second copy of it, the troubleshooting
  page links the explanation of why runs stall at the unit stage instead of
  repeating it, and `design_3_mechanism.md` defines the task file's three parts
  once. The README also gains a free first step near the top,
  `qikly --explain CALC_TAX`, which needs no API key.
- **A place to say how trying it went.** The README and the quick start link a
  Discussions thread for reports, whether a run worked, stalled or never got
  past install. The MCP docs now say what has been verified: the server is
  tested in VS Code and in Claude Code, and the setup for other hosts follows
  the standard but has not been checked end to end.
- **`--scaffold` writes one task file, not two.** By default it writes
  `<NAME>_VERIFY.yaml`, the task that tests the code you already have, and
  `--fresh` writes the task for a new implementation of the same interface
  instead. It used to write both and ask you to delete one. It now ends with
  numbered next steps that name the input file to add and put `--validate`
  before the run: the old `Then: qikly --tasks X` failed straight away, because
  scaffold never creates input data. Its comments use the decisions versus
  consequences rule, and the landing page links the quick start on your own
  data beside the install commands. The MCP `qikly_scaffold` tool returns the
  same default task and names the file to save it as, so step 1 of the quick
  start also works from inside VS Code.
- **Quick start is its own page, `docs/QUICK_START_ON_YOUR_OWN_DATA.md`.**
  The README kept its three-command demo, but everything needed to try qikly
  on your own module sat after about 2,600 words of explanation. The new page
  starts with the demo and five steps from `--scaffold` to a first run,
  including the one scaffold leaves to you, adding input data, and then keeps
  the command table and everything the old `USING_YOUR_OWN_DATA.md` had. That
  page is removed rather than left behind as a pointer.
- **The split between `requirements` and `acceptance_criteria` now has a rule
  you can apply.** The docs said spec-level statements go in one and checkable
  edge cases in the other. That sends a measurement convention or an exemption
  into the withheld half, where it produces the stuck loop the very next
  paragraph warned about. The rule is now decisions versus consequences, with
  one test for any line: could two competent developers, given only the
  requirements, legitimately disagree about it? The authoring guide, the
  mechanism write-up, the starter task and the `--scaffold` output all say so.
  The starter task had followed the old rule: its criterion that a quantity of
  0 is rejected was a decision its requirements never stated, and the
  requirement is now there.
- **"Doesn't a failing test give the criteria away?" is answered where the
  objection is raised**, in the README and on the landing page, rather than
  only in the case study.
- **The stale-name guard matches whole words**, so a test named after the
  package, such as `test_qikly_run`, no longer fails CI. It still catches a
  path that names the old project.

## 0.4.3

> Listed in the MCP Registry, so VS Code's own gallery can find it

### Added
- **qikly has a listing for the MCP Registry, `server.json`.** That registry
  is what VS Code's own gallery reads: searching `@mcp` in the Extensions view
  shows servers from it, and only servers listed there can be added that way.
  The listing carries the icon in four forms, PNG and SVG for a light and a
  dark background, served from the landing page, because clients are only
  required to support PNG and merely encouraged to support SVG.

  **The install block carries the `[mcp]` extra, and that is the part worth
  writing down.** A bare `uvx qikly` would install without the extra and
  produce exactly the server-that-will-not-start of 0.4.1 and 0.4.2, for every
  stranger who clicked install, and the console script is named `qikly-mcp`
  while the package is named `qikly`. Both facts live in the arguments:
  `--from qikly[mcp]==<version>` as a runtime argument, and `qikly-mcp` as a
  positional, both inside `runtimeArguments`. Verified with uv 0.12.13, and it
  is the shape the live `ai.gateco/gateco` listing uses, read from the registry
  on 2026-09-12. The placement is not cosmetic: with the script name in
  `packageArguments` instead, a client composing runtime arguments, then the
  package, then package arguments produces `uvx --from qikly[mcp]==X qikly
  qikly-mcp`, which fails with "unrecognized arguments: qikly-mcp". The
  version therefore appears three times in `server.json`, and a test holds
  them together.

  **It was nearly built the hard way, and that is the useful part.** A first
  pass sampled four pages of the registry, concluded that no entry can express
  an extra, and added a second, code-free distribution whose only job was to
  depend on `qikly[mcp]`. It worked. It also cost a second PyPI project, a
  second pending publisher, the version pinned in a fourth file, a workflow
  check to hold the pair together, and a shared console script that
  `pip uninstall` could take away from the package still needing it. Reading
  the whole registry rather than four pages of it found 1,513 package entries
  using runtime arguments, out of 21,240, by full pagination on 2026-09-12. So
  the extra had been expressible all along. The measurement was wrong before
  the design was, and the registry keeps growing, so that count is a reading
  on a date rather than a fact about the ecosystem.

  The other alternative, making `mcp` a hard dependency, was rejected on
  measurement too: 18 extra packages and about 19.5 MB on a 48 MB base, some
  40% more, paid by every command line and every CI run that never starts a
  server. Measured 2026-09-12 as the on-disk size of `site-packages`,
  excluding `__pycache__`, for `qikly==0.4.2` against `qikly[mcp]==0.4.2` in
  two fresh venvs, CPython 3.10 on Windows, where `pywin32` is the largest
  single item and installs on Windows only. An earlier figure of 26 MB in a
  draft of this entry counted `__pycache__`, which is bigger in the bigger
  venv and inflated the difference. The extra resolves through `mcp>=2.0,<3`,
  so this number drifts with its dependencies and is a measurement on a date,
  not a property of the package.

  Publishing needs the package on PyPI first, because the registry proves
  ownership by finding `mcp-name: io.github.gal-a/qikly` in the README that
  PyPI serves. That marker ships here as an HTML comment, so the listing can
  only be published after this release, never before.
- **A run records which code produced it, not just which release.** Every run
  summary already carried `qikly_version`, which is exact for an install from
  PyPI and misleading from a source checkout: the version only moves on
  release day, so 420 runs in this project's own history are stamped `0.1.0`
  across weeks of changing code. When qikly runs out of its own git checkout,
  the provenance now also carries the commit, whether the tree had
  uncommitted changes, whether that commit is a tag, and the Python version.
  The same line opens the run in the console and appears in both HTML report
  headers, because a console capture or a saved report is often all anyone
  keeps.

  The guard is the part worth reading. A virtual environment commonly sits
  inside the user's own repository, so asking git about the package directory
  would record *their* commit as qikly's: not a gap but a confident wrong
  answer. A git root is believed only when it actually contains `src/qikly`.

### Fixed
- **A third test stopped writing into the live project.** `tests/test_runs.py`
  had a `project` fixture that redirects to a temp directory, and tests that
  did not ask for it wrote to the real one: a CALC_TAX run summary and
  transaction log from the file's fixed timestamp were sitting in the live
  outputs tree, describing a run that never happened, the log saying every
  test passed while the summary said it failed. Redirecting is now automatic
  for every test in the file rather than something each test has to remember.

- **Four warnings pointed at a heading that was never written.** `cli.py` and
  `orchestrator.py` sent anyone running without acceptance criteria to
  `README.md#auto-generating-acceptance-criteria`, an anchor that has never
  existed in any version of that file, so the one message a person sees at the
  moment they need the explanation led nowhere. The section now exists, in
  `docs/USING_YOUR_OWN_DATA.md`, and the four messages point at it.
- **A docstring escaped nothing and warned about it.** `_demo_root` documents
  `cd C:\Temp\scratch` in a plain string, where `\T` is not a valid escape, so
  Python raised a DeprecationWarning whenever `cli.py` was compiled fresh. The
  docstring is now raw. Invisible from a warm `__pycache__`, which is why it
  survived this long.
### Changed
- **The MCP tool `qikly_check_criteria` is now `qikly_validate`.** It always
  ran the offline check that `qikly --validate` runs, while the command line
  has a separate `--check-criteria` that asks a model whether the
  specification contradicts itself. Same name, different check, one of them
  paid. It misled the first host that used it: asked to check CALC_TAX's
  criteria, GitHub Copilot read `cli.py`, found `--check-criteria`, and tried
  to run the paid checker in a terminal; and when finally pointed at the tool,
  it reported "no contradictions found", which the tool never looks for. The
  new name says what it does, and the description now says in as many words
  that it is not the contradiction check. The old name is not kept as an
  alias: the server shipped a day earlier, and a fifth tool listed under the
  misleading name would keep misleading.

- **The README is 751 lines instead of 1,099, and nothing was deleted.** It had
  become two documents interleaved: the case for reading further, and the
  reference you consult once you have. The reference half moved out whole, to
  `docs/USING_YOUR_OWN_DATA.md` (the task file field by field, criteria from a
  ticket, seeding your own code or tests, where files are read from, fixture
  proposals) and `docs/CONFIGURATION.md` (settings, environment variables,
  provider setup and determinism). Both are linked from where they used to sit.
  The prose was moved as text rather than rewritten, so the two pages inherited
  the documentation guards automatically: they are matched by the same
  `docs/*.md` globs, and the suite grew by six cases without a test being
  written.
- **The comparison table on the landing page stacks on a phone.** Two prose
  columns at 600px left a couple of words per line; each row is now its own
  card, carrying the column name that the dropped header row used to supply.
  The table also described its two sides as qikly's "unit stage" and
  "integration and system stages", a word neither document defines until well
  below it. They are tests, and now say so.

## 0.4.2

> One command prints an MCP config that starts on Windows

### Fixed
- **The Windows install failure has a fix now, not only an explanation.**
  0.4.1 documented why the one-click VS Code button produced a server that
  would not start and made the tools say where they had looked; the button
  itself still wrote a bare `qikly-mcp`. `python -m qikly --mcp-config` prints
  a config naming the full path of the Python that has qikly, run as
  `python -m qikly.mcp_server`, and the folder it was run from as
  `QIKLY_PROJECT_ROOT`. That removes both failures: nothing depends on `PATH`,
  and the editor's open folder no longer matters. `--mcp-config claude` prints
  the `mcpServers` shape for Claude Code, Cursor and most other hosts. It
  prints and never writes, because a host's config file holds the user's other
  servers, and VS Code's allows comments a JSON round-trip would delete. The
  JSON alone goes to stdout, and it runs before the update check, so a pasted
  "qikly X is available" line cannot end up inside mcp.json. A test runs the
  printed command and env for real and completes an MCP handshake with it.
  The README says so directly under the badge, where someone who just clicked
  it will look.
- **A Python file starting with a byte-order mark could not be scaffolded.**
  Python runs such a file happily and Windows tools write the mark routinely,
  PowerShell 5.1's `Set-Content -Encoding utf8` among them. qikly read Python
  sources as plain UTF-8, so the mark arrived as U+FEFF and `ast.parse`
  refused a file Python accepts. Scaffold and the code loader now read with
  `utf-8-sig`. Task YAML and `--criteria-from` were checked and already
  handled it. Found by writing a throwaway test module in PowerShell.
- **The test suite stopped writing into the project it tests.** Two tests
  left their output in the live `outputs/` tree on every run: 1,862 junit
  files from the end-to-end smoke test, and 311 empty `run_all` reports from a
  fake task, against 30 real sweeps. The smoke test already cleaned up five
  report directories and checked that it had; `reports/junit` was missing from
  both lists, so the check passed while the files piled up. It is now one list
  used by both. The `run_all` tests now write to a temporary directory, as the
  robustness test already did.

### Added
- **`python -m qikly`** runs the CLI. It exists for the users the `qikly`
  command fails for: when `qikly-mcp` is not on `PATH`, neither is `qikly`,
  so `--mcp-config` was unreachable by exactly the people who needed it.
- **`mcp` and `model-context-protocol` in the PyPI keywords.** 0.4.0 shipped an
  MCP server and neither the package metadata nor the repository said so.

## 0.4.1

> The MCP tools now say where they looked

### Fixed
- **The one-click install button produced a server that could not start.** It
  writes `"command": "qikly-mcp"`, and on Windows pip routinely installs
  console scripts into a `Scripts` directory that is not on `PATH`, so the host
  reported only that the command was not found. Shipped in 0.4.0 and found by
  the first person to click it. Both the README and
  [`docs/mcp.md`](docs/mcp.md) now say the command has to be on `PATH`, how to
  check, and what to write instead when it is not.
- **A server pointed at the wrong folder said the task was missing and not
  where it had looked.** An MCP host starts the server in the directory the
  editor has open, which is routinely the parent of the qikly project rather
  than the project. "No such task" is then true, useless, and reads as qikly
  being broken rather than misdirected. `qikly_check_criteria` and `qikly_run`
  now name the directory they resolved and the variable that changes it, and
  `qikly_run` refuses instead of starting a run that will spend minutes to
  reach the same answer.

  **Keyed on whether the task resolves, not on whether `inputs_private/`
  exists.** The first attempt used the directory, which declared every fresh
  install broken: bundled tasks ship inside the package and need no
  `inputs_private/` at all. That is the same false alarm
  `validate._input_exists` was written to undo, reintroduced through a
  different door and caught before release. The shape check on the task id
  still runs first, so a traversing id is refused as a security answer rather
  than softened into a lookup one.

### Added
- **The MCP server carries an icon, a title and a link.** Hosts that render
  MCP server icons show a mark rather than a bare command. The icon is the `q` lifted
  out of `docs/images/qikly_wordmark.svg`, the same subpath and the same
  gradient, so it cannot drift from the wordmark. It ships inside the package
  and is embedded as a `data:` URI at runtime, because `docs/` is not in the
  wheel and a `file://` path is a promise about the reader's filesystem that a
  sandbox, a container or a remote window will not keep. A missing icon is not
  an error: a server that refused to start over a picture would be a poor
  trade.

  **Two variants, because one gradient cannot serve both grounds.** Rendered
  at 16 px against VS Code's Light Modern background colours, the wordmark's
  pale-to-teal gradient all but vanished, and measuring it explained why: 1.22:1 and 2.33:1
  against white, where WCAG asks 3:1 of a graphic. On dark grounds the same
  stops measure 7 to 14:1 and are kept. The light variant swaps only the two
  stops, to `#112f2e` and `#2b8f95`, both already in the palette, and measures
  14.29:1 and 3.84:1. Each is tagged with the spec's `theme` field, and a test
  now holds every stop of every variant to 3:1 against the backgrounds it is
  tagged for, so a palette change cannot quietly undo this.

  **VS Code does not show it, and that was measured rather than assumed.** Its
  MCP Servers list and the server's details page kept the generic MCP mark for
  a locally configured server, sent SVG and then PNG, each confirmed on the
  wire and each after a window reload. The PNGs were removed rather than
  shipped for no effect. The icons stay for hosts that draw them, and nothing
  here should be read as a claim about VS Code.
- **`docs/mcp.md` lists the other editors' install schemes** for Visual Studio,
  Cursor, Goose and LM Studio, and says plainly that qikly ships no buttons for
  them because none has been tested here. They differ in how the config is
  encoded, and a button that writes a malformed config is worse than no button,
  because the reader blames the tool rather than the link.

### Changed
- **The update notice is printed again on the way out.** It was the first line
  of the run, and a run prints for minutes, so by the time there is a result to
  look at the line announcing a new release has scrolled off the top. The
  closing line repeats what the opening one computed: no second request, and
  nothing at all when there was no update to announce.

  It goes to **stderr**, and that is what makes it safe to add rather than a
  breaking change. `--json` exists so a caller can parse stdout, and a line
  appended after the JSON would break exactly the callers most likely to be
  parsing it. The opening line is unchanged.

## 0.4.0

> Your document is the input, and qikly speaks MCP

### Added
- **qikly speaks MCP.** `pip install "qikly[mcp]"` and `qikly-mcp` expose four
  tools to any MCP host, so an agent in Claude Code, Codex CLI or Cursor can
  start a run and read the result without leaving the conversation:
  `qikly_run`, `qikly_status`, `qikly_check_criteria`, `qikly_scaffold`.

  A run takes minutes to hours, which is longer than any host will hold a tool
  call open, so `qikly_run` starts a detached run and returns an id and
  `qikly_status` reports on it. The run outlives the terminal that started it.

  The withholding property is the reason this needed care rather than a
  wrapper. An MCP host is usually running its own coding agent, and whatever a
  tool returns becomes that agent's context, so no response carries acceptance
  criteria on any path including the error paths.
  `tests/test_mcp_withholding.py` asserts that on the serialised JSON rather
  than on the dict, because a dict holding criteria under a key nobody prints
  is still a leak the moment anything serialises it. Documented in
  [`docs/mcp.md`](docs/mcp.md), including the part qikly cannot enforce: the
  generated tests are on your disk, so keep them out of your agent's reach.

  `tests/test_mcp_end_to_end.py` spawns the real server as a subprocess and
  speaks the real protocol to it, because every other test here calls the
  functions directly and a server that crashed on startup or registered its
  tools under the wrong names would pass all of them. It skips when the extra
  is not installed, so the base suite stays dependency-free. The withholding
  test was written before the server existed and was checked by making a tool
  leak on purpose, and a redaction pass strips the forbidden keys anyway.

- **`--scaffold module.py --from-doc feature.md` builds the whole task file.**
  Two of the first three people to try qikly asked for the same thing from
  different angles: the artefact they already have should be the input. Both
  halves already existed and nobody had joined them. `--criteria-from` reads a
  markdown page, a ticket export or a `.feature` file, and `--scaffold` reads
  the real signatures out of the module. This is the join: criteria from the
  document, interface from the code.

  **What it deliberately does not fill is `requirements`.** That is the section
  the coding agent reads, and a feature page almost always restates its own
  acceptance criteria in the prose above them, so lifting requirements out of
  the document would hand the criteria to the one agent that must never see
  them, by a route none of the withholding tests watch. It is the same refusal
  as `--scaffold` declining to derive criteria from an implementation.
- **`qikly --check-criteria` now reads the whole specification, and catches a
  criterion that contradicts another criterion.** It looked only for a
  criterion against a requirement, so the fault that is entirely inside the
  criteria block was not merely missed, it was unrepresentable: the finding it
  returns names the requirement a criterion conflicts with, and there was no
  requirement involved. Two criteria that disagree make the suite
  unsatisfiable on their own, whatever the requirements say.

  **Numeric thresholds are no longer exempted as "merely stricter".** The
  prompt tells the model not to report a criterion that is stricter than the
  requirements, because that is the normal and intended relationship between
  the two and without the instruction it reports every criterion in the task.
  On numbers that instruction suppressed real faults: "fails below 2 m" and
  "fails below 2.5 m" read as one rule and a tighter version of it while
  actually disagreeing about every value in between, which is a typo, not a
  design. Different numeric bounds on the same quantity are now always
  reportable, and the finding names the disputed range.

  **The `description` reaches the check.** It carries what the task is for,
  and a criterion measuring something else is wrong in a way the requirements
  alone cannot show.

  Raised by a reader working on vehicle proximity metrics, whose example was a
  requirement failing below 2 m against criteria failing below 2.5 m and
  passing above 2 m. Before these changes the check reported one finding and it
  was neither of the two real faults. It now reports both, naming 2.2 m as a
  distance the suite demands be a pass and a failure at once.

  It remains advisory, one model call, and it never edits a task or blocks a
  run. It also has to sit here, before the run: everything inside the loop is
  bound by the rule the tool exists for, so the one agent placed to notice that
  a spec disagrees with itself is the one forbidden from seeing half of it. A
  specification fault is not a bug the loop can find.
- **`qikly --validate` now catches a requirement that restates a criterion.**
  The refusal above is only worth anything if the leak is caught when somebody
  pastes it in by hand, which is the obvious next move. Word overlap scored
  against the criterion rather than the requirement, so a criterion buried in a
  long pasted paragraph is caught rather than diluted. A warning, not an error,
  because the measure is blunt and a false positive must not stop a run.
- **A one-click install button for VS Code, and a live PyPI version badge.**
  The install button writes the MCP configuration into VS Code, which is the
  step that otherwise means finding out that your host spells the config key
  `servers` where another spells it `mcpServers`. It sets no
  `QIKLY_PROJECT_ROOT`, because VS Code starts the server in the workspace
  folder and that is already where qikly looks. The version badge reads PyPI
  rather than repeating a number written in the README, which is the kind of
  number that goes stale the release after someone stops checking it.
- **`--start`, `--status` and `--runs`.** The mechanism underneath the MCP
  server, useful on its own: start a run, close the terminal, ask later. State
  is derived from what the run writes rather than stored, so it is right even
  after a crash, and `stalled` is reported separately from `failed` because a
  crash and a failing suite are different things.

### Fixed
- **The restatement check counted a task's own field names as evidence.** Word
  overlap treated every word alike, so a criterion built mostly from field
  names scored against any requirement naming those fields. `end_date must not
  be earlier than start_date` reduces to three scoring words, two of them field
  names, and it produced three warnings on one shipped task, none of them a
  restatement: the word carrying the whole criterion is "earlier" and it
  appeared in no requirement. A word appearing in 40% or more of a task's own
  criteria is now discounted as that task's vocabulary. Below three criteria
  the measure is undefined rather than weak and nothing is discounted, and a
  criterion made entirely of common vocabulary falls back to the raw score, so
  a verbatim paste is still caught at 100%.
- **One finding repeated across every task drowned the findings that were
  not.** Nine of the bundled tasks carry the same output-contract restatement,
  one per file, and it is real every time: the coding agent cannot write the
  code without being told the JSON shape, so the contract belongs in
  `requirements`, and the suite should still check it. Printing it nine times
  buried the one task that had no acceptance criteria at all. A finding
  appearing in three or more tasks is now printed once with the list of tasks
  it applies to. The warning count is unchanged and says how many were
  collapsed, because the check is advisory and quietly reporting fewer problems
  than it found would be the wrong kind of quiet. Across the bundled tasks this
  is 23 warnings on 23 lines before, 18 warnings on 8 lines after.
- **A contradiction finding quoted the prompt's own bullet back at you.** The
  statements reach the model as `- <statement>`, so a reply quoting one
  faithfully carried the list marker into the report, where it read as part of
  the requirement rather than as formatting qikly had added.
- **Two documents described the diagram in colours it is not.** The landing
  page called the repair cycle "the dashed orange one" long after that arrow
  became purple, and the README called the same arrows red while
  `design_1_case_study.md` called them purple. Found by a reader. A test now
  checks the prose against the tokens and the mermaid `linkStyle` values, in
  both files, because a palette change silently invalidates a sentence a
  hundred lines away.
- **The MCP redaction pass could not see criteria inside a text blob.** It
  strips forbidden dict *keys*, and `qikly_scaffold` returns a whole task file
  as one string, so the same criteria removed as a key travelled through
  untouched as YAML. Nothing leaked: scaffold writes `TODO` placeholders and
  refuses to derive criteria from an implementation. It is fixed because
  `--from-doc`, added in this same release, merges real criteria into exactly
  that YAML, which puts the two features one plausible wiring change apart from
  a leak the guard would never have seen. Criteria in a YAML string are now
  replaced with a `[withheld]` marker, `TODO` placeholders survive because a
  scaffold with an empty criteria section would be useless, and
  `qikly_scaffold` goes through the guard like every other tool.
- **A task id can no longer escape the output tree.** It arrives straight from
  an MCP tool call and became part of several file paths unchecked, so
  `../../evil` normalised two levels above the project and wrote there. Task
  ids are now matched against `[A-Za-z0-9_.-]+` before any path is built.
- **Two runs started in the same second no longer collide.** A run id is the
  task plus a one-second timestamp, so two starts inside one second produced
  one id: the second record overwrote the first, both children were handed the
  same `QIKLY_RUN_TIMESTAMP` and appended to a single transaction log, and they
  raced to overwrite one summary. A host retrying a slow tool call was enough
  to trigger it. Ids are now claimed with `O_CREAT|O_EXCL`, which is a real
  reservation rather than a check followed by a write.
- **A run that was starting is no longer reported as a crash.** The run record
  was written only after the child process launched, so between claiming the id
  and that write there was a window where `status` found no pid, no summary,
  and called a perfectly healthy run `stalled`. Narrow on a local disk, wider
  on a synced folder, and permanent if the record write itself failed. The
  record is now written before the launch and gains its pid afterwards, through
  `os.replace` so a reader never sees half a file.
- **A broken process lookup no longer invents a crash either.** `_alive` shells
  out to `tasklist` on Windows and let the exception escape when it was missing
  or restricted, and it matched the pid as a substring of the whole line, so pid
  42 matched the `42,168 K` memory column of an unrelated process. It now asks
  for CSV and compares the pid as a field, and an unanswerable lookup means
  "believed alive" rather than "dead", because a wrong "alive" is corrected by
  the silence rule fifteen minutes later while a wrong "dead" is a false crash
  report that nothing takes back.
- **A reused process id no longer hides a crash.** `status` called a run
  `running` on the strength of the pid being live, and operating systems recycle
  pids. A crashed run whose pid had been taken by something unrelated reported
  `running` forever. A run that has written nothing for fifteen minutes is now
  reported `stalled` with an explanation, measured from its last transaction so
  a long legitimate model call is not mistaken for a crash.

### Changed
- **The update notice quotes a release headline instead of the version twice.**
  It read `qikly 0.3.5 is available + v0.3.5 (you have 0.3.4)`: the suffix is
  the GitHub release name, and `release.yml` titled every release with the bare
  tag, so the one line every existing user sees repeated the number it had
  already said. A version section in this file may now open with a
  `> one line` headline; the workflow lifts it out, titles the release
  `vX.Y.Z: that headline`, and keeps it out of the notes body. The notice
  strips the version prefix, drops a title that is only a version, and cuts
  anything past 64 characters, because it prints on every invocation and the
  title comes from a remote API. Twelve tests pin it, including that the line
  stays ASCII: it goes to a Windows console, which has cost this project a
  debugging session before.

## 0.3.5

### Changed
- **The provenance line is first person and carries a byline.** "This library's
  author worked in that setting" named nobody while speaking about them in the
  third person, which reads oddly for a claim about the writer's own
  experience. It now says "I worked in that setting", with
  `Built by Gal Arav` under it, and the landing page footer carries the same.
  For a tool whose whole argument is a methodological claim about test
  validity, a named person standing behind it is evidence rather than
  decoration.
- **The one-line summary no longer calls qikly a coding agent.** PyPI, the
  package docstring and the README's opening all described the whole tool as
  "an autonomous coding agent", while everywhere else in the project "coding
  agent" names the half that is deliberately denied the acceptance criteria.
  The summary therefore introduced the product as the exact thing the product
  argues you should not trust on its own. It now reads "Generates a test suite
  from acceptance criteria, then converges code against it with an agent that
  never sees those criteria", which keeps the mechanism and uses "agent" the
  way the other 106 occurrences do.
- **The Action can be pinned to a moving major tag.** Everything told a user
  `uses: gal-a/qikly@v0.3.4`, an exact patch, so nobody who copied a template
  ever received a fix: five patch releases shipped in two days and reached no
  existing user. `release.yml` now repoints `v0` after a successful publish,
  the two copyable templates use it, and the README explains both forms and
  why you would choose each. Exact pins remain supported.
- **The Marketplace listing is linked** from a README badge, the CI section and
  the landing page footer. Being listed and not saying so is a credibility
  signal left on the floor.
- **`qikly --explain` no longer prints a release title that repeats the
  version.** Releases here are titled `v0.3.4`, so the update notice rendered
  as "qikly 0.3.4 is available + v0.3.4".
- **The GitHub Release is now built by the workflow, with the artefacts
  attached.** The wheel and the sdist were only ever a workflow artifact, which
  expires, so the release page offered no way to install the exact thing that
  was published. They are now attached to the release, and the notes are read
  out of this file instead of pasted: three releases were written by hand and
  one of them was copied from GitHub's rendered page rather than the raw file,
  which silently dropped 22 bold markers and 64 code spans. The job creates the
  release if it is absent and updates it if it is not, so re-running is safe.
  Ticking the Marketplace box stays manual.
- **The release workflow no longer fires on the major alias it pushes.** It
  triggered on `v*`, which matches `v0` as well as `v0.3.5`, so moving the
  alias re-ran the release and failed four seconds later comparing tag `v0`
  against version `0.3.5`. Nothing could have been published, the guard is the
  step that stopped it, but it put a red X on the repository for something that
  had worked. The filter is now `v*.*.*`.

## 0.3.4

### Fixed
- **Every Gemini run printed a warning about a feature qikly does not use.**
  The SDK enables automatic function calling by default and warns, once per
  process, that using it through `generate_content` is not recommended. qikly
  passes no tools, so AFC had nothing to call and the warning reached every
  user's console and any recorded demo. It is now switched off in the request
  rather than filtered out of the log, since silencing a logger hides a message
  instead of answering it. Guarded on the config type, which is not present
  across the whole supported SDK range.

### Added
- **An offline request-shape test for Gemini.** OpenAI and Anthropic were
  covered against fake SDKs and Gemini was not, because its SDK is a hard
  dependency rather than an optional one. The effect was that the default
  provider, the one every first run uses, had nothing checking what it
  actually sent. Seven tests now pin the model, the output budget, the seed and
  temperature pairing, the refusal when no key is set, and that AFC stays off.

### Changed
- **The Action's Marketplace name and description.** GitHub rejects a name
  matching any existing action, user or organisation, and a dormant
  organisation already holds `qikly`. The Action is now `Qikly Test
  Generation`, which is also what someone browsing the Actions picker searches
  for; the mechanism stays in the description, which was over the 125
  character limit and is now 108. Nothing about `uses: gal-a/qikly@v0.3.4`
  changes.

## 0.3.3

### Fixed
- **A run summary recorded the wrong model whenever the provider was
  overridden.** `settings.yaml` pairs a provider with a model, and the
  provenance block read the two independently: environment first, settings
  second. Running with `LLM_PROVIDER=anthropic` and no `LLM_MODEL` therefore
  recorded `provider: anthropic` with `model: gemini-3.5-flash-lite`, a
  configuration that cannot exist, while the usage report for the same run
  correctly showed `claude-sonnet-5`. This mattered more than a cosmetic slip:
  every stored figure here carries its model, because a convergence rate
  belongs to a model and a configuration as much as to the tool, and the
  research harnesses read these files. It failed silently, attributing one
  model's numbers to another. The model now follows the provider that actually
  ran, `router.default_model_for()` exposes each provider's own default, and a
  test asserts provider and model can never come from different providers.
  Found on 2026-09-08 by running the demo against OpenAI and Anthropic, and
  reproduced twice.
- **The auth message read as broken English for two of the three providers.**
  0.3.1 phrased the expected key shape to sit after "normally 39 characters",
  which is true for Gemini alone, producing "a openai key is normally starting
  sk- or sk-proj-". The clause is now plural, so no article has to agree with a
  provider name nobody can predict, and each shape supplies its own verb. A
  provider with no known shape still gets no clause rather than a guessed one.

## 0.3.2

### Fixed
- **The variable named in an auth failure survives the process boundary.**
  0.3.1 made that message name the variable the key came from, and then named
  the wrong one for every real run. A run is a parent process and one child per
  task; the parent normalises `GEMINI_API_KEY` into `API_KEY` before spawning,
  so the child inherits an `API_KEY` that is already set and reported that as
  the source. Users were sent back to a variable they had never touched, which
  is the exact bug 0.3.1 set out to fix, one level down. The provenance now
  travels to the child alongside the key. A key the user really did set in
  `API_KEY` is still reported as `API_KEY`, and a test pins both directions.

### Changed
- The README's answer to "why not just add a reviewer agent?" is shorter. The
  passage explaining why a reviewer cannot reach this took fifty-one words to
  say what thirty-seven say, and stated the same point twice in the abstract.
  No claim changed.

## 0.3.1

### Fixed
- **An auth failure now names the variable the key came from.** Every provider
  hardcoded "check `API_KEY` for typos", which is the wrong advice for the
  common case: a key set in `GEMINI_API_KEY`, `OPENAI_API_KEY` or
  `ANTHROPIC_API_KEY` and normalised into `API_KEY` internally. A user who had
  never set `API_KEY`, and for whom it was not set, was told to go and check
  it. The message now gives the variable actually read, that key's length, and
  the shape the provider normally uses, so a key that is one character too long
  is visible at a glance. Found on release day against a real key.
- **A key that cannot be a key is refused before a model call is made.**
  Leading or trailing whitespace, wrapping quotes the shell did not strip, a
  byte order mark, a control character, an embedded space or a non-ASCII
  character all now fail immediately, naming the variable at fault, rather than
  being spent on a request the provider will reject. Length and prefix are
  deliberately **not** grounds for refusal: providers add formats without
  notice, and a stale refusal costs a user their whole run while a stale hint
  costs a sentence.

### Changed
- The license badge and the remaining relative links in `README.md` are
  absolute, so they resolve on the PyPI project page. Relative links render
  only on GitHub, and the 0.3.0 page shipped with fourteen of them dead.
- `project.urls` now points at the landing page and adds Issues and Changelog,
  so the PyPI sidebar links somewhere other than the repository.


### Released in 0.3.0, undocumented there

These shipped inside the `v0.3.0` tag but the changelog still filed them under
Unreleased, so the published 0.3.0 release notes omit them. `git ls-tree
v0.3.0` shows the three design documents present and `azure.py` absent. They
are recorded here rather than moved up into 0.3.0, because that release's notes
are already published and PyPI freezes a release's description at upload, so
0.3.0 can never be made to tell the whole story. This is where a reader will
now find it.

- **`docs/DESIGN.md` is now three documents**, because one 7,500-word article
  asked a reader to finish the argument, the evidence and the architecture in
  one sitting to get any of them. Nothing was cut.
  - [`design_1_case_study.md`](docs/design_1_case_study.md), the argument and
    one `CALC_TAX` repair followed end to end.
  - [`design_2_performance.md`](docs/design_2_performance.md), three sweeps,
    the benchmark defect corrected between them, and the withdrawn results.
  - [`design_3_mechanism.md`](docs/design_3_mechanism.md), the five agents, the
    FIX and PATCH separation, and the reference appendix.

- **The Azure OpenAI provider was removed.** Three providers ship: Gemini, OpenAI, Anthropic.
  Azure was a near-duplicate of the OpenAI path with an extra endpoint variable,
  and every SDK carried is somebody else's release schedule to track. It is in
  the git history and can come back when someone asks for it.

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
public version says the tool has been well exercised: 871 offline tests in the
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
