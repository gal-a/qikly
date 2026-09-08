"""
The human gate, and retrieval within a large file.

Two capabilities that answer the two questions this tool gets asked most often
by people who are not going to run it on ten example tasks: "does it apply
changes without asking" and "what happens when the file is five thousand lines".

Both defaults are unchanged. Patches still apply, and files under the threshold
are still loaded whole. What changed is that there is now a third option in
each case, where before there was none.
"""
import os

import pytest

from qikly import approval
from qikly.agent_api.code_loader.code_loader import load_target_files
from qikly.agent_api.code_loader.excerpt import (DEFAULT_MAX_CHARS,
                                                 excerpt_source,
                                                 relevant_names)


# ============================================================ approval ======

@pytest.fixture(autouse=True)
def _default_mode(monkeypatch):
    monkeypatch.delenv(approval.ENV_MODE, raising=False)


def test_the_default_is_unchanged_and_applies_everything():
    """
    Nothing about the existing behaviour moves. An unattended loop that stopped
    to ask would not be an unattended loop, and a run writes only inside its
    own output directory anyway.
    """
    assert approval.mode() == approval.APPLY
    assert approval.decide("--- a\n+++ b\n", "f1", "unit", 1) == (True, None)


def test_a_dry_run_applies_nothing_and_asks_nothing(monkeypatch):
    """
    It has to complete unattended. A dry run that blocked on a prompt would be
    useless in the place it is most wanted, which is a pipeline.
    """
    monkeypatch.setenv(approval.ENV_MODE, approval.DRY_RUN)
    approved, why = approval.decide("--- a\n+++ b\n", "f1", "unit", 1)
    assert approved is False
    assert "dry-run" in why


def test_review_applies_on_an_explicit_yes(monkeypatch, capsys):
    monkeypatch.setenv(approval.ENV_MODE, approval.REVIEW)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert approval.decide("--- a\n+++ b\n+new line\n", "f1", "unit", 1)[0] is True


def test_review_declines_on_anything_else(monkeypatch):
    monkeypatch.setenv(approval.ENV_MODE, approval.REVIEW)
    for answer in ("n", "", "maybe", "Y E S"):
        monkeypatch.setattr("builtins.input", lambda *a, _a=answer: _a)
        assert approval.decide("--- a\n+++ b\n", "f1", "unit", 1)[0] is False, answer


def test_silence_is_not_consent(monkeypatch):
    """
    No terminal behind the process, or a reviewer who walked away. Reading
    either as approval would turn a safety feature into a worse version of the
    default, and the person who chose review is exactly the person who would
    not forgive that.
    """
    monkeypatch.setenv(approval.ENV_MODE, approval.REVIEW)

    def walked_away(*a):
        raise EOFError

    monkeypatch.setattr("builtins.input", walked_away)
    approved, why = approval.decide("--- a\n+++ b\n", "f1", "unit", 1)
    assert approved is False
    assert "no answer" in why


def test_an_unknown_mode_falls_back_to_applying(monkeypatch):
    """
    A typo in an environment variable must not silently stop a run from
    converging. The failure would look like the tool being broken.
    """
    monkeypatch.setenv(approval.ENV_MODE, "revview")
    assert approval.mode() == approval.APPLY


def test_the_review_screen_leads_with_the_counts(monkeypatch, capsys):
    """
    A reviewer decides from the shape before reading a word of the diff. The
    numbers go first, and to stderr, so a redirected stdout still shows them.
    """
    monkeypatch.setenv(approval.ENV_MODE, approval.REVIEW)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    patch = ("--- a/x.py\n+++ b/x.py\n@@ -1 +1,2 @@\n" "-old\n+new\n+also new\n")
    approval.decide(patch, "f1", "unit", 3)
    err = capsys.readouterr().err
    assert "+2 / -1" in err
    assert "b/x.py" in err


def test_a_declined_patch_is_recorded_rather_than_forgotten():
    """
    A rejection is the one piece of evidence no test can produce: a human
    looked at a change and judged it wrong. The orchestrator logs it and keeps
    the diff, so a steered run can be told from an unsteered one afterwards.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator)
    assert "patch_not_applied" in source
    assert "approval.decide(" in source


# ============================================================= excerpt ======

BIG = '''import os
import csv

RATE = 0.2

def helper(a, b):
    """Not relevant to this failure."""
    return a + b

def compute_tax(rows):
    total = 0
    for row in rows:
        total += float(row["amount"]) * RATE
    return total

class Loader:
    def read(self, path):
        with open(path) as handle:
            return list(csv.DictReader(handle))

    def write(self, rows, path):
        pass
'''


def test_a_small_file_is_still_loaded_whole(tmp_path):
    """
    The threshold matters as much as the excerpting. Whole-file context is
    strictly better when it is affordable, and collapsing a two hundred line
    module costs clarity to save nothing.
    """
    path = tmp_path / "small.py"
    path.write_text(BIG, encoding="utf-8")
    from qikly.agent_api.code_loader.excerpt import excerpt_file

    assert excerpt_file(str(path), {"compute_tax"}) == BIG


def test_the_relevant_function_survives_verbatim():
    out = excerpt_source(BIG, {"compute_tax"}, path="etl.py")
    assert 'float(row["amount"]) * RATE' in out


def test_everything_else_collapses_to_a_signature():
    out = excerpt_source(BIG, {"compute_tax"}, path="etl.py")
    assert "def helper(a, b): ..." in out
    assert "return a + b" not in out


def test_imports_and_module_constants_are_always_kept():
    """
    A patch that cannot see the imports reintroduces one that already exists,
    and a patch that cannot see a constant hardcodes its value. Both are cheap
    to keep and expensive to lose.
    """
    out = excerpt_source(BIG, {"compute_tax"}, path="etl.py")
    assert "import csv" in out
    assert "RATE = 0.2" in out


def test_a_wanted_method_keeps_its_class_header():
    """
    An indented diff needs somewhere to anchor. A method shown without its
    class is a hunk that cannot be placed.
    """
    out = excerpt_source(BIG, {"write"}, path="etl.py")
    assert "class Loader:" in out
    assert "def write(self, rows, path):" in out
    assert "DictReader" not in out, "the sibling method should have collapsed"


def test_elided_ranges_are_named_so_line_numbers_stay_real():
    """
    The excerpt is context for a unified diff, and a diff carries line numbers.
    Silently renumbering would produce patches that do not apply, which is a
    failure that looks like the model being bad at diffs.
    """
    out = excerpt_source(BIG, {"compute_tax"}, path="etl.py")
    assert "lines 6-8 of etl.py" in out


def test_an_unparseable_file_is_shown_in_full():
    """
    A file the agent is part way through writing is often not valid Python, and
    that is exactly when it most needs to be seen whole: excerpting it would
    hide the syntax error the next patch exists to fix.
    """
    broken = "def f(:\n    pass\n"
    assert excerpt_source(broken, {"anything"}, path="x.py") == broken


def test_a_file_with_nothing_to_elide_is_returned_unchanged():
    source = "import os\n\ndef only(x):\n    return x\n"
    assert excerpt_source(source, {"only"}, path="x.py") == source


def test_names_are_taken_from_the_fix_text():
    """
    The retrieval query is the FIX and the failure output, which already name
    the functions. That is why this needs no embedding index and no model call:
    the question was answered before it was asked.
    """
    names = relevant_names("Change compute_tax so it rounds with Decimal.")
    assert "compute_tax" in names and "Decimal" in names


def test_loading_without_context_never_excerpts(tmp_path):
    """
    No context means no names, and matching nothing would collapse every
    definition in the file. Loading whole is the safe reading of "I was not
    told what matters".
    """
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    big = code_dir / "m.py"
    big.write_text(BIG + "\n# pad\n" * 4000, encoding="utf-8")

    loaded = load_target_files(str(code_dir), [str(big)])
    assert "return a + b" in loaded, "a file loaded without context was excerpted"


def test_loading_with_context_excerpts_a_large_file(tmp_path):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    big = code_dir / "m.py"
    big.write_text(BIG + "\n# pad\n" * 4000, encoding="utf-8")
    assert len(big.read_text(encoding="utf-8")) > DEFAULT_MAX_CHARS

    loaded = load_target_files(str(code_dir), [str(big)],
                              context="compute_tax rounds wrongly")
    assert 'float(row["amount"])' in loaded, "the relevant function was dropped"
    assert "def helper(a, b): ..." in loaded, "the irrelevant one was not collapsed"


def test_the_threshold_is_overridable(tmp_path, monkeypatch):
    """A larger context window should be usable without editing the source."""
    from qikly.agent_api.code_loader import excerpt

    monkeypatch.setenv(excerpt.ENV_MAX_CHARS, "50")
    assert excerpt.max_chars() == 50
    monkeypatch.setenv(excerpt.ENV_MAX_CHARS, "not a number")
    assert excerpt.max_chars() == DEFAULT_MAX_CHARS
