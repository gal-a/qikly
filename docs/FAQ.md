# FAQ

Questions people have actually asked, with the answer checked against the code
rather than remembered. Where an answer has a boundary, the boundary is stated:
a qualified yes is more use than an unqualified one.

## Does it run locally or in the cloud?

Locally. It is a `pip install` and a command line tool on your machine, or in
CI through the bundled GitHub Action. There is no qikly service in the middle
and nothing to sign up for.

The only thing that leaves your machine is the prompt sent to whichever model
provider you configure, using your own API key. Gemini, OpenAI and Anthropic
are supported; see [PROVIDER_KEY_SETUP.md](PROVIDER_KEY_SETUP.md).

## Does my code or my data go to you?

No. Nothing is sent to the project, and the tool collects no telemetry. What
reaches your model provider is what the prompts contain: the task file as each
agent receives it, and the test failures the loop is working through. Your
provider's own terms then govern that traffic.

## Is there anything I can run before committing an API key?

Yes, three things, all offline and free:

```bash
qikly --explain MERGE_SALES          # what each agent is shown, and the difference
qikly --explain MERGE_SALES --html   # the same as one page you can share
qikly --validate                     # check your task files
```

`--explain` is the one worth running first. It makes no model call and takes
about a second.

## Does the coding agent really never see the acceptance criteria?

That is what `--explain` exists to show, on your own task rather than on a
claim in a README: it prints the task file as test generation receives it, then
as the coding agent receives it, then the difference. It builds those strings
through the same function a real run uses, so it demonstrates the mechanism
instead of describing it.

The property is also held by the test suite: no call site in the codebase can
pass a criterion to the coding agent, so the removal cannot be undone by a
later change without a test failing.

## What does one passing run prove?

That this task converged this once. A run is a loop with a variable trip count,
so one run is an artifact and never a rate. If you want a number you can quote,
repeat the run and report the spread. The project's own performance figures are
in [design_2_performance.md](design_2_performance.md), with the sample sizes
they rest on.

## What will a run cost?

Every run prints a projection before it starts: the expected number of model
calls, tokens in and out, and a price from a static table rather than from your
bill. Treat it as a projection, because the trip count varies.

## Can I use it commercially?

Yes. qikly is Apache 2.0, which permits commercial use, modification and
redistribution. Note that the licence grants no trademark rights, so building a
service on it is fine and naming that service after the project is a separate
conversation.

## Can I drive it from an editor or an agent?

Yes, it ships an MCP server, so Claude Code, VS Code and other MCP hosts can
call it. See [mcp.md](mcp.md). The server deliberately never returns acceptance
criteria, for the same reason the coding agent never receives them.


## Does qikly know about the classes I already have, such as hardware drivers or protocol parsers?

Not by discovery. qikly does not scan your repository and work out what is
available, so it will not find your driver and parser classes on its own. What
the test-writing agent targets is what the task file's `interface` block
declares, plus the requirements and the acceptance criteria. You describe the
surface; it does not go looking for one.

Two things make that less manual than it sounds:

- `qikly --scaffold path/to/module.py` reads the real signatures out of a file
  you point it at and writes the `interface` block for you.
- `seed.tests` keeps a suite you already trust, per stage, so the loop repairs
  code against your tests rather than against generated ones. `seed.implementation`
  points the run at code you already have. Both are in
  [QUICK_START_ON_YOUR_OWN_DATA.md](QUICK_START_ON_YOUR_OWN_DATA.md).

**Can the tests import those classes once they exist?** Yes, with one condition.
Each stage runs as `python -m pytest` from your project root, which puts the
project root on `sys.path`. So a package sitting at the project root, or one
installed into the same virtualenv, imports normally from both the generated
tests and the generated implementation. A package in a subdirectory that is not
on the path does not: the run stops with a collection error, `no test ran: the
module could not be imported`, and no amount of iterating fixes it because the
problem is the path rather than the code. Put the directory on `PYTHONPATH`, or
`pip install -e .` your own package, and it resolves.

**One thing worth knowing before you start.** The loop reruns pytest on every
iteration, so it suits the deterministic layer best. Protocol parsing is a good
fit: bytes in, structured records out, driven from recorded captures. Code
talking to live hardware is better left behind the test doubles you already
have, because a suite that needs a rig attached is a suite the loop cannot rerun
freely.