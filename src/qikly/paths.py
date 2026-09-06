"""
Where "the project" is, and where input files come from.

Two separate questions, deliberately answered separately:

**Where outputs go, and where your own inputs live** -- the *project root*.
This is your working directory. Run outputs are written under it, and your
own task specs are read from `inputs_private/` inside it.

**Where the shipped defaults come from** -- `inputs_public/`, which lives
*inside this package*. It is not a sibling directory of your project, and
that is on purpose: package data has to live inside the package to travel in
a wheel, so this is the only layout where a `pip install` arrives with the
example tasks, agent definitions, and default settings already present. A
fresh install is runnable immediately, against the same defaults and
producing the same outputs as a git clone.

## Resolution order for the project root, first match wins

  1. ``$QIKLY_PROJECT_ROOT``, if set. Explicit beats inferred, and it gives CI
     and wrapper scripts a way to be unambiguous.
  2. The working directory, or the nearest ancestor of it, containing
     ``inputs_private/``. This is the normal installed case: your project
     directory, whatever it's called and wherever it is.
  3. The nearest ancestor of *this file* containing both ``pyproject.toml``
     and ``qikly/`` -- the git-clone case, so running from a
     subdirectory of a clone still finds the repo root. Installed into
     site-packages this never matches, which is the intent.
  4. The working directory. A fresh install with no ``inputs_private/`` yet
     still runs against the shipped defaults, writing outputs where you
     stand rather than refusing to start.

## Resolution order for an input file, first match wins

  1. ``<project root>/<inputs_dir>/<relative path>`` -- your override.
     ``<inputs_dir>`` is ``inputs.dir`` in settings.yaml, default
     ``inputs_private``.
  2. ``<package>/inputs_public/<relative path>`` -- the shipped default.

Per *file*, not per directory. Dropping one task spec into
``inputs_private/config/tasks/`` overrides exactly that task and leaves the
agent definitions, knowledge files, and every other default in place. You
never have to copy a tree you didn't want to change.
"""
import os

ENV_VAR = "QIKLY_PROJECT_ROOT"
PRIVATE_MARKER = "inputs_private"
DEFAULT_PRIVATE_DIR = "inputs_private"

# inputs_public/ sits next to this file, inside the package.
PUBLIC_INPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inputs_public")


def _walk_up(start, predicate):
    """Nearest directory at or above start satisfying predicate, else None."""
    current = os.path.abspath(start)
    while True:
        if predicate(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _is_source_checkout(directory):
    return os.path.isfile(os.path.join(directory, "pyproject.toml")) and os.path.isdir(
        os.path.join(directory, "src", "qikly")
    )


def project_root():
    override = os.environ.get(ENV_VAR)
    if override:
        resolved = os.path.abspath(os.path.expanduser(override))
        if not os.path.isdir(resolved):
            raise RuntimeError(
                f"{ENV_VAR} is set to {resolved}, which is not a directory. "
                "Point it at a project directory, or unset it."
            )
        return resolved

    from_cwd = _walk_up(os.getcwd(), lambda d: os.path.isdir(os.path.join(d, PRIVATE_MARKER)))
    if from_cwd:
        return from_cwd

    from_source = _walk_up(os.path.dirname(os.path.abspath(__file__)), _is_source_checkout)
    if from_source:
        return from_source

    return os.getcwd()


def chdir_to_project_root():
    """
    What entry-point modules call at import time. Returns the root it moved to,
    so a caller that wants to log or assert on it doesn't have to ask twice.
    """
    root = project_root()
    os.chdir(root)
    return root


def private_inputs_dir():
    """
    The configured private inputs directory name. Read from settings rather
    than hardcoded, but resolved without importing the settings loader --
    that module reads *its* settings file through this one, and a cycle here
    would be a startup crash rather than a subtle bug.
    """
    import yaml

    default_settings = os.path.join(PUBLIC_INPUTS_DIR, "config", "settings.yaml")
    try:
        with open(default_settings, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return DEFAULT_PRIVATE_DIR
    return ((loaded.get("inputs") or {}).get("dir")) or DEFAULT_PRIVATE_DIR


def resolve_input(relative_path, root=None):
    """
    Absolute path to an input file: your override if you have one, else the
    shipped default. Returns the public path even when neither exists, so the
    resulting FileNotFoundError names the file the caller actually asked for.

    `relative_path` is relative to an inputs directory, e.g.
    "config/tasks/ETL_ADDRESS.yaml" or "agent_defs/code_agent.md".
    """
    relative_path = relative_path.replace("/", os.sep)
    base = root if root is not None else project_root()
    private = os.path.join(base, private_inputs_dir(), relative_path)
    if os.path.exists(private):
        return private
    return os.path.join(PUBLIC_INPUTS_DIR, relative_path)


def private_input_path(relative_path, root=None):
    """
    Absolute path to an input file *for writing*, always inside
    inputs_private/, creating the parent directory. Never returns a path
    inside the package.

    Reads fall back to the bundled defaults; writes must not. The two places
    that write a task config -- `--generate-criteria` filling in a missing
    acceptance_criteria, and the refinement loop's scratch DRAFT task --
    would otherwise resolve a bundled example to its packaged location and
    try to write into site-packages: read-only on a system install, and a
    modification to every other project on the machine when it isn't.
    Writing the override into your own project is both safer and the
    behavior you'd want anyway.
    """
    relative_path = relative_path.replace("/", os.sep)
    base = root if root is not None else project_root()
    path = os.path.join(base, private_inputs_dir(), relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def ensure_task_data(task_id, root=None):
    """
    Make sure this task's fixture CSVs exist at `<inputs_dir>/data/<task_id>/`
    inside the project directory -- the same inputs_private/ that holds your
    task and prompt overrides -- copying the bundled ones there if they
    aren't. Returns the directory.

    There is deliberately only one input directory in your project. An
    earlier version materialised fixtures into a separate top-level
    `inputs/`, which meant three input locations to reason about
    (inputs_public, inputs_private, inputs) when two is the whole idea.

    Why copy rather than resolve: those paths appear in the task spec as
    literal strings (`inputs_private/data/ETL_ADDRESS/input_01.csv`), handed to the
    model, and opened by the *generated code* relative to its working
    directory. The generated program has no access to this module and no way
    to ask where the package lives, so the file has to actually be there.
    Copying is also what keeps a fresh install's output identical to a
    clone's rather than merely equivalent.

    Never overwrites: once the file exists it is yours, whether you edited a
    bundled fixture or wrote your own from scratch.
    """
    import shutil

    base = root if root is not None else project_root()
    dest = os.path.join(base, private_inputs_dir(), "data", task_id)
    source = os.path.join(PUBLIC_INPUTS_DIR, "data", task_id)
    if not os.path.isdir(source):
        return dest
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(source):
        src_file = os.path.join(source, name)
        dest_file = os.path.join(dest, name)
        if os.path.isfile(src_file) and not os.path.exists(dest_file):
            shutil.copy2(src_file, dest_file)
    return dest


def list_input_dir(relative_dir, root=None):
    """
    Every filename in `relative_dir` across both inputs directories, private
    shadowing public on an exact name match. Sorted, so task discovery order
    doesn't depend on the filesystem.

    Used for discovering task specs: `qikly-all` must run your own tasks and
    the bundled examples alike, and must run *your* ETL_ADDRESS.yaml rather
    than both if you have written one.
    """
    base = root if root is not None else project_root()
    seen = {}
    for directory in (
        os.path.join(PUBLIC_INPUTS_DIR, relative_dir.replace("/", os.sep)),
        os.path.join(base, private_inputs_dir(), relative_dir.replace("/", os.sep)),
    ):
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            full = os.path.join(directory, name)
            if os.path.isfile(full):
                seen[name] = full
    return [seen[name] for name in sorted(seen)]
