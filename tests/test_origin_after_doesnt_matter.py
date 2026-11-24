"""
A `#? CHECK` note above a question answered "doesn't matter" belongs to that
item, which a run drops. It used to carry over to the next item, so the
person's own pick came back labelled "check".
"""
from qikly import take_tests

DM = "doesn't matter, so no test for this"
OTHER = "other: write  N: <your sentence>, or just the sentence"


def _file(tmp_path, first_answer):
    folder = tmp_path / "inputs_private" / "config" / "tasks"
    folder.mkdir(parents=True)
    (folder / "T_VERIFY.yaml").write_text(
        'task_id: "T_VERIFY"\nacceptance_criteria:\n'
        "  #? What should f(1) do?\n"
        "  #?   1 = f(1) returns 1\n  #?   2 = f(1) returns 2\n"
        f"  #?   3 = {DM}\n  #?   4 = {OTHER}\n"
        "  #? CHECK: qikly was unsure of this answer. Read it first.\n"
        f"  - {first_answer}\n"
        "  #? What should f(2) do?\n"
        "  #?   1 = f(2) returns 2\n  #?   2 = f(2) returns 3\n"
        f"  #?   3 = {DM}\n  #?   4 = {OTHER}\n"
        "  - 1\n", encoding="utf-8")


def test_a_check_note_does_not_carry_past_a_doesnt_matter_item(tmp_path):
    _file(tmp_path, "3")
    assert take_tests.criteria_with_origin(str(tmp_path), "T_VERIFY") == [
        ("f(2) returns 2", "you")]


def test_a_check_note_still_labels_its_own_item(tmp_path):
    _file(tmp_path, "1")
    assert take_tests.criteria_with_origin(str(tmp_path), "T_VERIFY") == [
        ("f(1) returns 1", "check"), ("f(2) returns 2", "you")]
