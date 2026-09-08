"""
A human gate between a proposed change and an applied one.

By default qikly applies every patch it generates without asking. That is
defensible, because a run writes only inside its own output directory and never
touches your working tree, and it is the only way an unattended loop can make
progress. It is also the first thing anyone with a security or compliance
question asks about, and "it cannot reach your source tree" is a good answer to
a different question than the one they asked.

So there are three modes, and the default is unchanged.

**apply** (default). Every patch is applied as soon as it is generated.

**review.** Each patch is printed and the run waits for a decision. Use it when
you want to watch a specific task think, or when you are deciding whether to
trust it on something that matters.

**dry-run.** Every patch is generated, written to disk, and never applied. The
run therefore cannot converge, and that is the point: it produces the complete
set of changes the agent would have made, as diffs you can read at your own
pace, for the price of the model calls. Compare it to running a build with the
compiler in check-only mode.

## Why a rejected patch is recorded rather than discarded

A rejection is information about the agent, and it is the only kind this
project cannot otherwise collect: it says a human looked at a proposed change
and judged it wrong, which no test can tell you. The diff stays on disk and the
transaction log records the decision, so a run that was steered can be told
apart from one that was not. A patch that vanished when it was declined would
make those two runs look identical afterwards.
"""
import os
import sys

APPLY = "apply"
REVIEW = "review"
DRY_RUN = "dry-run"
MODES = (APPLY, REVIEW, DRY_RUN)

ENV_MODE = "QIKLY_APPROVAL"


def mode():
    """
    The approval mode for this process.

    Read from the environment rather than passed down through the orchestrator
    because a run happens in a child process per task, and the alternative is
    threading a parameter through six call sites that have no other reason to
    know about it.
    """
    value = (os.environ.get(ENV_MODE) or APPLY).strip().lower()
    return value if value in MODES else APPLY


def _summarise(patch):
    """Counts a reviewer wants before reading a word of the diff."""
    added = sum(1 for line in patch.split("\n")
                if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in patch.split("\n")
                  if line.startswith("-") and not line.startswith("---"))
    files = sorted({line.split(" ", 1)[1].strip()
                    for line in patch.split("\n")
                    if line.startswith("+++ ") and len(line.split(" ", 1)) > 1})
    return added, removed, files


def decide(patch, fix_id, stage, iteration, stream=None):
    """
    Whether to apply this patch. Returns (approved, reason).

    In dry-run nothing is ever applied and no question is asked, so an
    unattended dry run completes on its own. In review the question goes to the
    terminal, and anything other than a clear yes is a rejection: a reviewer who
    walked away, or a pipe with no keyboard behind it, must not be read as
    consent.
    """
    current = mode()
    if current == APPLY:
        return True, None
    if current == DRY_RUN:
        return False, "dry-run: patches are generated and never applied"

    out = stream or sys.stderr
    added, removed, files = _summarise(patch)
    print("", file=out)
    print("=" * 72, file=out)
    print(f"PATCH {fix_id}  stage={stage}  iteration={iteration}", file=out)
    print(f"  +{added} / -{removed} across {len(files)} file(s)", file=out)
    for name in files:
        print(f"    {name}", file=out)
    print("=" * 72, file=out)
    print(patch, file=out)
    print("=" * 72, file=out)

    try:
        answer = input("Apply this patch? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # No terminal, or the reviewer left. Silence is not approval.
        print("", file=out)
        return False, "no answer given, so the patch was not applied"

    if answer in ("y", "yes"):
        return True, None
    return False, "declined by the reviewer"
