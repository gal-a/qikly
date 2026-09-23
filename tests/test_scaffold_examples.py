"""
The worked example is real output, and stays real.

`inputs_public/examples/` mirrors the layout of a real project, so a reader sees
where these files belong rather than a flat folder of samples: the two task
files `qikly --scaffold` writes for `my_metrics.py`, one with `--fresh` and one
without, under `config/tasks/`, the sample data under `data/MY_METRICS/`, and
the module itself under `reference/MY_METRICS/`.

Under examples/ rather than beside the bundled tasks, and deliberately. A
scaffolded pair breaks two rules bundled tasks keep: `MY_METRICS_VERIFY` ends
in the suffix reserved for scaffolding, and the pair shares one data folder
where bundled ids map one to one. Shipping it as a bundled task would have cost
both, and would have put an example in everyone's task list.

What it no longer carries is scaffold's `TODO`s. The two sections a person
writes are written here, because `--example` prints the paid `qikly --tasks`
command as a next step and a newcomer who types it should not be paying for a
run whose requirements say TODO.

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


# The two sections a person writes are the two this cannot pin: they are not
# derived from the module, and a worked example exists precisely so that they
# are written rather than left as placeholders. Everything scaffold decides
# mechanically is still compared, field by field.
def _interface(task):
    """The interface as scaffold determines it, without the prose after `#`."""
    interface = task["interface"]
    functions = [f.split("#")[0].strip()
                 for f in interface.get("integration_functions") or []]
    return (interface["module"], functions,
            interface["system_entrypoint"].split("#")[0].strip())


@pytest.mark.parametrize("fresh,name", [
    (False, "MY_METRICS_VERIFY.yaml"),
    (True, "MY_METRICS.yaml"),
])
def test_the_committed_example_is_what_scaffold_writes_today(fresh, name):
    # No skip path on purpose. An earlier version of this test unpacked the
    # wrong element of build_task's (text, error) pair, got None, and skipped
    # itself quietly, which is the failure mode this whole file exists to
    # prevent: a guard that reports success while checking nothing.
    import yaml

    written = yaml.safe_load(_scaffold(fresh))
    committed = yaml.safe_load(_committed(name))
    regenerate = ("Regenerate %s rather than editing it by hand." % name)

    assert set(committed) == set(written), "a top level section came or went"
    assert committed["task_id"] == written["task_id"], regenerate
    assert committed["outputs"] == written["outputs"], regenerate
    assert committed.get("seed") == written.get("seed"), regenerate
    assert _interface(committed) == _interface(written), (
        "the interface is no longer what scaffold reads out of my_metrics.py. "
        + regenerate)

    # Scaffold names one input file because it cannot know how many you have,
    # and the example adds the second it ships. The first must still be the
    # path scaffold derives from the task id, because that is the derivation
    # that silently moves where a run reads from.
    assert committed["inputs"][:1] == written["inputs"], regenerate


@pytest.mark.parametrize("name", ["MY_METRICS_VERIFY.yaml", "MY_METRICS.yaml"])
def test_the_worked_example_has_nothing_left_to_fill_in(name):
    """
    `--example` prints the paid `qikly --tasks` command as a next step.

    While these two files carried scaffold's placeholders, that run went out
    with a specification that read, literally, "TODO: describe what this module
    must do". `--validate` warned and exited 0, so nothing stopped it. The
    example is the one task that has to arrive finished, and this is the check
    that keeps it that way, using validate's own placeholder pattern.
    """
    import yaml

    from qikly.validate import _TODO

    task = yaml.safe_load(_committed(name))
    left = [field for field in ("task_name", "description", "interface",
                                "requirements", "acceptance_criteria")
            if _TODO.search(str(task.get(field)))]
    assert not left, "still to fill in: %s" % ", ".join(left)


@pytest.mark.parametrize("name", ["MY_METRICS_VERIFY.yaml", "MY_METRICS.yaml"])
def test_every_boundary_the_criteria_name_is_reachable_in_the_sample_data(name):
    """
    The lesson the example teaches, applied to the example itself.

    A criterion no row can trigger is a criterion nothing checks. Each value
    below is the boundary of one written criterion, and each must appear in the
    data the task actually reads, not merely in the folder beside it.
    """
    import yaml

    task = yaml.safe_load(_committed(name))
    rows = ""
    for declared in task["inputs"]:
        path = os.path.join(EXAMPLE, "data", os.path.basename(os.path.dirname(declared)),
                            os.path.basename(declared))
        with open(path, encoding="utf-8") as handle:
            rows += handle.read()

    for value, criterion in (
            ("100", "a humidity of 100 is usable"),
            ("101", "a humidity of 101 is not"),
            ("0.0", "0.0 is a measurement rather than a missing value"),
            ("4.5", "the mean of 4.5 and 11.2 rounds away from zero"),
            ("11.2", "the mean of 4.5 and 11.2 rounds away from zero"),
            ("-1.0", "a negative temperature is usable"),
            ("not-a-timestamp", "a malformed timestamp contributes to no record")):
        assert value in rows, (
            "no row reaches %r, so nothing checks the criterion that %s"
            % (value, criterion))


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
                    "%s says it reads %s, and --example does not put a file "
                    "there" % (name, declared))

        # The seeded task names its implementation relative to the project root.
        seed = yaml.safe_load(_committed("MY_METRICS_VERIFY.yaml"))["seed"]
        landed = os.path.join(workspace, seed["implementation"].replace("/", os.sep))
        assert os.path.isfile(landed), (
            "MY_METRICS_VERIFY.yaml seeds from %s, which --example does not "
            "write there" % seed["implementation"])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_the_example_arrives_without_the_blank_starter_beside_it():
    """
    One command, one task.

    `--example` needs the same directory layout `--init` makes, and used to get
    the MY_FIRST_TASK starter along with it. A newcomer running the command the
    quick start recommends first ended up with two unrelated tasks, one of them
    described nowhere, and a later bare `qikly` with no --tasks would have run
    both of them for real money.
    """
    from qikly import scaffold

    workspace = tempfile.mkdtemp(prefix="qikly-example-alone-")
    try:
        scaffold.init_project(workspace, starter=False)
        scaffold.install_example(workspace)

        tasks = os.path.join(workspace, "inputs_private", "config", "tasks")
        assert sorted(os.listdir(tasks)) == ["MY_METRICS.yaml",
                                             "MY_METRICS_VERIFY.yaml"]
        assert not os.path.exists(os.path.join(
            workspace, "inputs_private", "data", "MY_FIRST_TASK"))
        # The layout itself still has to be there, or the example has nowhere
        # to land and a run has nowhere to write.
        assert os.path.isdir(os.path.join(workspace, "outputs"))
        assert os.path.isfile(os.path.join(
            workspace, "inputs_private", "config", "settings.yaml"))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_init_on_its_own_still_writes_the_starter():
    """The other half of the same contract: --init is unchanged."""
    from qikly import scaffold

    workspace = tempfile.mkdtemp(prefix="qikly-init-starter-")
    try:
        scaffold.init_project(workspace)
        assert os.path.isfile(os.path.join(
            workspace, "inputs_private", "config", "tasks", "MY_FIRST_TASK.yaml"))
        assert os.path.isfile(os.path.join(
            workspace, "inputs_private", "data", "MY_FIRST_TASK", "input_01.csv"))
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
