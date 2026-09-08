"""
Patch target resolution and sandbox containment.

Two real bugs lived here. A bare-path diff was being applied at -p1, which
stripped its first real component and landed the change in a phantom tree: the
patch applied cleanly, the implementation was untouched, and the loop burned an
attempt believing it had made a change. And a path containing `..` matched the
CODE_ROOT prefix while resolving outside it.

Both are silent when they fire, which is what makes them worth pinning.
"""
import pytest

from qikly.agent_tools.apply_patch import CODE_ROOT, _resolve_targets


def write(tmp_path, text):
    p = tmp_path / "p.diff"
    p.write_text(text, encoding="utf-8", newline="\n")
    return str(p)


def diff(dest_lines):
    return "".join(f"--- {d}\n+++ {d}\n@@ -1 +1 @@\n-a\n+b\n" for d in dest_lines)


def test_git_prefixed_diff_resolves_at_p1(tmp_path):
    p = write(tmp_path, diff([f"b/{CODE_ROOT}CALC_TAX/calc.py"]))
    strip, resolved = _resolve_targets(p)
    assert strip == 1
    assert resolved == [f"{CODE_ROOT}CALC_TAX/calc.py"]


def test_bare_diff_resolves_at_p0_not_p1(tmp_path):
    """The regression: -p1 here would strip `outputs/` and write to a phantom tree."""
    p = write(tmp_path, diff([f"{CODE_ROOT}CALC_TAX/calc.py"]))
    strip, resolved = _resolve_targets(p)
    assert strip == 0
    assert resolved == [f"{CODE_ROOT}CALC_TAX/calc.py"]


def test_mixed_prefixes_are_rejected(tmp_path):
    """One -p applies to the whole file, so a mixed diff is correct at no level."""
    p = write(tmp_path, diff([f"b/{CODE_ROOT}a.py", f"{CODE_ROOT}b.py"]))
    with pytest.raises(RuntimeError, match="mixes"):
        _resolve_targets(p)


@pytest.mark.parametrize("dest", [
    "etc/passwd",
    "outputs/agent_src/other/x.py",
    f"{CODE_ROOT}../../../escaped.py",
    f"{CODE_ROOT}CALC_TAX/../../../../escaped.py",
    "../outside.py",
])
def test_writes_outside_the_sandbox_are_rejected(tmp_path, dest):
    p = write(tmp_path, diff([dest]))
    with pytest.raises(RuntimeError, match="outside"):
        _resolve_targets(p)


def test_dev_null_destinations_are_ignored(tmp_path):
    p = write(tmp_path, diff(["/dev/null", f"{CODE_ROOT}CALC_TAX/calc.py"]))
    strip, resolved = _resolve_targets(p)
    assert resolved == [f"{CODE_ROOT}CALC_TAX/calc.py"]


def test_diff_with_no_destination_is_rejected(tmp_path):
    p = write(tmp_path, "@@ -1 +1 @@\n-a\n+b\n")
    with pytest.raises(RuntimeError, match="no destination"):
        _resolve_targets(p)


def test_trailing_timestamp_column_is_stripped(tmp_path):
    p = write(tmp_path,
              f"--- {CODE_ROOT}c.py\t2026-01-01 00:00:00\n"
              f"+++ {CODE_ROOT}c.py\t2026-01-01 00:00:00\n@@ -1 +1 @@\n-a\n+b\n")
    _, resolved = _resolve_targets(p)
    assert resolved == [f"{CODE_ROOT}c.py"]


def test_windows_separators_are_normalised(tmp_path):
    p = write(tmp_path, diff(["outputs\\agent_src\\code\\CALC_TAX\\calc.py"]))
    _, resolved = _resolve_targets(p)
    assert resolved == [f"{CODE_ROOT}CALC_TAX/calc.py"]


def test_gpatch_is_preferred_over_the_system_patch(monkeypatch):
    """
    macOS ships Apple's BSD patch as `patch`, and it rejects the GNU long
    options this module sends. The error path tells the user to run
    `brew install gpatch`, which installs the binary as `gpatch` rather than
    replacing the system one, so a lookup that asked for `patch` first found
    Apple's every time and the documented fix did nothing.
    """
    from qikly.agent_tools import apply_patch as ap

    asked = []

    def fake_which(name):
        asked.append(name)
        return {"gpatch": "/opt/homebrew/bin/gpatch",
                "patch": "/usr/bin/patch"}.get(name)

    monkeypatch.setattr(ap.shutil, "which", fake_which)
    assert ap._find_patch_exe() == "/opt/homebrew/bin/gpatch"
    assert asked[0] == "gpatch", "the system patch was consulted first"


def test_the_system_patch_is_still_used_when_gpatch_is_absent(monkeypatch):
    """Linux and Windows have no gpatch, and must be unaffected."""
    from qikly.agent_tools import apply_patch as ap

    monkeypatch.setattr(ap.shutil, "which",
                        lambda name: "/usr/bin/patch" if name == "patch" else None)
    assert ap._find_patch_exe() == "/usr/bin/patch"
