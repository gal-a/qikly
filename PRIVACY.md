# Privacy policy

**Short version: qikly runs on your machine, sends your specification and code
only to the model provider you configured with your own key, and collects
nothing for itself. There is no qikly server, no account and no telemetry.**

Last updated 23 September 2026. It applies to the `qikly` command line tool,
the `qikly-mcp` MCP server, and the GitHub Action, all of which are the same
package.

## What leaves your machine

**One thing, to one place you chose.** A run sends your task file's
`requirements` and `interface`, your `acceptance_criteria`, and the code under
test to the LLM provider named by `LLM_PROVIDER`, using the API key in your own
environment. That is Google (Gemini), OpenAI or Anthropic, whichever you set
up, and the request goes from your machine straight to them. What they do with
it is governed by their terms, not by this policy, so read theirs if the code
is sensitive.

Nothing is sent anywhere else, and nothing is sent to us. There is no "us" to
send it to: this project operates no server and holds no database.

**If your code may not leave your network at all, qikly is not usable as it
stands**, because generating tests requires a model. Better to know that before
installing than after.

## The one other network call, and how to stop it

At startup the tool asks whether a newer release exists, by reading two public
indexes:

- `https://pypi.org/pypi/qikly/json`
- `https://api.github.com/repos/gal-a/qikly/releases/latest`

Both are ordinary public endpoints. The request carries no usage data and
nothing about your project. It does identify the software: the `User-Agent`
header reads `qikly/<version>`, which is how the check knows whether to tell
you a newer release exists, and it is the only thing about you that the request
says. It reads indexes rather than any address this project controls, on
purpose, so that the check cannot become a channel for whatever a maintainer
decides to say later.

Turn it off completely:

```bash
export QIKLY_NO_VERSION_CHECK=1
```

## One more, only if you ask for it

`qikly --criteria-from-jira PROJ-412` reads a ticket from the Jira server you
configure with `JIRA_BASE_URL`, `JIRA_EMAIL` and `JIRA_API_TOKEN`. It is a
read: it fetches that issue's text so the acceptance criteria already written
there can become a task file, and it sends none of your code or specification
anywhere. It runs only when you pass that flag, against a server you named,
with credentials you supplied.

Listed separately because the section above says "the one other network call",
and without this line that sentence would be wrong.

## What stays on your machine

Everything else, under `outputs/` in your own project directory: the generated
tests, the code the agent wrote, every patch it tried, the JUnit XML, the HTML
reports, and the transaction log. None of it is uploaded. Deleting the
directory deletes it.

Your API key is read from the environment and used to authenticate to your
provider. It is never written to any log, report or artefact.

## Secrets, checked rather than asserted

`tests/test_mcp_withholding.py` and the server's own redaction step hold the
MCP tools to returning no acceptance criteria, and an independent scan by the
MCP Trust Index reports that secret environment variables are read but never
reach the network, a shell or a log. That is a property you can verify in the
source rather than a promise in a document.

## The MCP server

`qikly-mcp` speaks to your editor over stdin and stdout on your own machine. It
opens no listening socket and accepts no remote connection. Its four tools
(`qikly_run`, `qikly_status`, `qikly_validate`, `qikly_scaffold`) operate on
files in the project directory you point them at, and the same model-provider
rules above apply to `qikly_run`, which is the only one that calls a model.

## Children

This is a developer tool and is not directed at children.

## Changes

Material changes will be noted in `CHANGELOG.md` alongside the release that
makes them, so a change to this policy arrives through the same channel as a
change to the code.

## Contact

Open an issue at <https://github.com/gal-a/qikly/issues>.
