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


def inspect_failure(result):
    """
    Convert pytest output into a clean failure description
    that the agent can reason about.
    """

    raw = result.get("raw_output", "")
    failed_tests = result.get("failed_tests", [])

    summary = "\n".join(failed_tests) if failed_tests else _collection_summary(raw)

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
