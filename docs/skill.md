# qikly as an agent Skill

**What this gets you:** your coding agent stops needing to be told about
qikly. Ask it for tests you can trust and it reaches for the tool on its own,
and it knows the part that is hard to guess, which line of your specification
is a decision the coder needs and which is a consequence to withhold.

A Skill is a folder of Markdown your agent reads when what you are asking
matches what the Skill says it is for. No server, no configuration, no process
to keep running.

## Install it

From the directory of the project you want it in:

```bash
qikly --install-skill
```

That writes `.claude/skills/qikly/`, which is where agents look. Then open your
agent in that directory and ask for something ordinary, without mentioning
qikly:

> Write tests for `src/pricing.py` that would actually catch a bug.

It should reach for qikly by itself. If it does not, see
[checking that it works](#checking-that-it-works) below.

**A few options, none of them needed the first time.** `--dry-run` shows what
it would write. `--force` replaces a Skill you have already edited, keeping a
timestamped copy of the old one. And `--install-skill agents`, `cursor` or
`gemini` write where those tools document their own skill folders, rather than
Claude's.

## What is in it

- **The one question**: given only the requirements, could two competent
  developers legitimately disagree about this line? Yes means it is a decision
  and belongs in `requirements`; no means it is a consequence and belongs in
  `acceptance_criteria`.
- **Both mistakes and their signatures**, so an agent can recognise a stalled
  loop as a spec problem rather than a code problem.
- **How to write a criterion that can be tested**: name values not adjectives,
  name both sides of a boundary, and make sure the data contains what you name.
- **The five steps** on your own module, and which commands are free.
- **What to do when a run does not converge**, and the one thing never to do,
  which is loosen a criterion to get green.
- **The honest limit**, so an agent does not oversell it on your behalf.
- **Two bundled references**: the task file reference and the troubleshooting
  guide, complete, so the Skill works with no network.

## Skill or MCP server, and why qikly has both

**Skip this if you are not using the MCP server.** The Skill works on its own.
This is here because the two look interchangeable and are not: they answer
different halves of the same problem, and neither replaces the other.

| | MCP server | Skill |
|---|---|---|
| What it ships | a running process exposing typed tools | a folder of Markdown |
| What it gives the model | the ability to call `qikly_scaffold`, `qikly_validate`, `qikly_run`, `qikly_explain` | the judgement around those calls |
| Setup | `qikly --install-mcp`, then host configuration | `qikly --install-skill` |
| Can enforce a rule | **yes**, in server code | no, it is instructions |
| Works when the agent has no shell | yes | no |

**The MCP server is the one that can enforce things.** `qikly_run` is built so
it cannot return the acceptance criteria, and a test in qikly's own suite fails
the build if any code path lets a criterion through. That guarantee lives in
code, and it is why the server exists.

**The Skill is the one that can teach.** Which line of your spec is a decision
and which is a consequence; that a repeating identical patch means a decision
is in the wrong half; that a criterion naming a value your data never holds
produces a test that passes whatever the code does. None of that is a function
call, and an agent that does not know it will use qikly and get less out of it.

**Read this plainly: a Skill cannot keep anything hidden.** It is text in a
context window. The withholding is enforced by the tool, in code, whether or
not this Skill is installed. The Skill's own text says so, and there is a test
asserting it still does.

## Checking that it works

A Skill either loads or it does not, and it never tells you which, so it is
worth five minutes once. If you only do one of these, do number three.

**1. It is where the agent looks.**

```bash
ls .claude/skills/qikly/SKILL.md
```

**2. It loads on a request that should trigger it.** Start a fresh session and
ask for something in its territory without naming qikly:

> Write tests for `src/pricing.py` that would actually catch a bug in it.

The agent should mention qikly, or the decisions-and-consequences split,
unprompted. If it does not, the description in the frontmatter is the thing to
change: an agent decides whether to load a Skill from that sentence alone.

**3. It does not load when it should not.** Ask something unrelated, such as
"rename this variable everywhere", and it should stay quiet. A Skill that loads
for everything costs context on every request.

**4. It gives the right answer to the question that matters.** Ask:

> My spec says "warn when following distance breaks the two-second rule", and
> the acceptance criteria say a headway of exactly 2.00 s does not warn. Is
> that the right split?

The answer should be no, and the reason should be that "breaks" can be read as
"below" or "at or below", so the boundary is a decision and belongs in the
requirements. That is the single most valuable thing in the Skill, and if it
comes back wrong the rest does not matter much.

**5. It does not claim more than the tool does.** Ask what guarantees the
coding agent never sees the criteria. The answer should point at qikly's code
and its build-failing test, not at the Skill.

## Keeping it current

The Skill itself lives at
[`src/qikly/skills/qikly/`](https://github.com/gal-a/qikly/tree/main/src/qikly/skills/qikly)
and ships inside the installed package, so `--install-skill` works from
`pip install qikly` as well as from a clone.

**A stale Skill is worse than no Skill**, because an agent quotes it with
confidence and the reader has no way to tell. So it is updated whenever qikly
changes in a way it describes: a new or renamed flag, a change to which
commands are free, a re-measured convergence figure, a new failure mode worth
carrying.

Half of it cannot go stale on its own. The two bundled references are asserted
byte-identical to `docs/TASK_FILE_REFERENCE.md` and `docs/TROUBLESHOOTING.md`
by a test, so a drifted copy fails the build. The prose in `SKILL.md` has no
such test, which is why it is on the release checklist instead.
