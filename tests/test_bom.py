"""
A Python file that starts with a UTF-8 byte-order mark.

Python runs such a file without complaint, and Windows tools write the mark
routinely: PowerShell 5.1's `Set-Content -Encoding utf8` does, and so did
Notepad for years. qikly read those files as plain UTF-8, which keeps the mark
as a U+FEFF character, and `ast.parse` then refused the file as "invalid
non-printable character". Found by writing a throwaway test module in
PowerShell, not by reading the code.
"""
import io


def _module_with_bom(tmp_path):
    path = tmp_path / "mod.py"
    with io.open(path, "w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write("def add(a, b):\n    return a + b\n")
    assert path.read_bytes()[:3] == b"\xef\xbb\xbf", "the fixture must carry a BOM"
    return str(path)


def test_scaffold_reads_a_module_that_starts_with_a_bom(tmp_path):
    from qikly import scaffold

    yaml_text, problem = scaffold.build_task(_module_with_bom(tmp_path), str(tmp_path))
    assert problem is None, problem
    assert "add(a, b)" in yaml_text


def test_the_code_excerpt_does_not_carry_the_bom_into_a_prompt(tmp_path):
    from qikly.agent_api.code_loader.excerpt import excerpt_file

    text = excerpt_file(_module_with_bom(tmp_path), ["add"])
    assert not text.startswith(chr(0xFEFF))
    assert "def add" in text
