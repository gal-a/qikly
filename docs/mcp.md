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
