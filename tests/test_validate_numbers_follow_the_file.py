"""
Every number --validate prints for an item is the item's position in the file,
counting an item answered "doesn't matter" like any other: it used to count
after those were removed, so one output could call the file's second item
"criterion 1" and its third "criterion 3".
"""
from qikly.validate import check_task

HEAD = ('task_id: "X_VERIFY"\ntask_name: "f"\ndescription: "f"\n'
        'requirements: "f returns its input, or raises above 99"\n'
        'interface:\n  integration_functions: ["f"]\n')


def _question(answer):
    return ("  #? What should f(2) do?\n"
            "  #?   1 = f(2) returns 2\n"
            "  #?   2 = f(2) returns 3\n"
            "  #?   3 = doesn't matter, so no test for this\n"
            "  #?   4 = other: write  N: <your sentence>, or just the sentence\n"
            f"  - {answer}\n")


def _check(tmp_path, *answers):
    path = tmp_path / "X_VERIFY.yaml"
    path.write_text(HEAD + "acceptance_criteria:\n"
                    + "".join(_question(a) for a in answers), encoding="utf-8")
    return check_task(str(path))


def test_errors_after_a_doesnt_matter_item_keep_the_files_numbers(tmp_path):
    errors, _ = _check(tmp_path, "3", "f(100) returns: 0", "7")
    assert any("criterion 2 has a colon" in e for e in errors), errors
    assert any("criterion 3 answers '7'" in e for e in errors), errors


def test_the_answered_count_counts_the_doesnt_matter_item(tmp_path):
    _, warnings = _check(tmp_path, "3", '"f(2) returns 2"',
                         '"TODO: pick 1, 2, 3 or 4, or write your own"',
                         '"TODO: pick 1, 2, 3 or 4, or write your own"')
    text = " ".join(str(w) for w in warnings)
    assert "2 of its 4 acceptance criteria are answered" in text, text
    assert "skips the 2 still left" in text, text


def test_a_bare_number_in_the_data_keeps_its_file_position(tmp_path):
    path = tmp_path / "X_VERIFY.yaml"
    path.write_text(HEAD + "acceptance_criteria:\n  #? q\n"
                    "  #?   1 = a\n  #?   2 = doesn't matter, so no test for this\n"
                    "  #?   3 = other: write  N: <your sentence>, or just the sentence\n"
                    "  - 2\n  - 1.5\n", encoding="utf-8")
    errors, _ = check_task(str(path))
    assert any("criterion 2 is 1.5" in e for e in errors), errors
