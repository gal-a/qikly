"""
A task file from the document you already wrote, plus the code you already have.

The friction two of the first three users named was not where you invoke qikly.
It was that before you can invoke it at all you must hand-write a YAML file
restating things that already exist: the criteria live in a Confluence page or
a Jira ticket, and the signatures live in the module.

Both halves were already built and nobody had joined them up. `criteria_import`
reads a page or a ticket; `scaffold` reads the code. This is the join.

**The half it deliberately does not fill.** `requirements` is the section the
coding agent reads. A feature page usually restates its own acceptance criteria
in the prose above them, so lifting requirements out of the document would
carry the criteria to the one agent that must never see them, through a route
nobody would think to check. So requirements stay TODO, and `overlap()` exists
to catch it mechanically if someone pastes them in later.

That refusal is the same shape as `scaffold` refusing to derive criteria from
an implementation. Both are places where the convenient thing is the thing that
quietly destroys the property the tool exists to provide.
"""
import re

# Short, ordinary words carry no signal about whether two sentences say the
# same thing, and leaving them in makes everything look like everything else.
_NOISE = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "be", "must",
    "should", "shall", "it", "its", "that", "this", "with", "for", "on", "at",
    "as", "by", "from", "when", "if", "then", "not", "no", "any", "all", "each",
    "every", "than", "so", "but", "was", "were", "has", "have", "will", "may",
}


def _words(text):
    return [w for w in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if w not in _NOISE and len(w) > 2]


# A task's own field and domain names recur in nearly every line it contains.
# Two criteria about `start_date` and `end_date` share those words because they
# are about the same data, not because either restates the other, so counting
# them as evidence of restatement measures the subject matter instead of the
# overlap. Below this share of a task's criteria a word still discriminates.
_VOCABULARY_SHARE = 0.4

# With one or two criteria there is no such thing as a word common to the set:
# every word of a lone criterion appears in 100% of them, and discounting on
# that basis would empty it and score every pasted criterion at zero.
_VOCABULARY_MIN_CRITERIA = 3


def common_vocabulary(criteria, share=_VOCABULARY_SHARE):
    """
    The words this task says everywhere, which therefore say nothing.

    Returns an empty set for a handful of criteria, where the measure is not
    defined rather than merely weak.
    """
    criteria = [c for c in (criteria or []) if isinstance(c, str)]
    if len(criteria) < _VOCABULARY_MIN_CRITERIA:
        return set()
    counts = {}
    for crit in criteria:
        for word in set(_words(crit)):
            counts[word] = counts.get(word, 0) + 1
    return {w for w, n in counts.items() if n / len(criteria) >= share}


def overlap(requirement, criterion, threshold=0.6, common=None):
    """
    Does this requirement restate this criterion?

    Word overlap against the criterion, not against the requirement: a long
    requirement that happens to contain a short criterion is exactly the case
    worth catching, and dividing by the longer text would hide it.

    `common` is the task's own recurring vocabulary, from `common_vocabulary`.
    Discounting it is what separates a restatement from two sentences about the
    same fields: "end_date must not be earlier than start_date" keeps only
    "earlier" once the field names are discounted, and no requirement naming
    both fields scores against it any more.

    Deliberately blunt. It is a prompt to look, not a verdict, and a false
    positive costs a glance while a false negative costs the central claim.
    """
    crit = set(_words(criterion))
    if not crit:
        return 0.0
    # A criterion made entirely of the task's own vocabulary leaves nothing to
    # discount against, so fall back to the raw measure rather than scoring 0.
    discounted = crit - (common or set())
    if discounted:
        crit = discounted
    return len(crit & set(_words(requirement))) / len(crit)


def restated(requirements, criteria, threshold=0.6):
    """
    Every (requirement, criterion, score) pair that looks like a restatement.

    This is the mechanism that replaces trusting the author. It runs over a
    task file whoever wrote it and however it got there.
    """
    common = common_vocabulary(criteria)
    found = []
    for req in requirements or []:
        for crit in criteria or []:
            score = overlap(req, crit, threshold, common)
            if score >= threshold:
                found.append((req, crit, round(score, 2)))
    return found


_CRITERIA_BLOCK = re.compile(
    r"^acceptance_criteria:\n(?:[ \t]*[#-][^\n]*\n)*", re.M)


def merge(scaffold_yaml, criteria):
    """
    Put the document's criteria into the scaffold's task file.

    Text substitution rather than a YAML round trip, on purpose: the scaffold
    output is full of comments that explain why each section is what it is,
    and a load-then-dump would throw every one of them away. The comments are
    the reason the file teaches anything.
    """
    if not criteria:
        return scaffold_yaml, "no acceptance criteria found in that document"

    lines = ["acceptance_criteria:"]
    for item in criteria:
        lines.append('  - "%s"' % str(item).replace('"', '\\"'))
    block = "\n".join(lines) + "\n"

    if not _CRITERIA_BLOCK.search(scaffold_yaml):
        return scaffold_yaml, "the scaffold has no acceptance_criteria section to fill"
    return _CRITERIA_BLOCK.sub(block, scaffold_yaml, count=1), None
