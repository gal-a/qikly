"""
Modules made only of classes, which `--scaffold` used to refuse.

iniconfig and bidict are classes all the way down: `--score` raised questions
about them, then `--scaffold` said they had "no public top level functions"
and stopped, leaving the questions with nowhere to be answered. A class is
called as its constructor and its methods, so those are its interface.
"""
import yaml

from qikly import scaffold, score_questions, spec_draft


CLASSES = '''
"""Reads an ini file."""
from typing import overload


class Config:
    """The parsed file."""

    def __init__(self, path, data=None, *, encoding="utf-8", _sections=None):
        self.path = path

    @overload
    def get(self, section, name): ...

    def get(self, section, name, default=None):
        return default

    @property
    def sections(self) -> list:
        return []

    @staticmethod
    def parse(text, strict=False):
        return Config("x")

    @classmethod
    def empty(cls):
        return cls("x")

    def _helper(self):
        pass

    def __repr__(self):
        return "Config()"


class Section(dict):
    def lineof(self, name):
        return None


class _Hidden:
    def visible(self):
        pass
'''


def _write(tmp_path, text, name="config.py"):
    path = tmp_path / "pkg" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _lines(tmp_path, text, name="config.py"):
    path = _write(tmp_path, text, name)
    task, problem = scaffold.build_task(str(path), str(tmp_path), seed="existing")
    assert problem is None, problem
    return yaml.safe_load(task)["interface"]


def test_a_module_of_classes_is_scaffolded_with_constructors_and_methods(tmp_path):
    interface = _lines(tmp_path, CLASSES)
    assert interface["integration_functions"] == [
        "Config(path, data, encoding)",
        "Config.get(section, name, default)",
        "Config.sections -> list",
        "Config.parse(text, strict)",
        "Config.empty()",
        "Section(...)",
        "Section.lineof(name)",
    ]


def test_overload_stubs_private_names_and_dunders_are_left_out(tmp_path):
    listed = " ".join(_lines(tmp_path, CLASSES)["integration_functions"])
    assert listed.count("Config.get(") == 1, "one line per method, not per @overload"
    assert "_sections" not in listed and "_helper" not in listed
    assert "__repr__" not in listed and "_Hidden" not in listed and "visible" not in listed


def test_the_entrypoint_is_the_class_named_as_the_module(tmp_path):
    assert _lines(tmp_path, CLASSES)["system_entrypoint"] == "Config(path, data, encoding)"
    other = _lines(tmp_path, CLASSES, name="reader.py")["system_entrypoint"]
    assert other == "Config(path, data, encoding)", "else the class with the most methods"


def test_a_top_level_function_is_still_preferred_as_the_entrypoint(tmp_path):
    source = CLASSES + "\n\ndef run_config(path):\n    pass\n"
    assert _lines(tmp_path, source)["system_entrypoint"] == "run_config(path)"


def test_score_no_longer_sends_a_class_module_to_init(tmp_path):
    path = _write(tmp_path, CLASSES)
    assert score_questions._scaffoldable(str(path))


def test_starter_columns_read_the_constructor_and_methods():
    source = "class Rate:\n    def __init__(self, amount, rate):\n        pass\n" \
             "    def apply(self, discount):\n        pass\n"
    assert scaffold.starter_columns(source) == ["amount", "rate", "discount"]


def test_a_module_of_private_helpers_names_the_module_that_imports_it(tmp_path):
    _write(tmp_path, "def _wrapper(func):\n    return func\n", name="_cached.py")
    _write(tmp_path, "def cached(func):\n    from ._cached import _wrapper\n"
                     "    return _wrapper(func)\n", name="__init__.py")
    task, problem = scaffold.build_task(str(tmp_path / "pkg" / "_cached.py"), str(tmp_path))
    assert task is None
    assert "Tests reach it through __init__.py" in problem


def test_questions_name_a_method_with_its_class():
    questions = [{"function": "get", "line": 13, "question": "q"},
                 {"function": "__init__", "line": 9, "question": "q"},
                 {"function": "lineof", "line": 37, "question": "q"}]
    named = [q["function"] for q in spec_draft.in_classes(questions, CLASSES)]
    assert named == ["Config.get", "Config", "Section.lineof"]
    again = [q["function"] for q in spec_draft.in_classes(
        spec_draft.in_classes(questions, CLASSES), CLASSES)]
    assert again == named, "naming twice changes nothing"
    assert questions[0]["function"] == "get", "the saved questions are not changed"


# ------------------------------------------- found by running qikly on itself --

def test_the_class_named_as_the_module_wins_whatever_its_case_and_size(tmp_path):
    """iniconfig: IniConfig over SectionWrapper, though SectionWrapper has more methods."""
    source = ("class SectionWrapper:\n"
              "    def get(self, k):\n        pass\n"
              "    def items(self):\n        pass\n"
              "    def lineof(self, k):\n        pass\n\n"
              "class IniConfig:\n"
              "    def __init__(self, path):\n        pass\n")
    entry = _lines(tmp_path, source, name="iniconfig.py")["system_entrypoint"]
    assert entry == "IniConfig(path)", "matched as the module is named, ignoring case"


def test_used_by_reads_only_the_other_python_files(tmp_path):
    _write(tmp_path, "def _wrapper(f):\n    return f\n", name="_cached.py")
    (tmp_path / "pkg" / "README.md").write_text("from ._cached import _wrapper\n", encoding="utf-8")
    assert scaffold.used_by(str(tmp_path / "pkg" / "_cached.py")) == []


def test_a_commented_out_import_is_not_a_use(tmp_path):
    _write(tmp_path, "def _wrapper(f):\n    return f\n", name="_cached.py")
    _write(tmp_path, "# from ._cached import _wrapper\n\ndef cached(f):\n    return f\n",
           name="__init__.py")
    assert scaffold.used_by(str(tmp_path / "pkg" / "_cached.py")) == []
