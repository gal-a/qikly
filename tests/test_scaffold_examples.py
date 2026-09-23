"""
The worked example is real output, and stays real.

`inputs_public/examples/` mirrors the layout of a real project, so a reader sees
where these files belong rather than a flat folder of samples: the two task
files `qikly --scaffold` writes for `my_metrics.py`, one with `--fresh` and one
without, under `config/tasks/`, the sample data under `data/MY_METRICS/`, and
the module itself under `reference/MY_METRICS/`.

Under examples/ rather than beside the bundled tasks, and deliberately. A
scaffolded pair breaks three rules bundled tasks keep: `MY_METRICS_VERIFY` ends
in the suffix reserved for scaffolding, the pair shares one data folder where
bundled ids map one to one, and both files still carry the `TODO`s that are the
point of an example. Shipping it as a bundled task would have cost all three.

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
EXAMPLE = os.path.join(ROOT, "src", "qikly", "inputs_public", "examples")
TASKS = os.path.join(EXAMPLE, "config", "tasks")
DATA = os.path.join(EXAMPLE, "data", "MY_METRICS")
MODULE = os.path.join(EXAMPLE, "reference", "MY_METRICS", "my_metrics.py")


def _scaffold(fresh):
    """Run scaffold on the committed module in a throwaway project root."""
    from qikly import scaffold

    workspace = tempfile.mkdtemp(prefix="qikly-scaffold-example-")
    try:
        module = os.path.join(workspace, "my_metrics.py")
        shutil.copy2(MODULE, module)
        text, error = scaffold.build_task(
            module, workspace, seed=None if fresh else "existing")
        assert error is None, "scaffold refused to build the example: %s" % error
        assert text, "scaffold returned no text and no error"
        return text
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _committed(name):
    with open(os.path.join(TASKS, name), encoding="utf-8") as handle:
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
        "inputs_public/config/tasks/%s no longer matches what `qikly --scaffold%s "
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
    for name in ("input_01.csv", "input_02.csv"):
        with open(os.path.join(DATA, name), encoding="utf-8") as handle:
            rows.extend(handle.read().splitlines()[1:])

    joined = "\n".join(rows)
    assert ",," in joined, "no row with a missing value"
    assert "warm" in joined, "no row with a non-numeric reading"
    assert "101" in joined, "no row outside a plausible range"
    assert "not-a-timestamp" in joined, "no row with a malformed timestamp"
    assert len(rows) >= 10, "too little data to be a realistic sample"


def _install(root):
    from qikly import scaffold

    return scaffold.install_example(root)


def test_the_example_installs_to_the_paths_its_own_task_files_name():
    """
    The copy map and the task files have to agree, or the example lands
    somewhere the run does not look.

    This is the failure the map exists to prevent, and it is silent: scaffold's
    default input path is built from the task id, so a change there moves where
    a run reads from while the CSVs keep landing where they always did. The
    reader then gets `input file not found` on an example advertised as ready
    to run. So this reads the destination out of the committed YAML rather than
    restating it.
    """
    import yaml

    workspace = tempfile.mkdtemp(prefix="qikly-install-example-")
    try:
        made, skipped, missing = _install(workspace)
        assert not missing, "the example is not in the tree: %s" % missing
        assert not skipped, "nothing existed yet, so nothing should have been kept"
        assert len(made) == 5, "expected five files, wrote %d" % len(made)

        for name in ("MY_METRICS.yaml", "MY_METRICS_VERIFY.yaml"):
            task = yaml.safe_load(_committed(name))
            for declared in task["inputs"]:
                landed = os.path.join(workspace, declared.replace("/", os.sep))
                assert os.path.isfile(landed), (
                    "%s says it reads %s, and --with-example does not put a file "
                    "there" % (name, declared))

        # The seeded task names its implementation relative to the project root.
        seed = yaml.safe_load(_committed("MY_METRICS_VERIFY.yaml"))["seed"]
        landed = os.path.join(workspace, seed["implementation"].replace("/", os.sep))
        assert os.path.isfile(landed), (
            "MY_METRICS_VERIFY.yaml seeds from %s, which --with-example does not "
            "write there" % seed["implementation"])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_installing_the_example_twice_keeps_what_is_already_there():
    """The contract --init states, held to: your edits survive a second run."""
    workspace = tempfile.mkdtemp(prefix="qikly-install-example-")
    try:
        made, _, _ = _install(workspace)
        edited = os.path.join(workspace, "my_metrics.py")
        with open(edited, "w", encoding="utf-8") as handle:
            handle.write("# mine now\n")

        made_again, skipped, _ = _install(workspace)
        assert not made_again, "a second install rewrote files: %s" % made_again
        assert len(skipped) == len(made)
        with open(edited, encoding="utf-8") as handle:
            assert handle.read() == "# mine now\n", "the edited file was overwritten"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_wheel_without_the_examples_reports_rather_than_half_installs():
    """
    package-data is a glob in pyproject.toml, so it can silently stop matching.
    If that happens the command should say which files are absent, not write
    three of five and leave the reader with a task whose data is missing.
    """
    from qikly import scaffold

    workspace = tempfile.mkdtemp(prefix="qikly-install-example-")
    empty = tempfile.mkdtemp(prefix="qikly-no-examples-")
    try:
        original = scaffold.example_source_dir
        scaffold.example_source_dir = lambda: empty
        try:
            made, skipped, missing = scaffold.install_example(workspace)
        finally:
            scaffold.example_source_dir = original

        assert not made and not skipped
        assert len(missing) == 5, "every absent file should be named: %s" % missing
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(empty, ignore_errors=True)
