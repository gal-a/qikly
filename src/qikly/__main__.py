"""
`python -m qikly`, the same as the `qikly` command.

This exists for the people the `qikly` command fails for. pip installs console
scripts into a `Scripts` folder that is often not on `PATH` on Windows, and
when `qikly-mcp` cannot be found, neither can `qikly`: so the one command that
would print a working MCP config, `qikly --mcp-config`, was unreachable by
exactly the users who needed it. `python` is on `PATH` whenever pip worked.
"""
from qikly.cli import main

raise SystemExit(main())
