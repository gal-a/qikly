"""
Bundled task names follow one convention and can never collide.

Users are encouraged to contribute their own tasks, so the list of names has to
stay unambiguous as it grows. A collision is silent rather than loud: tasks
resolve by name, a Windows or macOS checkout cannot hold two files whose names
differ only in case, and a user's own task with the same id replaces the
bundled one without a word. CONTRIBUTING.md states these rules for people; this
states them for the build.
"""
import os
import re

import yaml

from qikly.scaffold import VERIFY_SUFFIX

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "src", "qikly", "inputs_public")
TASKS = os.path.join(PUBLIC, "config", "tasks")

# FAMILY_SUBJECT: upper case words joined by single underscores, at least two.
NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
MAX_LENGTH = 32


def _ids():
    return sorted(name[:-5] for name in os.listdir(TASKS) if name.endswith(".yaml"))


def _folders(kind):
    path = os.path.join(PUBLIC, kind)
    return sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))


def test_every_bundled_task_id_follows_the_naming_convention():
    bad = [t for t in _ids() if not NAME.match(t) or len(t) > MAX_LENGTH]
    assert not bad, ("these task ids are not FAMILY_SUBJECT in upper case, at most %d "
                     "characters: %s. See Naming in CONTRIBUTING.md." % (MAX_LENGTH, bad))


def test_no_bundled_task_id_ends_in_the_scaffold_suffix():
    """`qikly --scaffold` names the task that verifies existing code <NAME>_VERIFY."""
    bad = [t for t in _ids() if t.endswith(VERIFY_SUFFIX)]
    assert not bad, "%s is reserved for scaffolded tasks: %s" % (VERIFY_SUFFIX, bad)


def test_no_two_bundled_task_ids_differ_only_in_case():
    seen = {}
    for task_id in _ids():
        seen.setdefault(task_id.lower(), []).append(task_id)
    clashes = [names for names in seen.values() if len(names) > 1]
    assert not clashes, "task ids that collide on a case-insensitive filesystem: %s" % clashes


def test_each_bundled_task_file_declares_its_own_name():
    wrong = {}
    for task_id in _ids():
        with open(os.path.join(TASKS, task_id + ".yaml"), encoding="utf-8") as handle:
            declared = (yaml.safe_load(handle) or {}).get("task_id")
        if declared != task_id:
            wrong[task_id] = declared
    assert not wrong, "task_id inside the file differs from the filename: %s" % wrong


def test_every_task_has_its_data_and_no_folder_is_left_behind():
    """A rename that moves the task file but not its folders leaves an orphan."""
    ids = set(_ids())
    data = set(_folders("data"))
    assert ids == data, "tasks without data: %s; data without a task: %s" % (
        sorted(ids - data), sorted(data - ids))
    orphans = sorted(set(_folders("reference")) - ids)
    assert not orphans, "reference implementations without a task: %s" % orphans
