"""
The worked example in docs/examples/ is real output, and stays real.

`docs/examples/` holds the two task files `qikly --scaffold` writes for
`my_metrics.py`, one with `--fresh` and one without, and the quick start links
to them so a reader can see what step 1 produces instead of reading a
description of it.

An example nobody regenerates drifts. That is not hypothetical here: the worked
example in `docs/design_1_case_study.md` printed a test with a name and a body
that appeared in no run artifact anywhere, and it sat there until somebody
checked. The prose around it had been written to match the invention.

So this regenerates both files from the committed module and compares. Scaffold
makes no model call, so this costs nothing and needs no key.
"""
import os
import shutil
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "docs", "examples")


def _scaffold(fresh):
    """Run scaffold on the committed module in a throwaway project root."""
    from qikly import scaffold

    workspace = tempfile.mkdtemp(prefix="qikly-scaffold-example-")
    try:
        module = os.path.join(workspace, "my_metrics.py")
        shutil.copy2(os.path.join(EXAMPLES, "my_metrics.py"), module)
        text, error = scaffold.build_task(
            module, workspace, seed=None if fresh else "existing")
        assert error is None, "scaffold refused to build the example: %s" % error
        assert text, "scaffold returned no text and no error"
        return text
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _committed(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as handle:
        return handle.read()


@pytest.mark.parametrize("fresh,name", [
    (False, "MY_METRICS_VERIFY.yaml"),
    (True, "MY_METRICS.yaml"),
])
def test_the_committed_example_is_what_scaffold_writes_today(fresh, name):
    # No skip path on purpose. An earlier version of this test unpacked the
    # wrong element of build_task's (text, error) pair, got None, and skipped
    # itself quietly, which is the failure mode this whole file exists to
    # prevent: a guard that reports success while checking nothing.
    text = _scaffold(fresh)
    assert text.strip() == _committed(name).strip(), (
        "docs/examples/%s no longer matches what `qikly --scaffold%s "
        "my_metrics.py` writes. Regenerate it rather than editing it by hand."
        % (name, " --fresh" if fresh else ""))


def test_the_two_examples_differ_only_in_the_seed_block_and_the_task_id():
    """
    The point the README makes, held to.

    A reader comparing the two files should find one meaningful difference:
    the `seed:` block that says whether the code already exists. If a future
    change makes them diverge somewhere else, the README's explanation stops
    being true and this says so.
    """
    verify = _committed("MY_METRICS_VERIFY.yaml").splitlines()
    fresh = _committed("MY_METRICS.yaml").splitlines()

    def meaningful(lines):
        out = []
        for line in lines:
            line = line.replace("MY_METRICS_VERIFY", "MY_METRICS").rstrip()
            if line and not line.startswith("#"):
                out.append(line)
        return out

    only_verify = [l for l in meaningful(verify) if l not in meaningful(fresh)]
    assert only_verify == ["seed:", 'implementation: "my_metrics.py"'] or \
        all("seed" in l or "implementation" in l for l in only_verify), (
            "the two examples now differ in more than the seed block: %r" % only_verify)


def test_the_sample_data_reaches_more_than_the_happy_path():
    """
    Why these CSVs exist, asserted rather than trusted.

    The README tells the reader that a criterion no row can trigger is a
    criterion nothing checks, and points at this data as the demonstration. If
    someone tidies the awkward rows out, the lesson goes with them.
    """
    rows = []
    for name in ("input_my_metrics_01.csv", "input_my_metrics_02.csv"):
        with open(os.path.join(EXAMPLES, name), encoding="utf-8") as handle:
            rows.extend(handle.read().splitlines()[1:])

    joined = "\n".join(rows)
    assert ",," in joined, "no row with a missing value"
    assert "warm" in joined, "no row with a non-numeric reading"
    assert "101" in joined, "no row outside a plausible range"
    assert "not-a-timestamp" in joined, "no row with a malformed timestamp"
    assert len(rows) >= 10, "too little data to be a realistic sample"
