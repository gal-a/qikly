"""
Four things that would fail on somebody else's machine, not on this one.

Each was checked against reality rather than reasoned about, and the results
split evenly. Two were already safe and are pinned here so they stay safe. Two
were real and are fixed.

**Timestamp collisions: already safe.** 151 of 272 run timestamps in this
project's history are shared by more than one task, up to 14 at once, which
looks alarming until you notice that task_id is in every path. Across 1,453
task-and-timestamp pairs there are zero collisions that would have overwritten
anything.

**Braces in a criterion: already safe.** `str.format` does not recurse into the
values it substitutes, so a criterion containing `{task}` reaches the model as
written rather than raising KeyError or interpolating something else.

**The missing `patch` binary: fixed.** The message said what was wrong and not
what to do about it, on the first thing a user on a fresh machine hits.

**A non-GNU `patch`: fixed.** Apple and BSD ship an implementation that rejects
`--fuzz`, and the resulting error was indistinguishable from an ordinary hunk
failure. Every attempt in the run would then be spent regenerating diffs that
could never apply, for a reason nothing reported.
"""
import os
import re

import pytest

from qikly.agent_tools import apply_patch as ap
from qikly.agent_api.code_loader.excerpt import excerpt_source


# ------------------------------------------------------ the patch binary ----

def test_a_missing_patch_binary_says_how_to_install_one(monkeypatch):
    """
    The first failure on a fresh machine, and it stops every run dead. Naming
    the fix per platform is the difference between a minute and a search.
    """
    monkeypatch.setattr(ap.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as caught:
        ap._find_patch_exe()
    message = str(caught.value)
    for platform_hint in ("apt install patch", "brew install gpatch",
                          "Git for Windows"):
        assert platform_hint in message


def test_a_non_gnu_patch_is_told_apart_from_a_failed_hunk():
    """
    These reach the caller identically and mean opposite things. A hunk that
    will not apply is the loop working. A rejected flag means no diff will ever
    apply, so the rest of the run is wasted on regenerating patches that cannot
    land, and nothing says so.
    """
    for rejection in ("patch: unrecognized option '--fuzz=3'",
                      "patch: illegal option -- fuzz",
                      "patch: unknown option --dry-run"):
        assert ap._looks_like_wrong_patch_flavour(rejection), rejection


def test_an_ordinary_hunk_failure_is_not_mistaken_for_the_wrong_binary():
    """The other half, or the check would relabel every normal failure."""
    for ordinary in ("Hunk #1 FAILED at 12.",
                     "1 out of 2 hunks FAILED -- saving rejects to file x.rej",
                     "can't find file to patch at input line 3"):
        assert not ap._looks_like_wrong_patch_flavour(ordinary), ordinary


def test_the_installed_patch_is_gnu_and_takes_the_flags_we_send():
    """
    A live check of the binary on this machine, which is what CI runs on. It
    skips rather than fails where no patch exists, because that is an
    environment fact rather than a defect in this project.
    """
    import subprocess

    try:
        exe = ap._find_patch_exe()
    except RuntimeError:
        pytest.skip("no patch binary on this machine")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    banner = (out.stdout or out.stderr)
    assert "GNU" in banner, (
        f"{exe} is not GNU patch ({banner.splitlines()[:1]}), so --fuzz will be "
        f"rejected and no generated diff will apply")


def test_a_diff_that_would_escape_the_sandbox_is_refused(tmp_path):
    """
    The patch text is model output. Normalising before the prefix check is what
    stops `outputs/agent_src/code/../../../etc/x` matching the prefix and then
    resolving somewhere else entirely.
    """
    patch = tmp_path / "escape.diff"
    patch.write_text(
        "--- a/outputs/agent_src/code/../../../etc/passwd\n"
        "+++ b/outputs/agent_src/code/../../../etc/passwd\n"
        "@@ -1 +1 @@\n-x\n+y\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as caught:
        ap._resolve_targets(str(patch))
    assert "outside" in str(caught.value)


def test_a_diff_naming_no_destination_is_refused(tmp_path):
    patch = tmp_path / "empty.diff"
    patch.write_text("not a diff at all\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        ap._resolve_targets(str(patch))


# ------------------------------------------------- concurrent run safety ----

def test_every_per_run_path_carries_the_task_id(tmp_path):
    """
    Ten tasks run concurrently and the run timestamp is second-resolution, so
    two of them sharing one is routine: it has happened to 151 timestamps here,
    up to 14 tasks at once. Nothing collides because task_id is in every path,
    and that is the property to keep rather than the timestamp's uniqueness.
    """
    import inspect

    from qikly.orchestrator import orchestrator

    source = inspect.getsource(orchestrator.orchestrate)
    for path_expr in ("transactions_{task_id}_{run_timestamp}",):
        assert path_expr in source
    # The patch directory and the run summary are keyed the same way.
    assert "PATCH_DIR, task_id, run_timestamp" in source


def test_two_tasks_sharing_a_timestamp_do_not_share_a_file():
    from qikly.agent_tools import junit

    a = junit.stage_path("TASK_A", "20260101_000000", "unit")
    b = junit.stage_path("TASK_B", "20260101_000000", "unit")
    assert a != b


# --------------------------------------------- text from outside the tree ---

def test_a_criterion_containing_braces_reaches_the_prompt_unchanged():
    """
    `--criteria-from` and the Jira importer both read text nobody here wrote.
    A criterion like "reject rows where {task} is empty" would be a problem if
    the template engine recursed into substituted values. It does not: format
    processes the template, never the arguments.
    """
    from qikly.agent_api.prompts.template_loader import load_template
    from qikly.paths import chdir_to_project_root

    chdir_to_project_root()
    hostile = "reject rows where {task} is {criteria} and n > {0}"
    out = load_template("acceptance_criteria_prompt.md", task=hostile)
    assert hostile in out


def test_a_criterion_is_never_executed_or_evaluated():
    """
    Criteria are data all the way through. Nothing eval()s, exec()s or
    templates them a second time, which is what keeps text from a stranger's
    ticket boring.
    """
    import inspect

    from qikly import criteria_import, jira

    for module in (criteria_import, jira):
        source = inspect.getsource(module)
        for dangerous in ("eval(", "exec(", "os.system", "subprocess"):
            assert dangerous not in source, f"{module.__name__} uses {dangerous}"


# ------------------------------------------------- excerpting at real size --

def _big_module(functions=400, classes=20):
    parts = ["import os", "import csv", "", "RATE = 0.2", ""]
    for i in range(functions):
        parts += [f"def func_{i}(a, b):", f'    """Function {i}."""',
                  f"    total = a + b + {i}", "    return total", ""]
    for i in range(classes):
        parts += [f"class Klass_{i}:"]
        for j in range(5):
            parts += [f"    def method_{i}_{j}(self, x):", f"        return x * {j}", ""]
    return "\n".join(parts)


def test_every_elided_range_names_real_line_numbers():
    """
    The load-bearing property, and the one that fails silently. The excerpt is
    context for a unified diff, and a diff carries line numbers. A range that
    pointed one line off would produce patches that do not apply, which looks
    like the model being bad at diffs rather than the loader being wrong.
    """
    source = _big_module()
    lines = source.split("\n")
    out = excerpt_source(source, {"func_237", "method_12_3"}, path="big.py")

    ranges = re.findall(r"lines (\d+)-(\d+) of big\.py", out)
    assert len(ranges) > 300, "almost nothing was elided, so this proves little"
    for low, high in ranges:
        body = "\n".join(lines[int(low) - 1:int(high)]).strip()
        assert body.startswith(("def ", "class ", "@")), (
            f"lines {low}-{high} do not start a definition: {body[:60]!r}")


def test_the_wanted_symbols_survive_a_large_file_whole():
    out = excerpt_source(_big_module(), {"func_237", "method_12_3"}, path="big.py")
    assert "total = a + b + 237" in out
    assert "return x * 3" in out
    assert "class Klass_12:" in out
    assert "import csv" in out and "RATE = 0.2" in out


def test_excerpting_reduces_but_does_not_bound():
    """
    Worth pinning as a known limit rather than discovering later. Every elided
    definition still costs a signature line, so a module with hundreds of
    functions produces hundreds of signatures: 57k characters becomes 30k here,
    still over the threshold that triggered the excerpt.

    That is the right trade, because a model that cannot see what exists will
    write a second implementation of it. But "excerpting solves large files" is
    not a claim this supports, and the docs say so.
    """
    source = _big_module()
    out = excerpt_source(source, {"func_237"}, path="big.py")
    assert len(out) < len(source), "no reduction at all"
    assert len(out) > 16000, (
        "this file no longer demonstrates the limit; pick a bigger one")


def test_excerpting_a_large_file_is_fast_enough_to_be_invisible():
    """It runs on every PATCH prompt, so it cannot be the slow part."""
    import time

    source = _big_module()
    started = time.monotonic()
    excerpt_source(source, {"func_1"}, path="big.py")
    assert time.monotonic() - started < 2.0


# ------------------------------------- a failure nothing could run at all ---

def test_a_collection_error_says_so_instead_of_unknown_failure():
    """
    Nine of twelve iterations on a first gpt-4o run went to a module that would
    not import, and the FIX prompt's first line read "Unknown failure": true,
    and the least useful sentence available. The error itself was further down
    in the raw output, and the first line is the one most likely to be acted on.

    Gemini rarely writes code that fails to import, so this stayed invisible
    until a second model wrote differently. That is the argument for running
    the demo on every provider before a release.
    """
    from qikly.agent_tools.inspect_code import inspect_failure

    raw = ("ERROR collecting outputs/tests/T/integration/test_integration.py\n"
           "E   ImportError: cannot import name 'extract' from 'calc'\n")
    out = inspect_failure({"raw_output": raw, "failed_tests": []})
    assert "COLLECTION ERROR" in out
    assert "cannot import name 'extract'" in out
    assert "Unknown failure" not in out


def test_an_ordinary_failure_summary_is_untouched():
    """The common path must not change: a named failing test is the summary."""
    from qikly.agent_tools.inspect_code import inspect_failure

    out = inspect_failure({"raw_output": "x", "failed_tests": ["test_a FAILED"]})
    assert out.split("Raw Output")[0].strip().endswith("test_a FAILED")


def test_an_unrecognisable_failure_still_says_unknown():
    """
    The fallback stays. Claiming a collection error where there is none would
    send the agent after an import problem that does not exist.
    """
    from qikly.agent_tools.inspect_code import inspect_failure

    out = inspect_failure({"raw_output": "something else entirely", "failed_tests": []})
    assert "Unknown failure" in out


def test_the_key_setup_page_covers_every_supported_provider():
    """
    A setup page that names two of three providers is worse than none: the
    missing one reads as unsupported.
    """
    import os

    from qikly.agent_api.providers.router import _PROVIDERS

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", "PROVIDER_KEY_SETUP.md"),
              encoding="utf-8") as handle:
        text = handle.read().lower()
    for provider in _PROVIDERS:
        assert provider in text, f"{provider} is supported but not in the setup page"
    assert "azure" not in text, "azure was dropped and must not reappear here"


# ------------------------------------------- what a redirect actually writes -

def test_stdout_carries_utf8_so_a_redirect_produces_a_readable_file():
    """
    The README documents

        qikly --criteria-from ticket.md >> inputs_private/config/tasks/T.yaml

    and on Windows that wrote cp1252. A euro sign became a lone 0x80, and the
    task file that came out could not be decoded by any UTF-8 reader, including
    qikly's own, which opens task files as UTF-8 by name.

    Invisible at the terminal, because the console that wrote the bytes reads
    them back consistently. It surfaces later as a task that will not parse.
    """
    import subprocess
    import sys

    from qikly.console import use_utf8

    assert callable(use_utf8)
    # Run a child that prints non-ASCII through the same path the CLI uses, and
    # read its bytes rather than its text.
    code = (
        "from qikly.console import use_utf8; use_utf8();"
        "print('EURO DASH')".replace("EURO", chr(0x20AC)).replace("DASH", chr(0x2014))
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert proc.returncode == 0, proc.stderr
    decoded = proc.stdout.decode("utf-8")  # raises if it is not UTF-8
    assert chr(0x20AC) in decoded and chr(0x2014) in decoded


def test_reconfiguring_streams_never_raises(monkeypatch):
    """
    A display problem must not end a run. A stream that cannot be reconfigured,
    because a harness replaced it or it is already wrapped, is left alone.
    """
    import io as _io

    from qikly.console import use_utf8

    monkeypatch.setattr("sys.stdout", _io.StringIO())
    monkeypatch.setattr("sys.stderr", _io.StringIO())
    use_utf8()


def test_every_entry_point_that_prints_sets_it_up():
    """
    One entry point left out is one redirect still writing cp1252, and it would
    be the one somebody uses.
    """
    import inspect

    from qikly import cli
    from qikly.orchestrator import run_all
    from qikly.orchestrator.reports import aggregate_report
    from qikly.orchestrator.tuning import propose_fixtures

    for module in (cli, run_all, aggregate_report, propose_fixtures):
        source = inspect.getsource(module.main)
        assert "use_utf8()" in source, f"{module.__name__}.main does not set UTF-8"


# ------------------------------------------ what the console says happened --

def _line(iteration, counts, results=()):
    import tempfile

    from qikly.agent_tools import run_tests as rt

    original = rt.REPORT_DIR
    rt.REPORT_DIR = tempfile.mkdtemp()
    try:
        import io as _io
        import contextlib

        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rt._write_summary_report("T", "integration", iteration, counts,
                                     list(results), "ts", 1, 3)
        return buf.getvalue().strip()
    finally:
        rt.REPORT_DIR = original


NOTHING_RAN = {"passed": 0, "failed": 0, "error": 1, "skipped": 0, "total": 1}


def test_the_bootstrap_failure_says_it_is_expected():
    """
    Iteration 0 runs the suite before any code exists, on purpose, and does not
    count against the attempt budget. Printed as bare counts it was
    indistinguishable from the agent failing, and it opens the demo.
    """
    line = _line(0, NOTHING_RAN)
    assert "no code exists yet" in line
    assert "expected" in line


def test_a_later_collection_error_says_the_module_would_not_import():
    """
    Not the same event as the bootstrap, and the difference is what a viewer
    needs: this one is the agent failing, and it failed for a reason worth
    naming rather than as four counts that are all zero or one.
    """
    line = _line(3, NOTHING_RAN)
    assert "could not be imported" in line
    assert "no code exists yet" not in line


def test_an_ordinary_result_is_unchanged():
    """The common path must not move: passed over total, and the names."""
    results = [("test_a", "passed"), ("test_b", "failed")]
    line = _line(2, {"passed": 1, "failed": 1, "error": 0, "skipped": 0, "total": 2},
                 results)
    assert "1/2 passed" in line
    assert "FAILED: test_b" in line
