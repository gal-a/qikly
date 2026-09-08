"""
The reference implementations satisfy their own specifications.

A reference is the only thing in this project that is known-correct without
reference to anything a model produced, and two measurements rest entirely on
that: `false_rejection.py` asks whether a suite refuses it, and
`shared_substrate.py` uses it as the one substrate neither experiment arm
wrote. If a reference is wrong, both measurements are wrong and nothing else
would catch it.

So each acceptance criterion is checked directly here, against the same
fixtures a real run uses.

There is a second reason to pin this behaviour. When a generated suite fails a
reference, the tempting repair is to edit the reference until it passes. That
destroys the independence the whole measurement rests on, and these tests turn
it from a temptation into a failing build.

Where the specification does not decide something, the choice the reference
made is asserted here WITH the reason. Those cases are marked; a suite
disagreeing with one of them is a disagreement about the spec rather than
evidence that either side is wrong.
"""
import importlib.util
import json
import os

import pytest
import yaml

from qikly.paths import chdir_to_project_root, resolve_input

ROOT = chdir_to_project_root()


def _input(relative):
    """
    A declared input, found the way a run finds it.

    Task files name `inputs_private/data/<TASK>/input_01.csv`, and a bundled
    task's fixtures live inside the package until a run copies them out.
    Joining the literal path onto the project root therefore only works on a
    machine that already has an `inputs_private/` tree, which a fresh clone
    does not: every fixture here errored with FileNotFoundError on CI, naming
    a file that was never meant to be there. `qikly.validate._input_exists`
    carries the same rule for the same reason.
    """
    from qikly.paths import DEFAULT_PRIVATE_DIR

    literal = os.path.join(ROOT, relative)
    if os.path.isfile(literal):
        return literal
    parts = relative.replace("\\", "/").split("/")
    if parts and parts[0] in (DEFAULT_PRIVATE_DIR, "inputs_public"):
        return resolve_input("/".join(parts[1:]))
    return literal


def _load(task_id):
    with open(resolve_input(f"config/tasks/{task_id}.yaml"), encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    path = resolve_input(config["reference"]["implementation"])
    spec = importlib.util.spec_from_file_location(f"ref_{task_id}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, config


@pytest.fixture(scope="module")
def sales():
    module, config = _load("MERGE_SALES")
    rows = []
    for relative in config["inputs"]:
        rows.extend(module.extract(_input(relative)))
    return module, rows, module.transform(rows)


def _by_id(entries):
    out = {}
    for entry in entries:
        out.setdefault((entry.get("transaction_id") or "").strip(), []).append(entry)
    return out


# ------------------------------------------------- MERGE_SALES, the shape ----

def test_the_result_is_one_object_with_two_lists(sales):
    _, _, result = sales
    assert set(result) == {"accepted", "rejected"}
    assert all(isinstance(v, list) for v in result.values())
    assert all(isinstance(item, dict)
               for value in result.values() for item in value)


def test_the_output_file_is_valid_json_with_both_keys(sales, tmp_path):
    module, _, result = sales
    out = tmp_path / "nested" / "output.json"
    module.load(result, str(out))
    assert set(json.loads(out.read_text(encoding="utf-8"))) == {"accepted", "rejected"}


def test_every_rejection_names_the_field_or_the_duplicate(sales):
    """
    The criterion forbids a generic message. "invalid row" tells whoever has
    to fix the export nothing at all.
    """
    _, _, result = sales
    for entry in result["rejected"]:
        reason = entry["reason"]
        assert any(word in reason for word in
                   ("transaction_id", "amount", "date")), reason
        assert reason.strip().lower() not in ("invalid row", "invalid")


# ------------------------------------------- MERGE_SALES, field validation ----

def test_a_negative_amount_is_rejected_naming_amount(sales):
    _, _, result = sales
    assert "amount" in _by_id(result["rejected"])["TXN-1003"][0]["reason"]


def test_a_missing_amount_is_rejected_naming_amount(sales):
    _, _, result = sales
    assert "amount" in _by_id(result["rejected"])["TXN-1005"][0]["reason"]


def test_a_non_numeric_amount_is_rejected_naming_amount(sales):
    _, _, result = sales
    assert "amount" in _by_id(result["rejected"])["TXN-1007"][0]["reason"]


def test_a_date_in_the_wrong_format_is_rejected_naming_date(sales):
    """The criterion names YYYY-MM-DD specifically, so 01/09/2026 fails it."""
    _, _, result = sales
    assert "date" in _by_id(result["rejected"])["TXN-1010"][0]["reason"]


def test_nothing_valid_was_rejected_and_nothing_invalid_accepted(sales):
    """
    The two halves of the first criterion, checked against each other rather
    than against a hardcoded list: no id may appear in both outputs unless it
    is the mismatched-duplicate case, where every occurrence is rejected.
    """
    _, _, result = sales
    accepted = set(_by_id(result["accepted"]))
    rejected = set(_by_id(result["rejected"]))
    assert not (accepted & rejected)


# ------------------------------------------------ MERGE_SALES, duplicates ----

def test_a_transaction_in_both_files_at_the_same_amount_appears_once(sales):
    """
    The point of the whole task: overlapping export windows must not
    double-count. TXN-1001 is in both files at 150.00.
    """
    _, rows, result = sales
    assert sum(1 for r in rows if r["transaction_id"].strip() == "TXN-1001") == 2
    assert len(_by_id(result["accepted"])["TXN-1001"]) == 1


def test_a_transaction_in_both_files_at_differing_amounts_rejects_both(sales):
    """
    TXN-1002 is 89.50 in one file and 99.50 in the other. The criterion
    forbids silently keeping either, so both occurrences are rejected.
    """
    _, _, result = sales
    assert "TXN-1002" not in _by_id(result["accepted"])
    entries = _by_id(result["rejected"])["TXN-1002"]
    assert len(entries) == 2
    assert all("duplicate" in e["reason"] for e in entries)


def test_an_id_in_only_one_file_is_accepted_as_it_stands(sales):
    _, _, result = sales
    assert "TXN-1006" in _by_id(result["accepted"])
    assert "TXN-1004" in _by_id(result["accepted"])


def test_identity_ignores_the_date_when_the_amount_agrees(sales):
    """
    "the same transaction if and only if they share the same transaction_id,
    regardless of whether their amount or date also matches", combined with
    the amount rule. Only the amount decides a mismatch, so a differing date
    at an agreeing amount is still one transaction.
    """
    module, _, _ = sales
    rows = [{"transaction_id": "A", "amount": "10.00", "date": "2026-01-01"},
            {"transaction_id": "A", "amount": "10.00", "date": "2026-02-02"}]
    result = module.transform(rows)
    assert len(result["accepted"]) == 1
    assert result["rejected"] == []


# ------------------------------- MERGE_SALES, where the spec does not decide --

def test_an_id_is_compared_after_trimming_but_not_after_folding_case(sales):
    """
    UNDECIDED BY THE SPEC. Validity is defined on the trimmed id, so the
    trimmed value is what gets compared: validating one string while keying on
    another would be incoherent. Case is never mentioned, so it is left alone,
    which makes ` txn-1001 ` a different transaction from `TXN-1001`.
    """
    _, _, result = sales
    accepted = _by_id(result["accepted"])
    assert "txn-1001" in accepted and "TXN-1001" in accepted


def test_an_implausibly_large_amount_is_accepted(sales):
    """
    UNDECIDED BY THE SPEC. The requirements say to reject the implausible;
    no criterion gives a threshold. Inventing one would invent a rule, so the
    value stands. This is the likeliest source of disagreement with a suite.
    """
    _, _, result = sales
    assert "TXN-1009" in _by_id(result["accepted"])


def test_an_implausibly_distant_date_is_accepted(sales):
    """UNDECIDED BY THE SPEC, for the same reason: 2099-12-31 parses."""
    _, _, result = sales
    assert "TXN-1011" in _by_id(result["accepted"])


def test_a_currency_symbol_makes_an_amount_non_numeric(sales):
    """
    UNDECIDED, leaning strict. The requirements call amount "a dollar amount",
    which could be read as admitting a dollar sign, but the criteria say a
    non-numeric value is invalid and ask for strict validation. "$75.25" is
    not a number as written.
    """
    _, _, result = sales
    assert "amount" in _by_id(result["rejected"])["TXN-1008"][0]["reason"]


def test_repeats_inside_a_single_file_follow_the_same_rules(sales):
    """
    UNDECIDED BY THE SPEC. Every duplicate criterion says "in both input
    files", but identity is defined regardless of which file a row came from,
    so the more general criterion is the one applied.
    """
    module, _, _ = sales
    same = module.transform([{"transaction_id": "B", "amount": "5.00", "date": "2026-01-01"},
                             {"transaction_id": "B", "amount": "5.00", "date": "2026-01-01"}])
    assert len(same["accepted"]) == 1
    differ = module.transform([{"transaction_id": "C", "amount": "5.00", "date": "2026-01-01"},
                               {"transaction_id": "C", "amount": "6.00", "date": "2026-01-01"}])
    assert differ["accepted"] == [] and len(differ["rejected"]) == 2


# ------------------------------------------------------------- both of them --

@pytest.mark.parametrize("task_id", ["MERGE_SALES", "MERGE_STOCK"])
def test_a_reference_is_never_shown_to_an_agent(task_id):
    """
    The property everything else rests on. Only the two research harnesses may
    read these paths; a prompt builder reaching one would make the reference
    an input to the thing it exists to judge.
    """
    _, config = _load(task_id)
    relative = config["reference"]["implementation"]
    offenders = []
    for directory, _dirs, files in os.walk(os.path.join(ROOT, "src", "qikly")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as handle:
                if "reference/" in handle.read():
                    offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, (
        f"{relative} is referenced from shipped code: {offenders}")


@pytest.mark.parametrize("task_id", ["MERGE_SALES", "MERGE_STOCK"])
def test_the_reference_provides_every_function_the_interface_declares(task_id):
    module, config = _load(task_id)
    declared = [line.split("(")[0].strip()
                for line in config["interface"]["integration_functions"]]
    declared.append(config["interface"]["system_entrypoint"].split("(")[0].strip())
    for name in declared:
        assert callable(getattr(module, name, None)), f"{task_id} lacks {name}"


# ---------------------------------- the fixtures reach every criterion now ----

def test_merge_sales_data_can_trigger_every_criterion_it_declares():
    """
    The _WIDE variants are gone. They existed to hold rows the base fixtures
    lacked, and the base has them now: proposed by the fixture agent, reviewed,
    and accepted through the sidecar. A criterion nothing can reach produces a
    test that passes whatever the code does, which is worse in a shipped task
    than in an experiment.
    """
    import csv

    rows = []
    for i in (1, 2):
        with open(_input(f"inputs_private/data/MERGE_SALES/input_0{i}.csv"),
                  newline="", encoding="utf-8") as handle:
            rows += list(csv.DictReader(handle))
    assert any(not (r["transaction_id"] or "").strip() for r in rows),         "nothing tests the non-empty-once-trimmed rule"
    assert any((r["amount"] or "").strip() == "0.00" for r in rows),         "the criteria name zero explicitly and no row is zero"
    assert any("02-30" in (r["date"] or "") for r in rows),         "a real calendar date was only ever tested by a wrong format"


def test_merge_stock_data_can_trigger_every_criterion_it_declares():
    import collections
    import csv

    rows = []
    for i in (1, 2):
        with open(_input(f"inputs_private/data/MERGE_STOCK/input_0{i}.csv"),
                  newline="", encoding="utf-8") as handle:
            rows += list(csv.DictReader(handle))
    assert any(not (r["timestamp"] or "").strip() for r in rows),         "'missing timestamps are invalid' has no row"
    assert any("." in (r["quantity"] or "") for r in rows),         "'whole number' has no fractional row to reject"
    pairs = collections.Counter((r["sku"].strip(), r["timestamp"].strip()) for r in rows)
    assert [k for k, n in pairs.items() if n > 1],         "the tie-break criterion has nothing exercising it, which is what the "         "fixture agent wrongly reported as covered"
