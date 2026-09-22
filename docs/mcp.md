# qikly over MCP

`qikly` runs as an [MCP](https://modelcontextprotocol.io) server, so an agent in
any MCP host can start a run and read its result without you leaving the
conversation to type a command. It is tested in VS Code and Claude Code so far;
the setup for other hosts below follows the MCP standard but has not been
verified end to end.

With [uv](https://docs.astral.sh/uv/) installed, nothing else needs installing.
In Claude Code:

```bash
claude mcp add qikly -- uvx --from "qikly[mcp]" qikly-mcp
```

Other hosts take the same command in their own config file, and it speaks
stdio:

```json
{
  "mcpServers": {
    "qikly": { "command": "uvx", "args": ["--from", "qikly[mcp]", "qikly-mcp"] }
  }
}
```

Without uv, install with pip and register the `qikly-mcp` command instead:

```bash
pip install "qikly[mcp]"
claude mcp add qikly -- qikly-mcp
```

`uvx` keeps the version it first installed. To pick up a new release, run
`uv cache clean qikly` and restart the host.

Run it from the project directory, the one holding `inputs_private/`. That is
how it finds your tasks, and it is the same rule the CLI follows.

## One-click install, and which editors have it

The README badge installs into **VS Code**. It writes the `uvx` command above,
so it needs uv and installs nothing itself. The same redirect serves Insiders
from its own host:

```markdown
[![VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_qikly_MCP-24bfa5?logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=qikly&config=%7B%22name%22%3A%22qikly%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22qikly%5Bmcp%5D%22%2C%22qikly-mcp%22%5D%7D)
```

A common mistake in other projects' READMEs is pointing both buttons at
`insiders.vscode.dev`. Stable is `vscode.dev`, Insiders is
`insiders.vscode.dev`, and the payload is identical.

**Other editors have their own deeplink schemes**, and qikly does not yet ship
buttons for them because none has been tested against a real install here:

| Editor | Scheme |
| --- | --- |
| Visual Studio | `vs-open.link/mcp-install` |
| Cursor | `cursor://anysphere.cursor-deeplink/mcp/install` |
| Goose | `goose://install-mcp` |
| LM Studio | `lmstudio://add_mcp` |

They differ in how the config is encoded, and at least one uses base64 where
VS Code uses URL-encoded JSON. A button that writes a malformed config is worse
than no button, because the reader blames the tool rather than the link. Until
each is tried, use the plain configuration above: **every one of these editors
accepts a hand-written config**, and the button only ever saves you a paste.

## Let it register itself

```bash
qikly --install-mcp --dry-run    # what it would write, and where
qikly --install-mcp              # write it
```

It writes **project-local files only**: `.mcp.json` for Claude Code and
`.vscode/mcp.json` for VS Code. Never `~/.claude.json`, never the VS Code user
profile. Those hold every other server you have, and the project file is also
the right place on its own terms, because the setting that reliably goes wrong
is which folder the server treats as the project.

It merges rather than overwrites, so your other servers and every other key in
the file survive, and it copies the file to a timestamped backup first. Running
it twice changes nothing and says so.

It refuses in three cases, and prints the block for you to paste instead:

| It stops when | Because |
|---|---|
| the file holds comments | VS Code's `mcp.json` is JSONC, and writing it back as JSON would delete every comment you wrote |
| a `qikly` entry exists and differs | you changed it on purpose. `--force` says otherwise |
| the file is not valid JSON | guessing what you meant is how a config gets lost |

**If `claude` is not a command**, it is bundled inside the VS Code extension
rather than installed on `PATH`, at
`%USERPROFILE%\.vscode\extensionsnthropic.claude-code-<version>-<platform>
esources
ative-binary\claude.exe`.
The version is in the path, so it moves on every extension update. You do not
need the CLI for any of this; it is only how you check the registration from a
terminal.

**Claude Code needs one approval after this.** A project-scoped `.mcp.json`
is not trusted on sight, and it should not be: cloning a repository must not
silently run whatever it ships. `claude mcp list` will show qikly as pending
until you run `claude` once in that directory and approve it.

Add `--install-mcp claude` or `--install-mcp vscode` to target one host.

Cursor and Codex CLI are not written yet. Cursor takes the `mcpServers` shape
below; Codex needs TOML, which the standard library cannot write on any Python
this supports.

## Two things that will bite you on Windows

Both were hit on a real machine before anyone else saw them, and neither
announces itself clearly, so they are worth reading before you debug.

**The command has to be on `PATH`.** The uv route and the one-click button run
`uvx`, which the uv installer puts on `PATH`, though an editor opened before
you installed uv will not see it until you restart the editor. The pip route
names a bare `qikly-mcp`, and on Windows `pip` often
installs console scripts into a `Scripts` directory that is not on `PATH`, and
the host then reports only that the command was not found. Check it:

```powershell
Get-Command qikly-mcp
```

If that finds nothing, let qikly print a config that does not depend on
`PATH`. In your project folder:

```powershell
python -m qikly --mcp-config
```

It prints a VS Code config naming the full path of the Python that has qikly,
run as `python -m qikly.mcp_server`, and the folder you ran it from as
`QIKLY_PROJECT_ROOT`, which also settles the folder problem below.
`--mcp-config claude` prints the `mcpServers` shape for Claude Code, Cursor
and most other hosts. It only prints; it never edits a config file, because
those hold your other servers too. Use `python -m qikly` rather than `qikly`
here: when `qikly-mcp` is not on `PATH`, neither is `qikly`.

**The host starts the server in the folder your editor has open**, which is
often the parent of your qikly project rather than the project itself. The
server starts, and every task looks absent. Name the project explicitly:

```json
{
  "servers": {
    "qikly": {
      "type": "stdio",
      "command": "qikly-mcp",
      "env": { "QIKLY_PROJECT_ROOT": "C:\\path\\to\\your\\project" }
    }
  }
}
```

The tools detect this case rather than reporting an empty project: if the
resolved root has no `inputs_private/`, they say so and name the directory they
resolved, because that one fact is the difference between a misconfiguration
and an apparently broken tool.

## The four tools

| Tool | What it achieves | Input | Returns | Safe to call unattended? | CLI equivalent |
| --- | --- | --- | --- | --- | --- |
| `qikly_run` | Starts a full run for one task: generates the suite from the acceptance criteria, writes an implementation from the requirements alone, and repairs it against the suite until every stage passes or the retry budget is spent. Returns **immediately**, because a run takes minutes to hours. | `task_id`, optional `provider` and `model` | A `run_id` to poll with | **No.** It writes code and tests, calls a model provider over the network, and spends real money. A second call is a second run, not a repeat: the agents are not deterministic even at a fixed seed. | `qikly --run <task>` |
| `qikly_status` | Reports where a run got to, reading what the run itself wrote rather than watching the process. That is what lets it tell a crash from a failing suite: `stalled` means the process is gone without writing a summary. While a run is in flight it also gives the stage and iteration. | `run_id` | One of `running`, `passed`, `failed`, `stalled`, `unknown`, plus stage and iteration | **Yes.** Reads local run records only. Free, no network. | `qikly --status <run_id>` |
| `qikly_validate` | Checks a task file offline before you spend anything on it: valid YAML, the required sections present, `acceptance_criteria` a list rather than one long string, and fixture paths that actually resolve. It does **not** look for contradictions between requirements and criteria: that is `qikly --check-criteria`, a paid model call this server deliberately does not expose. | `task_id` | Counts and a verdict | **Yes.** No model call, so no network and no cost. Returns no criterion text. | `qikly --validate --tasks <task>` |
| `qikly_scaffold` | Turns a Python file you already have into a task that tests it: the module path, the real signatures of its public functions, a guessed entrypoint, and a seed pointing back at the file. `requirements` and `acceptance_criteria` are left as `TODO` on purpose, because criteria read out of an implementation can only describe what it already does. | `file_path` | The task YAML as text, for you to save under `inputs_private/config/tasks/` | **Yes.** Returns the YAML rather than writing it, so saving stays your decision. | `qikly --scaffold <file>` |

Every tool carries the four MCP behaviour annotations, so a host can act on the
column above rather than guess: `readOnlyHint`, `destructiveHint`,
`idempotentHint` and `openWorldHint`. Three of the four are read-only, free and
local. Only `qikly_run` is none of those things.

## Why `qikly_run` does not wait

A run takes minutes to hours. No MCP host will hold a tool call open that long,
so `qikly_run` starts the run in a detached process and hands back an id:

```
qikly_run(task_id="CALC_TAX")
  -> {"run_id": "CALC_TAX_20260910_113412", "state": "running"}
```

The agent then polls:

```
qikly_status(run_id="CALC_TAX_20260910_113412")
  -> {"state": "running", "progress": {"stage": "unit", "iteration": 2}}
```

Because the run is detached, you can close the terminal, close the editor, and
ask for the status tomorrow. The run outlives the conversation that started it.

`stalled` is worth knowing about: it means the run died without writing a
summary, which is a crash rather than a failing suite. The two need different
reactions, so they get different words.

## What these tools will not tell you

No qikly tool returns your acceptance criteria. Not on success, and especially
not on failure, which is exactly when a helpful tool wants to explain why and
"why" is the criterion.

That is the point of the whole library, so it is enforced rather than intended:
`tests/test_mcp_withholding.py` asserts on the serialised JSON that crosses the
wire, for every tool, including the error paths.

Your agent will see that four tests failed, and the pytest output for each. It
will not see the rule it broke. That is the same information a human developer
gets from a failing CI run, and it is what stops the agent writing code aimed at
the test instead of at the requirement.

## One thing you have to do yourself

These tools control what a *response* contains. They cannot control what your
agent reads off your disk, and **the generated tests under `outputs/tests/` are
written from your criteria**. An agent that opens those files has the answer
key, without any tool call being involved.

This matters more than it first sounds, because the natural way to use this
server is to let the same agent both write your code and call `qikly_run`.

So tell your agent to leave the generated tests alone. In Claude Code, add to
`.claude/settings.json`:

```json
{
  "permissions": {
    "deny": ["Read(./outputs/tests/**)"]
  }
}
```

Or add `outputs/tests/` to whatever your host uses to keep files out of an
agent's reach. Reading the *summary* is fine and useful. Reading the tests is
the one habit that quietly undoes the reason you installed this.
