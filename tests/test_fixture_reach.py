"""
The free reachability check: which criteria the data cannot trigger.

Two halves matter here and they pull against each other. It has to find a
criterion whose value no row holds, and it has to stay quiet on thirteen
bundled tasks whose criteria are full of numbers that are not values. Every
test below is one of the false positives that an earlier, looser rule produced
against those tasks, kept so the rule cannot loosen again by accident.
"""
import io
import os

import pytest

from qikly import fixture_reach as fr


RADAR = ("sample_id,ego_speed_mps,gap_m\n"
         "S001,20.0,40.0\n"
         "S013,12.0,250.0\n"
         "S016,30.0,250.01\n")


def _task(tmp_path, criteria, data=RADAR, name="radar.csv"):
    path = tmp_path / name
    io.open(str(path), "w", encoding="utf-8", newline="\n").write(data)
    task = {"acceptance_criteria": criteria, "inputs": [name]}
    return task, (lambda declared: str(path))


def test_a_value_no_row_holds_is_reported(tmp_path):
    task, resolve = _task(tmp_path, ["A gap_m of exactly 0 is rejected"])
    found = fr.unreachable(task, resolve)
    assert [(i, m) for i, _c, m, _f in found] == [(1, ["0"])]


def test_a_value_the_data_holds_is_not_reported(tmp_path):
    task, resolve = _task(
        tmp_path, ["A gap_m of exactly 250 is accepted and 250.01 is rejected"])
    assert fr.unreachable(task, resolve) == []


def test_one_value_present_is_enough(tmp_path):
    """
    A criterion usually needs one row, not all of them.

    Reporting a criterion because one of its three numbers is absent would
    fire on almost every boundary criterion ever written, since the data
    rarely holds both sides and every worked value.
    """
    task, resolve = _task(
        tmp_path, ["A gap_m of exactly 250 is accepted, 999 is rejected"])
    assert fr.unreachable(task, resolve) == []


def test_the_field_has_to_be_one_the_data_has(tmp_path):
    """
    Without this the check reads output structure as input values.

    Criteria talk about what lands in "accepted" and "rejected", which are
    output keys no input row will ever contain. Requiring a field the data
    actually has is what keeps those out.
    """
    task, resolve = _task(tmp_path, [
        'Every sample is listed under "accepted" exactly once',
        "All computed amounts are rounded, so 434.99999999999994 reports as 435.00",
    ])
    assert fr.unreachable(task, resolve) == []


def test_a_value_is_checked_against_its_own_field(tmp_path):
    """
    40.0 is in the file, under gap_m. It is not an ego_speed_mps.

    An earlier version searched the whole file, so a boundary for one column
    was satisfied by an unrelated column holding the same number, and the
    check quietly agreed that everything was reachable.
    """
    task, resolve = _task(tmp_path, ["An ego_speed_mps of exactly 40 is rejected"])
    assert [i for i, _c, _m, _f in fr.unreachable(task, resolve)] == [1]


@pytest.mark.parametrize("criterion", [
    "A zip is only valid if it is exactly 5 digits after normalization",
    "A state is only valid if it identifies one of the 50 real US states",
    "phone is valid if, once formatting is removed, it is exactly 10 digits",
    "Rows from file 1 and file 2 are combined into one stream",
])
def test_counts_and_ordinals_are_not_values(tmp_path, criterion):
    """
    Every one of these was flagged by the version that took any number.

    A number in a criterion is usually counting something: digits, states,
    files, positions. Only a number in a value construction is a value, which
    is why the relation words are required.
    """
    data = ("zip,state,phone,file\n"
            "94103,CA,4155550101,a\n")
    task, resolve = _task(tmp_path, [criterion], data=data, name="rows.csv")
    assert fr.unreachable(task, resolve) == []


def test_a_worked_example_in_parentheses_is_not_a_value(tmp_path):
    """
    CALC_CALENDAR's own wording, and the last false positive to go.

    "(e.g. January 1 to January 5 is 5 billed days, not 4)" illustrates the
    rule rather than naming a value any field holds.
    """
    data = "customer_id,start_date,end_date\nCUST-1,2026-01-01,2026-01-31\n"
    task, resolve = _task(tmp_path, [
        "The number of billed days is counted inclusively, both start_date and "
        "end_date count (e.g. January 1 to January 5 is 5 billed days, not 4)"],
        data=data, name="billing.csv")
    assert fr.unreachable(task, resolve) == []


def test_the_value_pattern_still_discriminates():
    """
    The guard that has to exist because this check was once dead.

    An edit turned every `\\b` in the value pattern into a literal backspace,
    so the regex matched nothing at all. The check then reported zero findings
    across every bundled task, which is exactly what a healthy check reports,
    and the count alone could not tell the two apart.
    """
    assert "\\b" in fr._VALUE.pattern, "word boundaries lost from the pattern"
    assert "\x08" not in fr._VALUE.pattern, "a backspace is not a word boundary"
    assert fr._VALUE.findall("a gap_m of exactly 250") == ["250"]
    assert fr._VALUE.findall("this 5") == []
    assert fr._VALUE.findall("roof 9") == []


def test_a_number_inside_a_larger_one_does_not_count(tmp_path):
    """250 is not present merely because 1250 is."""
    data = "sample_id,gap_m\nS001,1250.0\n"
    task, resolve = _task(tmp_path, ["A gap_m of exactly 250 is accepted"],
                          data=data)
    assert [i for i, _c, _m, _f in fr.unreachable(task, resolve)] == [1]


def test_json_inputs_are_read_by_field(tmp_path):
    data = ('[{"sample_id": "S001", "gap_m": 40.0},'
            ' {"sample_id": "S002", "gap_m": 250.0}]')
    task, resolve = _task(tmp_path, [
        "A gap_m of exactly 250 is accepted",
        "A gap_m of exactly 0 is rejected",
    ], data=data, name="rows.json")
    assert [i for i, _c, _m, _f in fr.unreachable(task, resolve)] == [2]


def test_missing_data_is_not_this_check_s_finding(tmp_path):
    """`validate` already reports a missing input file, as an error."""
    task = {"acceptance_criteria": ["A gap_m of exactly 0 is rejected"],
            "inputs": ["nowhere.csv"]}
    assert fr.unreachable(task, lambda declared: None) == []


def test_no_criteria_and_no_inputs_are_silent(tmp_path):
    assert fr.unreachable({}, None) == []
    assert fr.unreachable({"acceptance_criteria": ["A gap_m of 0 is rejected"]},
                          None) == []


def test_describe_names_the_criterion_and_the_value(tmp_path):
    task, resolve = _task(tmp_path, ["A gap_m of exactly 0 is rejected"])
    lines = fr.describe(task, "ADAS.yaml", resolve)
    assert len(lines) == 1
    assert "ADAS.yaml" in lines[0] and "criterion 1" in lines[0]
    assert "names 0 for gap_m" in lines[0]


def test_the_bundled_tasks_are_clean():
    """
    The noise floor, measured rather than assumed.

    Thirteen tasks and 134 criteria whose fixtures were audited for exactly
    this, so the correct report is nothing. Earlier rules scored 49 and then
    11 here, and both were entirely false. If this ever fails, read the
    finding before loosening the rule: it may be right.
    """
    import glob

    import yaml

    from qikly.validate import _readable_input

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "qikly", "inputs_public", "config", "tasks")
    paths = sorted(glob.glob(os.path.join(root, "*.yaml")))
    if not paths:
        pytest.skip("bundled tasks not present in this tree")

    reported = []
    for path in paths:
        with io.open(path, encoding="utf-8") as handle:
            task = yaml.safe_load(handle)
        for index, criterion, missing, _fields in fr.unreachable(task, _readable_input):
            reported.append(f"{os.path.basename(path)} criterion {index}: "
                            f"{missing} in {criterion[:60]!r}")
    assert reported == [], "\n".join(reported)
