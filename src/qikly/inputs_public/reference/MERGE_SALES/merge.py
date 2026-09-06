"""
Reference implementation for MERGE_SALES, written by hand from the spec.

This file exists to be judged, not to be judged against. No agent sees it, and
no generated suite may be consulted while writing it. If a generated suite
fails this file, the suite is refusing code that satisfies the specification,
which is a false rejection no amount of fault detection compensates for.

Written from `requirements` and `acceptance_criteria` together, which is the
one place in this project where both halves are read by the same author. That
is the point: a reference is only a reference if it is known-correct
independently of anything a model produced.

## Four places the spec does not decide, and what was chosen

Each of these is a real gap rather than an oversight in reading. They are
recorded here because a suite disagreeing with any of them is a disagreement
about the SPECIFICATION, not evidence that either side is wrong.

**Case.** Validity is defined on the trimmed id ("non-empty once
whitespace-trimmed"), so the trimmed value is what gets compared: validating
one string while keying on another would be incoherent. Case is never
mentioned, so it is left alone. ` txn-1001 ` and `TXN-1001` are therefore two
different transactions.

**Implausible values.** The requirements say to reject the implausible, but no
criterion gives a threshold for either amount or date. An amount of
99999999999.00 and a date of 2099-12-31 are accepted, because inventing a
bound would be inventing a rule the spec does not contain. This is the gap
most likely to produce a disagreement.

**Duplicates inside one file.** Every criterion about duplicates says "in both
input files", but identity is defined as "the same transaction_id, regardless
of which file they came from". The rules are therefore applied to repeats
wherever they occur, since the identity criterion is the more general one.

**Output order.** Nothing constrains it, so input order is preserved and a
reader can line the result up against the file they supplied.

## Validation runs before deduplication

A row with a non-numeric amount cannot be compared by amount, so it could not
take part in the mismatch rule even in principle. Invalid rows are rejected
for their own specific reason and take no part in deduplication.
"""
import csv
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

DATE_FORMAT = "%Y-%m-%d"


def extract(input_path):
    """Read one input file and return its raw rows, unvalidated."""
    with open(input_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _clean_id(row):
    """The trimmed transaction_id, or None. Trimmed because validity is
    defined on the trimmed value, and this same value is the identity."""
    value = (row.get("transaction_id") or "").strip()
    return value or None


def _clean_amount(row):
    """
    A positive number, or None.

    Decimal rather than float, because these are money and a comparison for
    equality decides whether two rows are the same transaction. `Decimal` also
    rejects an empty string and anything non-numeric, which is what the
    criteria call invalid. A leading currency symbol is not a number as
    written, so "$75.25" is invalid: the criteria say non-numeric values are,
    and the requirements ask for strict validation.
    """
    raw = (row.get("amount") or "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount if amount > 0 else None


def _clean_date(row):
    """A real calendar date in YYYY-MM-DD, or None. strptime rejects both a
    wrong format and an impossible day, which is exactly the criterion."""
    raw = (row.get("date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None


def _validate(row):
    """Returns (parsed, reason). Exactly one of them is None."""
    transaction_id = _clean_id(row)
    if transaction_id is None:
        return None, "transaction_id is empty or whitespace only"

    amount = _clean_amount(row)
    if amount is None:
        raw = (row.get("amount") or "").strip()
        return None, "amount " + repr(raw) + " is not a number greater than zero"

    date = _clean_date(row)
    if date is None:
        raw = (row.get("date") or "").strip()
        return None, "date " + repr(raw) + " is not a real calendar date in YYYY-MM-DD"

    return {"transaction_id": transaction_id, "amount": amount, "date": date}, None


def transform(rows):
    """
    Validate every row, then collapse repeated transaction_ids.

    Three outcomes per id once the invalid rows are out of the way:

      seen once                     accepted as it stands
      seen again, amounts agree     the same real transaction recorded in two
                                    overlapping exports, so accepted ONCE
      seen again, amounts differ    an unresolvable inconsistency, so EVERY
                                    occurrence is rejected, not just the later
                                    one, since the spec gives no rule for
                                    choosing between them
    """
    prepared = []
    for position, row in enumerate(rows):
        parsed, reason = _validate(row)
        prepared.append({"position": position, "row": row,
                         "parsed": parsed, "reason": reason})

    amounts_by_id = {}
    for item in prepared:
        if item["parsed"]:
            amounts_by_id.setdefault(item["parsed"]["transaction_id"], []).append(
                item["parsed"]["amount"])

    accepted, rejected = [], []
    already_accepted = set()
    for item in prepared:
        parsed = item["parsed"]
        if parsed is None:
            rejected.append(dict(item["row"], reason=item["reason"]))
            continue

        transaction_id = parsed["transaction_id"]
        amounts = amounts_by_id[transaction_id]
        if len(set(amounts)) > 1:
            listed = ", ".join(sorted(str(a) for a in set(amounts)))
            rejected.append(dict(
                item["row"],
                reason=("mismatched duplicate transaction_id " + repr(transaction_id)
                        + ": the same transaction appears with differing amounts ("
                        + listed + ")")))
            continue

        if transaction_id in already_accepted:
            # The same transaction from the other export's overlapping window.
            # Not an error and not a rejection: it is one transaction, and it
            # is already in the accepted list once.
            continue
        already_accepted.add(transaction_id)
        accepted.append(dict(item["row"], transaction_id=transaction_id))

    return {"accepted": accepted, "rejected": rejected}


def load(data, output_path):
    """Write the result as a single JSON object."""
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)


def run_merge(input_paths, output_path):
    """Read every input, combine, validate and deduplicate, then write."""
    rows = []
    for path in input_paths:
        rows.extend(extract(path))
    load(transform(rows), output_path)
