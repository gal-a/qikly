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

It should reach for qikly by itself. That has been watched happen in **Claude
Code, Gemini CLI, Codex and Cursor**, once each, in a throwaway project with a
rival testing skill installed beside this one and a request that never
mentioned qikly. Four sessions is four anecdotes rather than a rate, and your
project has more skills in it than that test did.

If it does not, see [if your agent does not pick it up](#if-your-agent-does-not-pick-it-up).

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

## If your agent does not pick it up

Three causes, in the order to check them.

**1. Your agent is not in that directory.** The Skill is per project. It is
files on disk, so an agent started in another folder, or running in a browser
with its own sandbox rather than on your machine, cannot see them. Start the
agent in the directory you installed into. This is the commonest cause by some
distance.

**2. Just name it.** This always works, because it does not depend on the
agent being told what the Skill is for:

> Use the qikly skill to write tests for `src/pricing.py`.

If naming it works and the neutral request did not, the Skill is fine and the
problem is discovery.

**3. The host did not pass the description along.** Whether an agent reaches
for a Skill unprompted depends on how much it explores before it starts typing,
and on what the host told it. Claude Code reserves a fraction of the context
window for the whole skill listing, 1% by default; when the listing does not
fit, Anthropic's own bundled skills keep their descriptions and everything else
is ranked by how often you have used it. So a skill you have never invoked can
arrive as a bare name with nothing to match against. Raising
`skillListingBudgetFraction` in your Claude Code settings gives the listing more
room, and that single change turned four failed routing attempts into a clean
one during testing.

## Checking that it works

A Skill either loads or it does not, and it never tells you which, so it is
worth five minutes once. **If you only do one of these, do number four:** the
others check that the Skill arrived, and that one checks that it is right.

**1. The files are where your agent looks for them.** In the project you ran
`qikly --install-skill` in:

```bash
ls .claude/skills/qikly/SKILL.md        # macOS, Linux
dir .claude\skills\qikly\SKILL.md       # Windows PowerShell
```

**And start your agent in that same directory.** The Skill is per project, not
per machine: an agent started somewhere else, or running in a browser with its
own sandbox rather than on your computer, cannot see these files and will never
load them. That is the commonest reason a correctly installed Skill appears to
do nothing.

**2. It loads on a request that should trigger it.** Start a fresh session and
ask for something in its territory, **naming a real module of your own** and
not mentioning qikly:

> Write tests for `src/pricing.py` that would actually catch a bug in it.

Any module will do; `src/pricing.py` is a stand-in for a file you actually
have, and the request has to name one that exists or the agent will spend its
answer asking you which file you meant.

The agent should mention qikly, or the decisions-and-consequences split,
unprompted. If it does not, see [when an agent does not pick it
up](#if-your-agent-does-not-pick-it-up) below before changing anything.

**3. It does not load when it should not.** Ask something unrelated, such as
"rename this variable everywhere", and it should stay quiet. A Skill that loads
for everything costs context on every request.

**4. It gives the right answer to the question that matters.** This is the one
to do if you do only one. Ask:

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

**An installed Skill does not update itself, and until 0.5.4 nothing told you.**
`pip install --upgrade qikly` replaces the package; it cannot touch a folder
copied into your project, so after an upgrade you can be following instructions
that name a different set of commands. From 0.5.4 any qikly command says so
when it notices:

```
note: the qikly Skill in .claude/skills/qikly is older than this qikly, so it
describes a different set of commands. `qikly --install-skill --force`
replaces it and keeps a copy of the old one.
```

`--force` keeps a timestamped copy of what it replaces, so a Skill you have
edited is recoverable. That is the whole update mechanism: qikly tells you, and
you run one command. There is no background process and nothing phones home;
the check is two version strings read from two files on your disk.

The Skill's version is its own and moves when its instructions move, not when
qikly releases, so a release that does not touch it produces no notice.

---

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
