# FAQ

Questions people have actually asked, with the answer checked against the code
rather than remembered. Where an answer has a boundary, the boundary is stated:
a qualified yes is more use than an unqualified one.

## 1. Does it run locally or in the cloud?

Locally. It is a `pip install` and a command line tool on your machine, or in
CI through the bundled GitHub Action. There is no qikly service in the middle
and nothing to sign up for.

The only thing that leaves your machine is the prompt sent to whichever model
provider you configure, using your own API key. Gemini, OpenAI and Anthropic
are supported; see [PROVIDER_KEY_SETUP.md](PROVIDER_KEY_SETUP.md).

## 2. Does my code or my data go to you?

No. Nothing is sent to the project, and the tool collects no telemetry. What
reaches your model provider is what the prompts contain: the task file as each
agent receives it, and the test failures the loop is working through. Your
provider's own terms then govern that traffic.

## 3. Is there anything I can run before committing an API key?

Yes, three things, all offline and free:

```bash
qikly --explain MERGE_SALES          # what each agent is shown, and the difference
qikly --explain MERGE_SALES --html   # the same as one page you can share
qikly --validate                     # check your task files
qikly --score-code src/yours.py --score-tests tests/test_yours.py
```

`--explain` is the one worth running first: no model call, about a second.

`--score-code` is the one that runs on **your** code rather than on a bundled
task. It plants one fault at a time and reports which ones your existing tests
did not notice. No task file, no run, no key, and nothing of yours is modified.
Read the score as a floor: it says how much of the code that is there your
tests would notice changing, and nothing about a rule nobody implemented.

## 4. Does the coding agent really never see the acceptance criteria?

That is what `--explain` exists to show, on your own task rather than on a
claim in a README: it prints the task file as test generation receives it, then
as the coding agent receives it, then the difference. It builds those strings
through the same function a real run uses, so it demonstrates the mechanism
instead of describing it.

The property is also held by the test suite: no call site in the codebase can
pass a criterion to the coding agent, so the removal cannot be undone by a
later change without a test failing.

## 5. What does one passing run prove?

That this task converged this once. A run is a loop with a variable trip count,
so one run is an artifact and never a rate. If you want a number you can quote,
repeat the run and report the spread. The project's own performance figures are
in [design_2_performance.md](design_2_performance.md), with the sample sizes
they rest on.

## 6. What will a run cost?

Every run prints a projection before it starts: the expected number of model
calls, tokens in and out, and a price from a static table rather than from your
bill. Treat it as a projection, because the trip count varies.

## 7. Can I use it commercially?

Yes. qikly is Apache 2.0, which permits commercial use, modification and
redistribution. Note that the licence grants no trademark rights, so building a
service on it is fine and naming that service after the project is a separate
conversation.

## 8. Can I drive it from an editor or an agent?

Yes, it ships an MCP server, so Claude Code, VS Code and other MCP hosts can
call it. See [mcp.md](mcp.md). The server deliberately never returns acceptance
criteria, for the same reason the coding agent never receives them.


## 9. Does qikly know about the classes I already have, such as hardware drivers or protocol parsers?

Not by discovery: it targets what your task file's `interface` block declares,
and `qikly --scaffold your_module.py` writes that block from the real
signatures. Your other classes import normally at run time as long as they are
importable from your project root.

What it may **change** is a separate question from what it can import, and the
answer is the seed: `seed.implementation` can name a single module or a whole
package, and everything inside it is visible to the coding agent and
repairable. A defect in a helper you left outside the seed is caught by the
tests, cannot be repaired, and the run now says so rather than working around
it.

The full picture, including what a run prints in each case, is in
[EXISTING_CODE_AND_HELPERS.md](EXISTING_CODE_AND_HELPERS.md).
