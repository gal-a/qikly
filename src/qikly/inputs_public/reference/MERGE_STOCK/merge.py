"""
Reference implementation for MERGE_STOCK, written by hand from the spec.

This file exists to be judged, not to be judged against. It is never shown to
any agent, and no generated suite may see it before being run on it. If a
generated suite fails this file, the suite is refusing code that satisfies the
specification, and that is a false rejection no amount of fault detection
compensates for.

Written from `requirements` and `acceptance_criteria` together, which is the
one place in this project where both halves are read by the same author. That
is the point: a reference is only a reference if it is known-correct
independently of anything a model produced.

Every rejection names the field responsible, because the criteria require it
and a generic "invalid row" would make the output useless for the very
debugging this tool exists to support.
"""
import csv
import json
from datetime import datetime

VALID_TYPES = ("receive", "ship", "adjust")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def extract(input_path):
    """Read one input file and return its raw rows, unvalidated."""
    with open(input_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _clean_sku(row):
    sku = (row.get("sku") or "").strip()
    return sku or None


def _clean_type(row):
    """Case-insensitive by spec, and trimmed, since a padded field is a typo."""
    value = (row.get("transaction_type") or "").strip().lower()
    return value if value in VALID_TYPES else None


def _clean_quantity(row, tx_type):
    """
    A whole number, with the sign rules the criteria state.

    int() is deliberately not used on the raw string: it accepts "5" but also
    silently truncates nothing and raises on "5.0", which is the behaviour
    wanted here. A float that happens to be whole, "5.0", is still not a whole
    number as written and the criteria call non-integer values invalid.
    """
    raw = (row.get("quantity") or "").strip()
    if not raw:
        return None
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        return None
    if tx_type in ("receive", "ship"):
        return quantity if quantity > 0 else None
    if tx_type == "adjust":
        return quantity if quantity != 0 else None
    return None


def _clean_timestamp(row):
    raw = (row.get("timestamp") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, TIMESTAMP_FORMAT)
    except (TypeError, ValueError):
        return None


def _validate(row):
    """Returns (parsed, reason). Exactly one of them is None."""
    sku = _clean_sku(row)
    if sku is None:
        return None, "sku is empty or whitespace only"

    tx_type = _clean_type(row)
    if tx_type is None:
        raw = (row.get("transaction_type") or "").strip()
        return None, f"transaction_type {raw!r} is not receive, ship or adjust"

    quantity = _clean_quantity(row, tx_type)
    if quantity is None:
        raw = (row.get("quantity") or "").strip()
        if tx_type == "adjust":
            return None, f"quantity {raw!r} is not a nonzero whole number"
        return None, f"quantity {raw!r} is not a positive whole number"

    timestamp = _clean_timestamp(row)
    if timestamp is None:
        raw = (row.get("timestamp") or "").strip()
        return None, f"timestamp {raw!r} is not a valid {TIMESTAMP_FORMAT} date and time"

    return {"sku": sku, "transaction_type": tx_type, "quantity": quantity,
            "timestamp": timestamp}, None


def transform(rows):
    """
    Validate every row, then apply the valid ones in chronological order.

    Two orderings are in play and conflating them is the mistake the criteria
    warn about. Stock levels must be computed in timestamp order across BOTH
    files, because the files interleave. Ties are broken by the position a row
    held in the combined input, which is a defined rule rather than whatever
    the sort happens to do.

    The output preserves the original input order, so a reader can line the
    result up against the file they supplied. Only the processing is
    chronological.
    """
    prepared = []
    for position, row in enumerate(rows):
        parsed, reason = _validate(row)
        prepared.append({"position": position, "row": row,
                         "parsed": parsed, "reason": reason})

    stock = {}
    for item in sorted((p for p in prepared if p["parsed"]),
                       key=lambda p: (p["parsed"]["timestamp"], p["position"])):
        parsed = item["parsed"]
        delta = parsed["quantity"]
        if parsed["transaction_type"] == "ship":
            delta = -delta
        current = stock.get(parsed["sku"], 0)
        resulting = current + delta
        if resulting < 0:
            # Rejected, and the running total is left untouched by it.
            item["reason"] = (f"insufficient stock for sku {parsed['sku']}: "
                              f"{current} available, {abs(delta)} required")
            item["parsed"] = None
            continue
        stock[parsed["sku"]] = resulting
        item["resulting_stock"] = resulting

    accepted, rejected = [], []
    for item in prepared:
        if item["parsed"] is not None:
            accepted.append({**item["row"],
                             "sku": item["parsed"]["sku"],
                             "transaction_type": item["parsed"]["transaction_type"],
                             "quantity": item["parsed"]["quantity"],
                             "resulting_stock": item["resulting_stock"]})
        else:
            rejected.append({**item["row"], "reason": item["reason"]})
    return {"accepted": accepted, "rejected": rejected}


def load(data, output_path):
    """Write the result as a single JSON object."""
    import os
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)


def run_merge(input_paths, output_path):
    """Read every input, combine, validate and process, then write."""
    rows = []
    for path in input_paths:
        rows.extend(extract(path))
    load(transform(rows), output_path)
