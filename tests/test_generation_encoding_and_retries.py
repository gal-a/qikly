"""
Generated test files on Windows, and what a retry is told.

Found on the twenty-library sweep of 2026-10-22. price-parser's generated
tests held a `€`, written with the locale's encoding, cp1252, as the byte 0x80:
a file pytest cannot parse. Every attempt of all three seeds then reported
"the module could not be imported", and the coding agent spent ten attempts a
run on a file it may not touch. humanize's run died writing a `μ`. And
inflect's run ended after three invalid generated files, each retry given a
new seed and no reason, so nothing told the model what it got wrong.
"""
import ast
import glob
import os

from qikly.orchestrator import orchestrator as orch

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "qikly")


def _quiet(monkeypatch, generator):
    monkeypatch.setattr(orch, "TEST_GENERATORS",
                        {"integration": (generator, "test_integration.py")})
    monkeypatch.setattr(orch, "criteria_per_batch", lambda: 0)
    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)


def test_a_generated_test_with_non_ascii_text_is_written_as_utf8(tmp_path, monkeypatch):
    source = ("def test_price():\n"
              "    assert '€1.234,56'.startswith('€')\n"
              "    assert 'μs' == 'μs'\n")
    _quiet(monkeypatch, lambda task_id, seed=None, criteria=None: source)
    path = orch.generate_and_write_tests("integration", str(tmp_path), "CALC_TAX", seed=1)
    with open(path, "rb") as handle:
        raw = handle.read()
    assert raw.decode("utf-8") == source, "utf-8 on disk, whatever the locale"
    compile(raw, path, "exec")


def test_every_text_file_qikly_opens_names_its_encoding():
    """
    The locale's encoding is cp1252 on Windows. A file opened without one
    reads or writes any character outside it wrongly, and a task file, a test
    or a report can hold any character a README or a test output does.
    """
    unnamed = []
    for path in glob.glob(os.path.join(SRC, "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "open"):
                continue
            mode = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "mode"), None)
            mode = mode.value if isinstance(mode, ast.Constant) else "r"
            if (isinstance(mode, str) and "b" not in mode
                    and not any(k.arg == "encoding" for k in node.keywords)):
                unnamed.append(f"{os.path.relpath(path, SRC)}:{node.lineno}")
    assert not unnamed, "text-mode open() with no encoding: " + ", ".join(unnamed)


def test_a_retry_is_told_why_the_last_draft_was_refused(monkeypatch):
    told = []

    def generator(task_id, seed=None, criteria=None, guidance=None):
        told.append(guidance)
        return "def test_x(:\n" if len(told) == 1 else "def test_x():\n    assert True\n"

    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)
    source = orch._generate_one("integration", generator, "CALC_TAX", 1, None, 1)
    assert "assert True" in source
    assert told[0] is None, "the first call is told nothing"
    assert "not valid Python" in told[1] and "rejected" in told[1]


def test_a_retry_keeps_the_suite_checks_guidance_too(monkeypatch):
    told = []

    def generator(task_id, seed=None, criteria=None, guidance=None):
        told.append(guidance)
        return "x = 1\n" if len(told) == 1 else "def test_x():\n    assert True\n"

    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)
    orch._generate_one("integration", generator, "CALC_TAX", 1, None, 1,
                       guidance="Cover criterion 2.")
    assert told[0] == "Cover criterion 2."
    assert told[1].startswith("Cover criterion 2.") and "no test_ functions" in told[1]


def test_a_generator_without_guidance_still_retries(monkeypatch):
    calls = []

    def generator(task_id, seed=None, criteria=None):
        calls.append(seed)
        return "def test_x(:\n" if len(calls) == 1 else "def test_x():\n    assert True\n"

    monkeypatch.setattr(orch, "log_transaction", lambda *a, **k: None)
    assert "assert True" in orch._generate_one("integration", generator, "CALC_TAX", 1, None, 1)
    assert len(calls) == 2
