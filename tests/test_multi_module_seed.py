"""
What happens when a task's implementation is more than one module.

`seed.implementation` accepts a directory as well as a file, and that one line
in `docs/TASK_FILE_REFERENCE.md` is the only place the project has ever said
so. Nothing was designed for it: the capability falls out of three unrelated
decisions, `install_seed` walking a tree, `load_codebase` reading every `.py`
under the code directory, and PATCH taking a list of target files. So before
anything is claimed about it, this file establishes what actually works.

**Read the failing shapes as specifications of today, not as bugs.** Four of
the eight import shapes below do not work, three of them are pinned here with
the exact error, and the fourth fails in plain Python too. Each one is a
statement of scope that somebody can check, which is the opposite of the
situation this file was written to end.

Written 2026-09-29, offline: no model call, no orchestrator run, nothing
beyond pytest importing modules in a temporary directory.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from qikly.agent_api.code_loader.code_loader import load_codebase


TASK = "T"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


@pytest.fixture
def bench(tmp_path):
    """A project root laid out the way a run lays one out."""
    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    tests = root / "outputs" / "tests" / TASK / "integration"
    os.makedirs(str(code))
    os.makedirs(str(tests))

    def run(import_roots=None):
        """Collect and run the generated tests exactly as a stage does."""
        env = None
        if import_roots:
            env = dict(os.environ)
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join(
                [os.path.abspath(r) for r in import_roots]
                + ([existing] if existing else []))
        return subprocess.run(
            [sys.executable, "-m", "pytest", str(tests), "-q", "--tb=line",
             "-p", "no:cacheprovider", "-o", "addopts="],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env)

    return {"root": str(root), "code": str(code), "tests": str(tests), "run": run}


def _module_under_test(bench, body):
    return _write(os.path.join(bench["code"], "pricing.py"), body)


def _importing_test(bench, name="pricing"):
    """What test generation writes: an import of `interface.module`."""
    return _write(os.path.join(bench["tests"], "test_it.py"), """
        from outputs.agent_src.code.%s.%s import total


        def test_total():
            assert total(1.0) == 1.0
    """ % (TASK, name))


# --- the import shapes, which is what decides whether any of this works -----

def test_a_relative_sibling_import_works(bench):
    """`from .money import to_cents`, the shape that does work today."""
    _write(os.path.join(bench["code"], "money.py"), "def to_cents(x):\n    return x\n")
    _module_under_test(bench, """
        from .money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _importing_test(bench)
    assert "1 passed" in bench["run"]().stdout


def test_a_relative_subpackage_import_works(bench):
    """A `utils/` folder, which is what most projects actually have."""
    _write(os.path.join(bench["code"], "utils", "money.py"),
           "def to_cents(x):\n    return x\n")
    _module_under_test(bench, """
        from .utils.money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _importing_test(bench)
    assert "1 passed" in bench["run"]().stdout


def test_a_relative_import_works_without_any_init_files(bench):
    """Namespace packages, so no `__init__.py` is required anywhere."""
    assert not os.path.exists(os.path.join(bench["code"], "__init__.py"))
    test_a_relative_sibling_import_works(bench)


def test_a_relative_import_still_works_with_init_files_present(bench):
    for folder in (bench["code"], os.path.join(bench["code"], "utils")):
        _write(os.path.join(folder, "__init__.py"), "")
    _write(os.path.join(bench["code"], "utils", "money.py"),
           "def to_cents(x):\n    return x\n")
    _module_under_test(bench, """
        from .utils.money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _importing_test(bench)
    assert "1 passed" in bench["run"]().stdout


def test_an_absolute_sibling_import_needs_the_code_directory_on_the_path(bench):
    """
    `from money import to_cents`. Without the import root it does not
    resolve, and with it it does. Both directions, because the run adds that
    root only for a task whose implementation was seeded as a package, and a
    test that checked only the working half would not notice the restriction
    disappearing.
    """
    _write(os.path.join(bench["code"], "money.py"), "def to_cents(x):\n    return x\n")
    _module_under_test(bench, """
        from money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _importing_test(bench)
    assert "No module named 'money'" in bench["run"]().stdout
    assert "1 passed" in bench["run"]([bench["code"]]).stdout


def test_a_package_that_imports_itself_by_name_works(bench):
    """
    `from mypkg.money import to_cents`, and this is the shape that matters:
    it is how most real Python packages refer to themselves.

    It works because a seeded directory now keeps its own folder name and the
    task's code directory goes on the path, so the package the code names
    still exists after it has been installed. Before 0.5.5 the folder name
    was dropped and this raised ModuleNotFoundError.
    """
    package = os.path.join(bench["code"], "mypkg")
    _write(os.path.join(package, "money.py"), "def to_cents(x):\n    return x\n")
    _write(os.path.join(package, "pricing.py"), """
        from mypkg.money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _write(os.path.join(bench["tests"], "test_it.py"), """
        from mypkg.pricing import total


        def test_total():
            assert total(1.0) == 1.0
    """)
    assert "1 passed" in bench["run"]([bench["code"]]).stdout


def test_a_circular_import_between_two_modules_does_not_work(bench):
    """
    Pinned for completeness, and it is not a qikly defect: two modules that
    import each other's names at module scope fail this way in plain Python.
    It is here so that a future reader does not mistake it for one.
    """
    _write(os.path.join(bench["code"], "money.py"), """
        from .pricing import total


        def to_cents(x):
            return total(x)
    """)
    _module_under_test(bench, """
        from .money import to_cents


        def total(x):
            return to_cents(x)
    """)
    _importing_test(bench)
    out = bench["run"]().stdout
    assert "circular import" in out or "partially initialized" in out, out


# --- what the seed does with a directory ------------------------------------

def test_a_seeded_package_keeps_its_own_name(tmp_path):
    """
    The change that makes self-reference work. Before 0.5.5 the folder's name
    was dropped, so `mypkg` stopped existing and every `from mypkg.x import y`
    inside it broke.
    """
    from qikly.orchestrator import orchestrator as orch

    src = tmp_path / "mypkg"
    _write(str(src / "pricing.py"), "X = 1\n")
    _write(str(src / "money.py"), "Y = 2\n")
    dest = tmp_path / "code" / TASK
    orch.install_seed(str(src), str(dest), keep_directory_name=True)

    assert os.path.isfile(str(dest / "mypkg" / "pricing.py"))
    assert os.path.isfile(str(dest / "mypkg" / "money.py"))


def test_a_seeded_test_directory_is_still_flattened(tmp_path):
    """
    Seeded *tests* keep the old behaviour, and must: they are installed into
    a stage directory pytest collects by path, and a stage's suite is not a
    package. Only the implementation call site asks for the name to be kept.
    """
    from qikly.orchestrator import orchestrator as orch

    src = tmp_path / "suite"
    _write(str(src / "test_a.py"), "def test_a():\n    assert True\n")
    dest = tmp_path / "tests" / "integration"
    orch.install_seed(str(src), str(dest))

    assert os.path.isfile(str(dest / "test_a.py"))
    assert not os.path.exists(str(dest / "suite"))


@pytest.mark.parametrize("seed_path", ["..", "a/../..", "."])
def test_a_seed_path_that_is_not_a_directory_name_is_refused(tmp_path, seed_path):
    """
    Found by audit 2026-09-29, before release, and the reason the name is
    validated. `seed.implementation: ".."` made the destination
    `outputs/agent_src/code/<task>/..`, which is the directory every task
    shares. The destination then contained the source, so the copy recursed
    into what it had just written until the path length ran out.
    """
    from qikly.orchestrator import orchestrator as orch

    root = tmp_path / "proj"
    _write(str(root / "a" / "keep.py"), "X = 1\n")
    dest = root / "outputs" / "agent_src" / "code" / TASK
    os.makedirs(str(dest))
    monkey = os.getcwd()
    try:
        os.chdir(str(root))
        with pytest.raises(ValueError) as raised:
            orch.install_seed(seed_path, str(dest), keep_directory_name=True)
        assert "seed.implementation" in str(raised.value)
    finally:
        os.chdir(monkey)
    # And nothing was written outside the task's own directory on the way.
    assert os.listdir(str(dest)) == []


def test_mutation_scoring_sees_a_package_seeded_implementation(tmp_path):
    """
    Found by the same audit. `implementation()` listed one directory level, so
    a package seed produced no files at all and `--score-suite` reported
    nothing to score, which reads exactly like a trivial implementation.
    """
    from qikly import mutation_score

    root = tmp_path / "code"
    _write(str(root / TASK / "mypkg" / "calc.py"), "def f():\n    return 1\n")
    _write(str(root / TASK / "mypkg" / "money.py"), "def g():\n    return 2\n")
    _write(str(root / TASK / "mypkg" / "__init__.py"), "")

    found = mutation_score.implementation(TASK, root=str(root))
    assert sorted(os.path.basename(real) for real, _rel in found) == ["calc.py", "money.py"]
    for _real, relative in found:
        assert "mypkg" in relative.replace("\\", "/")


def test_mutation_scoring_still_sees_a_flat_implementation(tmp_path):
    from qikly import mutation_score

    root = tmp_path / "code"
    _write(str(root / TASK / "calc.py"), "def f():\n    return 1\n")
    found = mutation_score.implementation(TASK, root=str(root))
    assert [os.path.basename(real) for real, _rel in found] == ["calc.py"]


def test_a_single_file_seed_is_unchanged(tmp_path):
    """A file seed keeps its own basename, which must match interface.module."""
    from qikly.orchestrator import orchestrator as orch

    src = _write(str(tmp_path / "calc.py"), "X = 1\n")
    dest = tmp_path / "code" / TASK
    installed = orch.install_seed(str(src), str(dest), keep_directory_name=True)

    assert installed == [os.path.join(str(dest), "calc.py")]


def test_a_seeded_directory_keeps_its_subfolders(tmp_path):
    from qikly.orchestrator import orchestrator as orch

    src = tmp_path / "pkg"
    _write(str(src / "pricing.py"), "X = 1\n")
    _write(str(src / "utils" / "money.py"), "Y = 2\n")
    dest = tmp_path / "code" / TASK
    orch.install_seed(str(src), str(dest), keep_directory_name=True)

    assert os.path.isfile(str(dest / "pkg" / "utils" / "money.py"))


def test_a_seeded_package_is_not_reported_as_unwritable(tmp_path, monkeypatch):
    """
    The guard and the package seed have to agree. `mypkg/` is usually still
    sitting at the project root as well, so resolving the import against the
    project first would name the copy the task owns and repairs as a file it
    may not write, which is the opposite of true.
    """
    from qikly.orchestrator.write_scope import unwritable_imports

    root = tmp_path / "proj"
    _write(str(root / "mypkg" / "money.py"), "def to_cents(x):\n    return x\n")
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "mypkg" / "money.py"), "def to_cents(x):\n    return x\n")
    _write(str(code / "mypkg" / "pricing.py"), """
        from mypkg.money import to_cents


        def total(x):
            return to_cents(x)
    """)
    monkeypatch.chdir(str(root))
    assert unwritable_imports(str(code), str(root)) == []


# --- what the coding agent is given -----------------------------------------

def test_every_module_in_the_code_directory_reaches_the_agent(bench):
    """`load_codebase` walks the tree, so a helper is visible once seeded."""
    _write(os.path.join(bench["code"], "money.py"), "def to_cents(x):\n    return x\n")
    _write(os.path.join(bench["code"], "utils", "rounding.py"), "HALF_UP = 1\n")
    _module_under_test(bench, "def total(x):\n    return x\n")

    text = load_codebase(bench["code"])
    assert "def to_cents" in text
    assert "HALF_UP" in text
    assert "def total" in text


# --- a repair that spans two files ------------------------------------------

def test_one_diff_may_change_two_modules_at_once(tmp_path, monkeypatch):
    """
    PATCH already takes a list of targets, so a fix is not confined to one
    file once several are seeded. This is the half of multi-module repair
    that genuinely works today.
    """
    from qikly.agent_tools.apply_patch import apply_patch

    root = tmp_path / "proj"
    code = root / "outputs" / "agent_src" / "code" / TASK
    _write(str(code / "pricing.py"), "VALUE = 1\n")
    _write(str(code / "money.py"), "VALUE = 2\n")
    monkeypatch.chdir(str(root))

    diff = _write(str(root / "both.diff"), """
        --- a/outputs/agent_src/code/T/pricing.py
        +++ b/outputs/agent_src/code/T/pricing.py
        @@ -1 +1 @@
        -VALUE = 1
        +VALUE = 11
        --- a/outputs/agent_src/code/T/money.py
        +++ b/outputs/agent_src/code/T/money.py
        @@ -1 +1 @@
        -VALUE = 2
        +VALUE = 22
    """)
    apply_patch(diff)  # returns None, raises on failure
    assert "VALUE = 11" in open(str(code / "pricing.py"), encoding="utf-8").read()
    assert "VALUE = 22" in open(str(code / "money.py"), encoding="utf-8").read()


def test_a_diff_may_not_reach_outside_the_task_s_directory(tmp_path, monkeypatch):
    """The write scope this whole area rests on, pinned where it is enforced."""
    from qikly.agent_tools.apply_patch import apply_patch

    root = tmp_path / "proj"
    _write(str(root / "outputs" / "agent_src" / "code" / TASK / "pricing.py"), "VALUE = 1\n")
    _write(str(root / "helpers" / "money.py"), "VALUE = 2\n")
    monkeypatch.chdir(str(root))

    diff = _write(str(root / "outside.diff"), """
        --- a/helpers/money.py
        +++ b/helpers/money.py
        @@ -1 +1 @@
        -VALUE = 2
        +VALUE = 22
    """)
    with pytest.raises(RuntimeError) as raised:
        apply_patch(diff)
    assert "outside" in str(raised.value).lower()
    assert "VALUE = 2\n" == open(str(root / "helpers" / "money.py"), encoding="utf-8").read()
