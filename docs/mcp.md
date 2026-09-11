# qikly over MCP

`qikly` runs as an [MCP](https://modelcontextprotocol.io) server, so an agent in
Claude Code, Codex CLI, Cursor or any other MCP host can start a run and read
its result without you leaving the conversation to type a command.

```bash
pip install "qikly[mcp]"
```

Then register the `qikly-mcp` command with your host. In Claude Code:

```bash
claude mcp add qikly -- qikly-mcp
```

Other hosts take the same two facts in their own config file: the command is
`qikly-mcp`, and it speaks stdio.

```json
{
  "mcpServers": {
    "qikly": { "command": "qikly-mcp" }
  }
}
```

Run it from the project directory, the one holding `inputs_private/`. That is
how it finds your tasks, and it is the same rule the CLI follows.

## One-click install, and which editors have it

The README badge installs into **VS Code**. The same redirect serves Insiders
from its own host:

```markdown
[![VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_qikly_MCP-24bfa5?logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=qikly&config=%7B%22name%22%3A%22qikly%22%2C%22command%22%3A%22qikly-mcp%22%7D)
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

## Two things that will bite you on Windows

Both were hit on a real machine before anyone else saw them, and neither
announces itself clearly, so they are worth reading before you debug.

**`qikly-mcp` has to be on `PATH`.** Every config above, and the one-click
install button in the README, names the bare command. On Windows, `pip` often
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

| Tool | What it does |
| --- | --- |
| `qikly_run` | Starts a run for one task. Returns a run id **immediately**. |
| `qikly_status` | Reports on a run: `running`, `passed`, `failed`, `stalled`, `unknown`. |
| `qikly_check_criteria` | Validates a task offline. Free, no model call. |
| `qikly_scaffold` | Turns a Python file into a task skeleton. |

## Why `qikly_run` does not wait

A run takes minutes to hours. No MCP host will hold a tool call open that long,
so `qikly_run` starts the run in a detached process and hands back an id:

```
qikly_run(task_id="CALC_TAX")
  -> {"run_id": "CALC_TAX_20260910_113412", "state": "started"}
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
