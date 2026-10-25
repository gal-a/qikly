"""
What the audit of 0.6.1 found, each pinned so it cannot come back.

The audit was run before release on everything since 0.6.0: the spec agent,
classes-only modules, the sweep fixes, and 0.6.0's numbered answers. Each test
here reproduces one of its findings and fails on the code before the fix.
"""
import json
import os

import yaml

from qikly import cli, scaffold, score_questions, spec_draft, take_tests
from qikly.mutation_score import setup_advice


def _module(tmp_path, source, readme=None, name="m.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    if readme is not None:
        (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return str(path)


def _draft(tmp_path, reply, questions=None, source="def f(x):\n    return x\n",
           readme="f doubles a number. Doubles x and returns the result as an int.\n"):
    module = _module(tmp_path, source, readme)
    questions = questions or [{"question": "What should f(2) do?", "function": "f"}]
    return spec_draft.draft(module, str(tmp_path), questions,
                            call=lambda role, prompt, seed=None: json.dumps(reply))


# ------------------------------------------------- criteria keep their text --

def test_a_numbered_option_keeps_its_spaces():
    question = {"question": "What should pad('ab') do?", "path": "m.py", "function": "pad",
                "hint_prompt": "What should pad('ab') do?",
                "hint_options": [{"criterion": "pad('ab') returns 'ab      |'", "note": "", "now": True},
                                 {"criterion": "pad('ab') returns 'ab |'", "note": "", "now": False}]}
    block = score_questions.yaml_block([question])
    assert "'ab      |'" in block and "'ab |'" in block


def test_every_line_break_yaml_knows_is_escaped_in_a_criterion():
    for brk in ("\r", "\x85", " ", " ", "\n"):
        text = spec_draft.criterion_text(f"lines('a{brk}b') returns ['a', 'b']")
        loaded = yaml.safe_load('- "' + text.replace("\\", "\\\\").replace('"', '\\"') + '"')
        assert len(loaded) == 1 and brk not in loaded[0], repr(brk)


# ------------------------------------------------------- the requirements line --

def test_drafted_requirements_that_give_away_a_criterion_are_not_used(tmp_path):
    reply = {"requirements": "Doubles numbers; f(2) returns 4.",
             "answers": [{"question": 1, "criterion": "f(2) returns 4", "source": "purpose",
                          "quote": "", "check": True}]}
    drafted = _draft(tmp_path, reply)
    assert drafted["requirements"] is None and drafted["requirements_dropped"]


def test_drafted_requirements_that_keep_to_the_purpose_are_used(tmp_path):
    reply = {"requirements": "Doubles numbers given as ints.",
             "answers": [{"question": 1, "criterion": "f(2) returns 4", "source": "purpose",
                          "quote": "", "check": True}]}
    drafted = _draft(tmp_path, reply)
    assert drafted["requirements"] == "Doubles numbers given as ints."
    assert not drafted["requirements_dropped"]


# ------------------------------------------------------------------ quotes --

def test_a_quote_has_to_say_something():
    doc = spec_draft._squash("A slug is made from the text. Slug length is configurable.")
    for quote in ("slug", "a", "text", "Slug ... configurable"):
        assert not spec_draft.quoted(quote, doc), quote
    assert spec_draft.quoted("A slug is made from the text", doc)


def test_a_signature_is_not_documentation_to_quote(tmp_path):
    reply = {"requirements": None,
             "answers": [{"question": 1, "criterion": "f(1, strict=True) raises ValueError",
                          "source": "docs", "quote": "def f(x, strict=False):", "check": False}]}
    drafted = _draft(tmp_path, reply, source="def f(x, strict=False):\n    return x\n")
    assert drafted["answers"] == {} and drafted["dropped"] == 1


def test_an_answer_with_another_result_than_its_quoted_example_is_marked_check():
    names = {"slugify"}
    assert spec_draft.other_function("slugify('one two') == 'one-two'",
                                     "slugify('one two') returns 'one_two'", names)
    assert spec_draft.other_function("slugify('one two') == 'one-two'",
                                     'slugify("one two") returns "one-two"', names) is None


def test_quote_marks_alone_are_not_other_arguments():
    assert spec_draft.other_function('>>> parse_number("12,34")',
                                     "parse_number('12,34') returns Decimal('12.34')",
                                     {"parse_number"}) is None


def test_a_docs_answer_the_agent_flagged_is_marked_check_in_the_file():
    drafted = {"requirements": None, "dropped": 0, "answers": {1: {
        "criterion": "f(2) returns 4", "source": "docs", "quote": "Doubles x.", "check": True,
        "why": None}}}
    out, _, check = spec_draft.apply('acceptance_criteria:\n  - "TODO: your answer"\n', drafted)
    assert check == 1 and "#? CHECK:" in out


# ----------------------------------------------------------- what is drafted --

def test_only_the_docstrings_the_agent_sees_count_as_documentation(tmp_path):
    source = ('def _norm(x):\n    """' + "Normalises the code to lower case without spaces. " * 3
              + '"""\n    return x\n\ndef label(code):\n    return _norm(code)\n')
    module = _module(tmp_path, source)
    assert len(spec_draft.documentation(module, str(tmp_path))) < spec_draft.MIN_DOCS


def test_a_one_line_def_names_the_parameter_whose_default_changed():
    source = "def parse(path, strict=False):\n    return path\n"
    q = [{"function": "parse", "line": 1, "code": "def parse(path, strict=False):",
          "change": "bool False -> True, line 1", "question": "this False flipped"}]
    assert spec_draft.with_parameters(q, source)[0]["parameter"] == "strict"


def test_an_answer_to_a_question_nobody_asked_is_dropped(tmp_path):
    reply = {"requirements": None, "answers": [
        {"question": 1, "criterion": "f(2) returns 4", "source": "purpose", "quote": "", "check": True},
        {"question": 7, "criterion": "f(9) returns 99", "source": "purpose", "quote": "", "check": True}]}
    assert set(_draft(tmp_path, reply)["answers"]) == {1}


def test_a_reply_with_braces_after_the_json_is_still_read(tmp_path):
    reply = {"requirements": None, "answers": [
        {"question": 1, "criterion": "f(2) returns 4", "source": "purpose", "quote": "", "check": True}]}
    module = _module(tmp_path, "def f(x):\n    return x\n", "f doubles a number given to it.\n")
    text = json.dumps(reply) + "\nNote: sets like {1, 2} are not used."
    drafted = spec_draft.draft(module, str(tmp_path),
                               [{"question": "What should f(2) do?", "function": "f"}],
                               call=lambda role, prompt, seed=None: text)
    assert drafted and set(drafted["answers"]) == {1}


def test_a_readme_link_is_followed_only_to_documentation_inside_the_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "secret.py").write_text("def f():\n    return 'BODY'\n", encoding="utf-8")
    (project / "README.md").write_text("secret.py", encoding="utf-8")
    module = project / "m.py"
    module.write_text("def g():\n    pass\n", encoding="utf-8")
    assert "BODY" not in spec_draft.readme_text(str(module), str(project))
    (tmp_path / "outside.txt").write_text("OUTSIDE text", encoding="utf-8")
    (project / "README.md").write_text("../outside.txt", encoding="utf-8")
    assert "OUTSIDE" not in spec_draft.readme_text(str(module), str(project))


# ------------------------------------------------------------ the scaffold --

def test_a_dataclass_constructor_takes_its_fields(tmp_path):
    source = ("from dataclasses import dataclass\n\n@dataclass\nclass Point:\n"
              "    x: float\n    y: float = 0.0\n\n    def norm(self) -> float:\n        return 0.0\n")
    path = tmp_path / "pkg" / "point.py"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    text, problem = scaffold.build_task(str(path), str(tmp_path), seed="existing")
    assert problem is None
    assert yaml.safe_load(text)["interface"]["system_entrypoint"] == "Point(x: float, y: float)"


def test_a_signature_with_a_double_quote_still_makes_valid_yaml(tmp_path):
    source = ("class Point:\n    def label(self, fmt: 'Literal[\"x\"]') -> str:\n        return ''\n")
    path = tmp_path / "pkg" / "point.py"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    text, problem = scaffold.build_task(str(path), str(tmp_path), seed="existing")
    assert problem is None
    assert 'Literal["x"]' in " ".join(yaml.safe_load(text)["interface"]["integration_functions"])


# ----------------------------------------------------------- take-tests ----

def test_criterion_numbers_follow_the_yaml_whatever_the_items_look_like(tmp_path):
    tasks = tmp_path / "inputs_private" / "config" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T.yaml").write_text(
        "task_id: T\nacceptance_criteria:\n"
        "  - >\n    a criterion the user wrote\n    over two lines\n"
        "  - \"it's fine\"\n"
        "  #? Drafted from your documentation: \"f doubles x and returns it\"\n"
        "  - \"f(1) returns 2\"\n"
        "  - \"f(2) returns 3\\\\\"\n"
        "  #? CHECK: drafted from the module's purpose; nothing written decides it.\n"
        "  - \"f(3) returns 4\"\n", encoding="utf-8")
    got = take_tests.criteria_with_origin(str(tmp_path), "T")
    assert [o for _, o in got] == ["you", "you", "docs", "you", "check"]
    assert got[2][0] == "f(1) returns 2" and got[4][0] == "f(3) returns 4"


# ------------------------------------------------------------- the advice --

def test_a_syntax_error_is_reported_as_one_first():
    class Target:
        suites = ["tests"]
    lines = setup_advice(["E   SyntaxError: invalid syntax"], Target())
    text = "\n".join(lines)
    assert "fix the syntax error" in text and "check the Python version" not in text


# ---- the second audit, of the fixes from the young-library sweep ----------

def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_src_package_with_a_stdlib_named_module_still_scores(tmp_path):
    # A project that imports itself as src.app and keeps src/logging.py: the
    # extra src root put that file ahead of the real logging module.
    from qikly import mutation_score as ms
    _write(tmp_path, "pyproject.toml", "")
    _write(tmp_path, "src/__init__.py", "")
    _write(tmp_path, "src/logging.py", "def note(m):\n    return m\n")
    _write(tmp_path, "src/app/__init__.py", "")
    code = _write(tmp_path, "src/app/calc.py", "from src.logging import note\n\ndef rate(x):\n"
                  "    note('r')\n    return x if x <= 100 else 100\n")
    _write(tmp_path, "tests/test_calc.py", "from src.app.calc import rate\n\ndef test_r():\n"
           "    assert rate(150) == 100\n    assert rate(5) == 5\n")
    target = ms.from_paths(str(code), str(tmp_path / "tests"))
    assert ("app", "src") not in ms._import_roots(target)
    assert ms.score(target, mutants=2, seed=1)["baseline"] is True


def test_any_async_test_is_refused_even_beside_sync_ones():
    from qikly.orchestrator.orchestrator import _validate_generated_tests
    mixed = ("import asyncio\nfrom m import f\n\ndef test_a():\n    assert asyncio.run(f())\n\n"
             "async def test_b():\n    assert await f()\n")
    method = "from m import f\n\nclass TestX:\n    async def test_c(self):\n        assert await f()\n"
    for source in (mixed, method):
        said = _validate_generated_tests(source, "unit")
        assert said and "asyncio.run" in said and "skips" not in said.split(":")[0]


def test_a_factory_made_test_still_counts_when_nothing_else_does(tmp_path):
    from qikly import start
    _write(tmp_path, "pyproject.toml", "")
    _write(tmp_path, "pkg/__init__.py", "")
    code = _write(tmp_path, "pkg/calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/test_made.py", "from pkg.calc import add\n\ndef _make(n):\n"
           "    def t():\n        assert add(n, 0) == n\n    return t\n\ntest_one = _make(1)\n")
    assert start.auto_tests(str(code), str(tmp_path)) == str(tmp_path / "tests" / "test_made.py")


def test_copied_tests_left_out_of_the_score_are_named(tmp_path):
    import subprocess
    import sys
    _write(tmp_path, "pyproject.toml", "")
    _write(tmp_path, "src/ini/__init__.py", "def parse(s):\n    return s if s else None\n")
    _write(tmp_path, "testing/test_ini.py", "from ini import parse\n\ndef test_p():\n"
           "    assert parse('a') == 'a'\n")
    _write(tmp_path, "tests/qikly_generated/ini_verify/unit/test_unit.py",
           "from ini import parse\n\ndef test_u():\n    assert parse('a') == 'a'\n")
    out = subprocess.run([sys.executable, "-m", "qikly", "--score", "src/ini/__init__.py",
                          "--score-mutants", "1", "--score-seed", "0"], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=600, env=dict(os.environ, PYTHONPATH=os.pathsep.join(
                             [os.path.join(os.path.dirname(__file__), "..", "src"), str(tmp_path / "src")])))
    assert "copied in is not under it" in out.stdout, out.stdout + out.stderr


def test_signatures_of_async_context_managers_properties_and_aliases():
    from qikly import scaffold
    src = ("from contextlib import asynccontextmanager\nfrom typing import TypeAlias\n\n"
           "@asynccontextmanager\nasync def session():\n    yield 1\n\n"
           "class K:\n    @property\n    async def val(self):\n        return 1\n\n"
           "class _EmailStr(str):\n    pass\n\nEmailStr: TypeAlias = _EmailStr\n\n"
           "def _impl(x):\n    return x\n\nA = B = _impl\nC = A\n\n"
           "def parse(x, y):\n    return x\n\nparse = _impl\n")
    sigs = [scaffold._signature(f) for f in scaffold.read_interface(src)]
    assert "session()  (a context manager: use it in an async with statement)" in sigs
    assert "async K.val" in sigs
    assert {"EmailStr()", "A(x)", "B(x)", "C(x)"} <= set(sigs) or \
        {"A(x)", "B(x)", "C(x)"} <= set(sigs) and any(s.startswith("EmailStr") for s in sigs)
    assert [s for s in sigs if s.startswith("parse")] == ["parse(x)"]
