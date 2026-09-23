import re

# A collection error names no test, because pytest never reached one, so the
# summary line used to read "Unknown failure": true, and the least useful
# sentence available. The whole error sits further down in the raw output, and
# the first line of a FIX prompt is the line most likely to be acted on.
#
# Found running CALC_TAX on gpt-4o, which spent nine of its twelve iterations
# on a module that would not import. Gemini rarely produces that shape, so the
# weakness stayed invisible until a second model wrote differently.
_IMPORT_ERRORS = (
    r"E\s+(ModuleNotFoundError: .*)",
    r"E\s+(ImportError: .*)",
    r"E\s+(SyntaxError: .*)",
    r"E\s+(IndentationError: .*)",
    r"E\s+(NameError: .*)",
    r"E\s+(AttributeError: .*)",
)


def _collection_summary(raw):
    """
    A first line worth reading when nothing failed because nothing could run.

    Names the shape before the detail: this is not a wrong answer, it is code
    that cannot be loaded, and no other finding means anything until it is.
    """
    text = raw or ""
    if "ERROR collecting" not in text and "error during collection" not in text:
        return "Unknown failure"
    for pattern in _IMPORT_ERRORS:
        found = re.search(pattern, text)
        if found:
            return (
                "COLLECTION ERROR: the test module could not be imported, so no "
                "test ran.\n"
                f"{found.group(1).strip()}\n"
                "Fix that first. Nothing else can be assessed until the module "
                "loads.")
    return ("COLLECTION ERROR: the test module could not be imported, so no test "
            "ran. Fix that first; nothing else can be assessed until it loads.")


# `# Requirements: 2, 4` and `# Criteria: 2`, as test generation writes them
# into a docstring and `qikly.traceability` reads them back. Tolerant about
# spacing and about the label's plural, because a model writes the line.
_TRACE_MARKER = re.compile(
    r"^\s*#\s*(?:requirements?|criteri(?:on|a))\s*:.*$",
    re.IGNORECASE | re.MULTILINE)


def strip_traceability_markers(text):
    """
    Remove the criteria and requirement markers from text bound for the agent.

    They exist for the person reviewing the suite and for the coverage report,
    and they say nothing that helps a repair: a criterion's number is not a
    rule. What they do say is how many criteria there are and which one this
    test came from, which across iterations maps out the bar the agent is
    being judged against. Removing them costs nothing, which is what makes
    this the one narrowing that is on by default.

    The file on disk keeps its markers. Only the agent's copy loses them, so
    the report, `traceability.py` and anyone reading the suite are unaffected.
    """
    if not text:
        return text
    return _TRACE_MARKER.sub("", text)


def inspect_failure(result, strip_markers=True):
    """
    Convert pytest output into a clean failure description
    that the agent can reason about.

    `strip_markers` is the traceability narrowing above. It defaults to on
    here rather than at the call site so that a future call site cannot
    reintroduce the leak by forgetting about it.
    """

    raw = result.get("raw_output", "")
    failed_tests = result.get("failed_tests", [])

    summary = "\n".join(failed_tests) if failed_tests else _collection_summary(raw)

    if strip_markers:
        raw = strip_traceability_markers(raw)
        summary = strip_traceability_markers(summary)

    return f"""
Test Failure Summary:
{summary}

Raw Output:
{raw}
""".strip()


def failure_signature(result):
    """
    A stable identifier for "what's currently failing", ignoring volatile
    noise like timing (e.g. "1 error in 0.53s") and pytest banner text.
    Used to detect when a successfully-applied patch had no real effect on
    the test outcome.
    """
    tests = result.get("tests", [])
    not_passed = sorted(f"{name}:{status}" for name, status in tests if status != "passed")
    if not_passed:
        return "|".join(not_passed)

    # No per-test results available (e.g. a collection error) -- fall back to
    # the actual exception line(s) pytest prints, which pytest always
    # prefixes with "E ".
    raw = result.get("raw_output", "")
    exception_lines = [l.strip() for l in raw.splitlines() if l.strip().startswith("E ")]
    return "|".join(exception_lines) if exception_lines else raw.strip()
