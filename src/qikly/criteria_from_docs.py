"""
Acceptance criteria read out of prose documentation, with its working shown.

`criteria_import` reads criteria somebody has already written as a list, under
a heading, and deliberately refuses to touch anything else: "it never guesses
at prose", because a criterion nobody wrote is the invented bar this project
argues against. That refusal is right, and it leaves a gap. Most projects have
no "Acceptance criteria" heading anywhere. What they have is a README making
claims in sentences, and the rules are implicit in those sentences.

This reads that prose. Its guard is narrower than the rule above and says so:
**the quote beside each criterion is checked against the document, but the
criterion is the model's wording of that quote, and a reader has to compare
the two.** What is enforced, and what is merely asked for:

  - **Enforced.** Every criterion carries the sentence it came from, and
    that sentence must be found as one or more whole sentences of a single
    document before the criterion is kept. A model will invent a quote: on
    the first run against one project it fabricated three different versions
    of the same line, and the check caught all three. An earlier, weaker
    version of this check accepted a single letter, and accepted a fragment
    that dropped the word "never" and so inverted the claim.
  - **Enforced.** The same check is applied to the rejected sentences,
    because one printed beside a `>` marker looks exactly like a verified
    quote.
  - **Asked for, not enforced.** That a sentence which cannot be tested is
    rejected rather than guessed at. That is a prompt instruction, and a
    prompt cannot be relied on.
  - **Asked for, not enforced.** That the criterion faithfully restates its
    quote. Nothing compares the two, which is why both are printed together.

It reads only the files it is given, and the caller is expected to give it
documentation. Note that a model may also know a well-known project's
implementation from pretraining, so "never saw the source" is a statement
about this program rather than about everything the model has read.
"""
import json
import os
import re
import unicodedata

PROMPT = """You are reading the published documentation of a software project.

You have NOT been shown its source code, its tests, or its issue tracker, and
you must not guess at them. Everything you write must be supported by a
sentence in the text below.

Extract ACCEPTANCE CRITERIA: statements of observable behaviour that a test
could check by calling the public interface and comparing a result.

Rules, in order of importance:

1. Every criterion must be traceable to the documentation, and you will
   quote the source **exactly as it appears, character for character**. The
   source may be:
     - one sentence, or
     - one row of a table, including a requirements table, or
     - one line of a code example, or an input line and the output line
       shown beneath it.

   Copy it verbatim. Do not tidy it, reflow it, merge two lines into one
   readable sentence, or turn `>>> f(1)` and `2` into "f(1) returns 2". A
   reconstruction is not a quote, and anything that is not found in the
   document word for word is discarded along with its criterion.

2. Reject a sentence only when two careful readers would disagree about WHAT
   IS BEING CLAIMED. The test is not whether it spells out an exact output.
   It is whether, shown some observed behaviour, two readers would agree on
   whether that behaviour conforms.

   REJECT, because the claim itself is unclear:
     - "the indentation is changed"              (to what?)
     - "tries to produce more compact output"    (how compact?)
     - "repeated whitespace is collapsed"        (in the input, the output,
                                                  or both? a reader cannot
                                                  tell)

   KEEP, even with no exact output given, because the claim is unambiguous:
     - "simple is the default format"
     - "an unknown format name raises ValueError"
     - "missing values are shown as an empty string unless missingval is set"

   Err toward keeping. A criterion that proves too loose costs one discarded
   test. Rejecting a good one costs a finding nobody will ever see.

3. Name a boundary or an exact value ONLY where the documentation states
   one. If it says "must be positive", write "must be positive". Do not
   choose the first accepted value yourself: for a float parameter that is a
   guess, and a guessed bar is exactly what this must not produce.

4. State what must be TRUE after the call, not what happens internally. You
   cannot see the internals and must not speculate.

5. Prefer defaults, exact literal values, error conditions and documented
   relationships between options. Those are the claims a project most often
   drifts away from.

Return STRICT JSON and nothing else:

{{
  "criteria": [
    {{"criterion": "<one testable statement>",
      "source": "<the exact sentence from the documentation>"}}
  ],
  "rejected": [
    {{"sentence": "<the source you rejected, quoted exactly>",
      "kind": "ambiguous_claim" | "not_a_claim",
      "why": "<what it leaves open, or why it is not a claim>"}}
  ]
}}

`kind` matters and the two are not the same thing:

  - **ambiguous_claim**: it DOES assert something about behaviour, but
    leaves the answer open. "repeated whitespace is collapsed" is a claim
    whose scope a reader cannot settle. These are the useful rejections.
  - **not_a_claim**: it asserts nothing testable in the first place.
    "Tabulate is a Python3 library", or a line introducing an example. These
    are ordinary prose and say nothing about documentation quality.

Do not list every non-claim sentence in the document. Only list a
`not_a_claim` where a reader might reasonably have expected it to be one.

Quality over quantity. Ten criteria that pin down a result are worth more
than thirty that do not.

THE DOCUMENTATION:

{docs}
"""

# One prompt holds the lot, so a whole docs/ tree would be sent in a single
# call. Naming the few pages that make behavioural claims is both cheaper and
# better: a stub page yields nothing and still costs tokens.
_MAX_CHARS = 200000

# One escape at a time, consumed whole: a valid pair, or a lone backslash with
# nothing valid after it. Scanning character by character instead misread the
# second backslash of a valid `\\d` as the start of a new escape.
_ESCAPE = re.compile(r'\\(?:(["\\/bfnrt]|u[0-9a-fA-F]{4})|)')

# JSON escapes that are valid but almost never meant in documentation. A regex
# `\b` arrives as a backspace and a literal `\n` in prose as a line break, so
# the quote no longer matches the document, and an honest criterion would be
# reported as a fabricated citation.
_UNESCAPE = {"\x08": r"\b", "\x0c": r"\f", "\r": r"\r", "\n": r"\n",
             "\t": r"\t"}


def _loads(text):
    """
    Parse the reply, repairing the one thing that reliably breaks it.

    Documentation is full of backslashes, in format strings and regex
    examples, and a model passes them into JSON unescaped. JSON allows only a
    short list of escapes, so one stray backslash makes the entire reply
    unparseable. Doubling the invalid ones keeps the quoted sentence faithful,
    which matters because that quote is what a reader checks.

    The repair runs before the salvage of a truncated reply, not after:
    salvage parses each object on its own and skips any it cannot, so running
    it first quietly lost every criterion holding a stray backslash.
    """
    if "{" not in text:
        raise ValueError("the model did not return a JSON object. It began: "
                         "%s" % _squash(text)[:300])
    repaired = _ESCAPE.sub(
        lambda m: m.group(0) if m.group(1) else r"\\", text)
    for candidate in (text, repaired):
        found = _first_reply(candidate)
        if found is not None:
            return found
    salvaged = _salvage(repaired)
    if salvaged is not None:
        return salvaged
    # The call has been paid for, so show what came back rather than only
    # that it failed.
    raise ValueError("the model's reply is not valid JSON. It began: %s"
                     % _squash(text)[:300])


def _first_reply(text):
    """
    The first `{...}` that parses as the reply object, or None.

    Not simply the span from the first brace to the last: a model may write
    prose before the JSON, and prose mentioning `{criteria}` put the start in
    the wrong place and lost the whole reply.
    """
    decoder = json.JSONDecoder()
    best, best_size = None, -1
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and ("criteria" in obj or "rejected" in obj):
            # The largest, not the first: a model that restates the format
            # as `{"criteria": []}` before answering made the empty example
            # the reply, reported as "no testable claim found".
            size = sum(len(v) for v in (obj.get("criteria"), obj.get("rejected"))
                       if isinstance(v, list))
            if size > best_size:
                best, best_size = obj, size
    return best


def _salvage(text):
    """
    Whole objects out of a reply that stopped mid-sentence.

    A long documentation set makes the model emit more criteria than its
    output budget allows, and the reply then ends inside a string. Throwing
    the whole thing away loses every complete criterion before the cut, and
    the call has already been paid for. So each `{...}` object is parsed on
    its own and the broken tail is dropped.

    Returns None when nothing could be recovered, so the caller can report
    the original parse error rather than a confusing empty success.
    """
    decoder = json.JSONDecoder()
    out = {"criteria": [], "rejected": []}
    key = None
    for match in re.finditer(r'"(criteria|rejected)"\s*:\s*\[|\{', text):
        if match.group(1):
            key = match.group(1)
            continue
        if key is None:
            continue
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            out[key].append(obj)
    return out if (out["criteria"] or out["rejected"]) else None


def _squash(s):
    return " ".join((s or "").split())


def _shown(s):
    """
    `_squash`, then any character YAML refuses written as an escape.

    For the report only, never for matching. An ANSI colour code in a quoted
    line, or a DEL in the model's reason, made the whole output unparseable.
    """
    return "".join(ch if ch.isprintable() else "\\x%02x" % ord(ch)
                   if ord(ch) < 0x100 else "\\u%04x" % ord(ch)
                   for ch in _squash(s))


def _as_quoted(quote, bodies):
    """
    The form of `quote` found in the documents, or None.

    Tried as given first, then with the control characters a JSON escape
    produced turned back into the two characters the document holds.
    """
    if _is_quoted(quote, bodies):
        return quote
    # The rare escapes first on their own, because a real line break in the
    # same quote as a regex `\b` must stay a line break; then everything.
    for keep in ("\n\t", ""):
        restored = "".join(ch if ch in keep else _UNESCAPE.get(ch, ch)
                           for ch in quote)
        if restored != quote and _is_quoted(restored, bodies):
            return restored
    return None


def _is_quoted(quote, bodies, min_words=4):
    """
    Whether `quote` is one or more whole sentences of a single document.

    A plain `quote in haystack` is far too weak, and the feature's whole
    claim rests on this. Against one document that check accepted:

      - "e", a single letter
      - "raises on empty input." lifted out of "The parser never raises on
        empty input", which inverts the meaning
      - "### a.md", which is qikly's own file header rather than the document
      - a fragment spanning the end of one file and the start of the next

    So each document is first cut into units, `_units`, and a quote must be
    one or more whole sentences of a single unit. A line break is not a
    sentence boundary: hard-wrapped prose made "raise on empty input" a line
    of its own, and an earlier version that treated every line start as a
    sentence start accepted it without the "never" on the line above. Nor is
    a colon: "The following is no longer true: the default is 30" must not
    yield "the default is 30".

    Whitespace is flexible because prose wraps, and both sides are
    NFC-normalised so a composed character is not mistaken for a fabrication.
    A line of code is the one unit that may be quoted with fewer than
    `min_words` words, because `>>> add(1, 2)` is exactly what the prompt
    asks for, and it must then be the whole line.
    """
    quote = unicodedata.normalize("NFC", quote or "")
    lines = [_squash(l) for l in quote.splitlines() if l.strip()]
    if not lines:
        return False
    for body in bodies:
        units = _units(unicodedata.normalize("NFC", body))
        texts = [text for text, _ in units]
        # An input line and the output shown beneath it, quoted together:
        # consecutive code lines, each matched whole.
        if len(lines) > 1:
            for i in range(len(units) - len(lines) + 1):
                if (texts[i:i + len(lines)] == lines
                        and any(code for _, code in units[i:i + len(lines)])):
                    return True
        wanted = _strip_marker(_squash(quote))
        for text, code in units:
            if code:
                if wanted == text and len(wanted.replace(" ", "")) >= 3:
                    return True
                continue
            if len(wanted.split()) < min_words:
                continue
            for candidate in (wanted, _unwrap_quotes(wanted)):
                if candidate and _whole_sentences(candidate, text):
                    return True
    return False


_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"""[.!?]["')\]]*$""")


def _strip_marker(text):
    return _MARKER.sub("", text, count=1)


def _unwrap_quotes(text):
    """`'Use raw strings.'` as a table cell often comes back with its quotes."""
    if len(text) > 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1].strip()
    return None


def _whole_sentences(quote, text):
    """Whether `quote` sits in `text` starting and ending on sentence edges."""
    start = text.find(quote)
    while start >= 0:
        end = start + len(quote)
        starts = start == 0 or _SENTENCE_END.search(text[:start].rstrip()) \
            and text[start - 1] == " "
        ends = end == len(text) or (_SENTENCE_END.search(quote)
                                    and text[end] == " ")
        if starts and ends:
            return True
        start = text.find(quote, start + 1)
    return False


def _units(body):
    """
    A document as [(text, is_code)], each a place a sentence cannot cross.

    Paragraphs are joined across their wrapped lines; a list item, a heading,
    each table row and each of its cells, and each line of a code block or a
    doctest stand alone. Text is whitespace-squashed.
    """
    import csv

    units, para = [], []
    fence = indented = doctest = False

    def flush():
        if para:
            units.append((_squash(" ".join(para)), False))
            del para[:]

    previous_blank = True
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            flush()
            fence = not fence
            previous_blank = False
            continue
        if fence:
            if line:
                units.append((_squash(line), True))
            continue
        if not line:
            flush()
            doctest = indented = False
            previous_blank = True
            continue
        if raw.startswith(("    ", "\t")) and (indented or previous_blank) \
                and not para:
            # An indented block after a blank line: Markdown code, or an
            # RST literal block after `::`.
            indented = True
            units.append((_squash(line), True))
            continue
        indented = False
        previous_blank = False
        if line.startswith((">>>", "...")) or doctest:
            # A doctest prompt, and the output lines under it until a blank.
            flush()
            doctest = True
            units.append((_squash(line), True))
            continue
        if line.startswith("|") or line.count("|") >= 2:
            flush()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(set(c) <= set("-:= ") for c in cells):
                units.append((_squash(" ".join(cells)), False))
                units.extend((_squash(c), False) for c in cells if c)
            continue
        if line[0] in "'\"" and "," in line:
            # A row of an RST csv-table, such as a requirements table.
            flush()
            try:
                cells = next(csv.reader([line], skipinitialspace=True,
                                        quotechar=line[0]))
            except (csv.Error, StopIteration):
                cells = []
            units.append((_squash(line), False))
            units.extend((_squash(c), False) for c in cells if c.strip())
            continue
        if line.startswith("#") or set(line) <= set("=-~^*+#"):
            flush()
            heading = line.lstrip("#").strip()
            if heading:
                units.append((_squash(heading), False))
            continue
        if _MARKER.match(line):
            flush()
            para.append(_strip_marker(line))
            continue
        para.append(line.lstrip("> ").strip() if line.startswith(">")
                    else line)
    flush()
    return units


def extract(paths, seed=None):
    """
    Criteria from the documents at `paths`, and the sentences refused.

    Returns (criteria, rejected, unquoted). `unquoted` holds criteria dropped
    because their quote is not in the source: a reader cannot check those, so
    reporting them would be worse than leaving them out.
    """
    from qikly.agent_api.call_llm import call_llm

    # Check the contents before the filename headers are added, or a file
    # holding nothing but whitespace still looks non-empty and still costs a
    # model call.
    blobs, bodies = [], []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            body = handle.read()
        if "\x00" in body:
            raise ValueError("%s is not text" % os.path.basename(path))
        if body.strip():
            # Kept separately from `blobs`: a quote must be found in one
            # document's own text, never across a join and never in the
            # `### name` header this adds.
            bodies.append(body)
        blobs.append("### %s\n\n%s" % (os.path.basename(path), body))
    if not bodies:
        raise ValueError("those documents are empty")
    docs = "\n\n".join(blobs)
    if len(docs) > _MAX_CHARS:
        raise ValueError(
            "those documents total %d characters, over the %d limit. Name "
            "the few pages that make behavioural claims rather than the "
            "whole set." % (len(docs), _MAX_CHARS))

    reply = call_llm("test_system", PROMPT.format(docs=docs), seed=seed)
    data = _loads(reply)

    criteria, unquoted = [], []
    # A criterion the parser lost, through a truncated reply or a quote
    # ending in a backslash, otherwise vanished without appearing in either
    # list. It is counted, so the report can at least say so.
    parsed = data.get("criteria") if isinstance(data.get("criteria"),
                                                list) else []
    lost = reply.count('"criterion"') - len(parsed)
    if lost > 0:
        unquoted.append({"criterion": "(%d more in the model's reply could "
                                      "not be parsed)" % lost, "source": ""})
    for item in data.get("criteria") or []:
        # A reply is a model's output, not a contract: an item may be a bare
        # string, or carry a number where a sentence belongs.
        if not isinstance(item, dict):
            continue
        criterion, source = item.get("criterion"), item.get("source")
        if not isinstance(criterion, str) or not criterion.strip():
            continue
        found = _as_quoted(source, bodies) if isinstance(source, str) else None
        if found is not None:
            if found != source:
                # The criterion went through the same JSON decoding, so the
                # same backspace or form feed is in it. Line breaks and tabs
                # are left alone: in a criterion they are only whitespace.
                criterion = "".join(_UNESCAPE[ch] if ch in "\x08\x0c\r"
                                    else ch for ch in criterion)
            criteria.append({"criterion": criterion, "source": found})
        else:
            unquoted.append({"criterion": criterion,
                             "source": source if isinstance(source, str)
                             else ""})

    # Rejections are checked too. One printed beside a `>` marker looks
    # exactly like a verified quote, so an invented sentence would be
    # indistinguishable from a real one.
    rejected = []
    for item in data.get("rejected") or []:
        if not isinstance(item, dict):
            continue
        sentence = item.get("sentence")
        found = (_as_quoted(sentence, bodies) if isinstance(sentence, str)
                 else None)
        if found is not None:
            kind = item.get("kind")
            rejected.append({
                "sentence": found,
                # Only an ambiguous claim is evidence that documentation is
                # imprecise. A sentence that was never a claim is ordinary
                # prose, and counting it would inflate the finding.
                "kind": kind if kind in ("ambiguous_claim", "not_a_claim")
                else "unlabelled",
                "why": str(item.get("why") or "").strip()})
    return criteria, rejected, unquoted


def render(paths, criteria, rejected, unquoted):
    """
    The report, shaped so the whole thing can be pasted into a task file.

    Every line that is not YAML is a comment, because the output is meant to
    be redirected and pasted. Prose printed bare alongside the list would
    make the file unparseable the moment anyone did that.

    Criteria are emitted with `json.dumps`, which is valid YAML for a scalar
    and the only way to survive the two cases that broke the first version:
    a criterion containing a backslash, such as `matches \\d+ digits`, which
    produced a scanner error, and one containing a double quote, which was
    rewritten to a single quote and silently changed the literal the prompt
    had asked the model to preserve exactly.
    """
    names = ", ".join(os.path.basename(p) for p in paths)
    lines = ["# Read %s. The model was shown only these files." % names, ""]

    if criteria:
        lines.append("acceptance_criteria:")
        for item in criteria:
            # The quote travels with the criterion, so the citation survives
            # into the task file rather than being left behind in a terminal.
            lines.append("  # > %s" % _shown(item["source"]))
            # json.dumps escapes C0 controls but leaves DEL and C1 raw, which
            # YAML refuses, so those are escaped as well.
            dumped = json.dumps(_squash(item["criterion"]),
                                ensure_ascii=False)
            lines.append("  - %s" % "".join(
                "\\u%04x" % ord(ch) if 0x7f <= ord(ch) <= 0x9f else ch
                for ch in dumped))
    else:
        lines.append("# No testable claim found. That is a finding about the "
                     "documentation rather than an error.")

    if rejected:
        ambiguous = [r for r in rejected
                     if r.get("kind") != "not_a_claim"]
        other = len(rejected) - len(ambiguous)
        lines += ["", "# Claims that cannot be tested as written (%d)%s. "
                      "Each asserts something about behaviour but leaves "
                      "the answer open:"
                  % (len(ambiguous),
                     ", plus %d sentences that make no claim" % other
                     if other else "")]
        for item in ambiguous:
            lines.append("#   > %s" % _shown(item.get("sentence")))
            lines.append("#     %s" % _shown(item.get("why")))

    if unquoted:
        lines += ["", "# Dropped because the quote could not be found as a "
                      "whole sentence of one of these documents (%d). A "
                      "model will invent a citation, so each is checked and "
                      "an unverifiable criterion is not reported:"
                  % len(unquoted)]
        for item in unquoted:
            lines.append("#   %s" % _shown(item.get("criterion")))
            # The claimed source, so a reader can tell a fabricated citation
            # from a real passage this check could not match. Without it the
            # two are indistinguishable, and that hid a serious fault: every
            # requirement in a project's formal requirements table was
            # dropped, because a table row is not a sentence.
            lines.append("#     claimed: %s"
                         % (_shown(item.get("source")) or "(none given)"))

    lines += ["", "# Each criterion is the model's wording of the quote above "
                  "it, and only the quote is checked. Read the two together "
                  "before using them. Only the files named at the top were "
                  "sent; if any of them is source code, these criteria "
                  "describe that code rather than a standard for it."]
    return "\n".join(lines)
