"""
Summarise sensor readings into per-station daily metrics.

The module you already have, as scaffold sees it: four signatures and no
implementation. Scaffold reads the signatures and never the bodies, so the
`TODO` in each one is for you rather than for the tool. Each says what is
expected there, with an example of the shape an answer takes.
"""


def extract(input_path):
    """Read one CSV of readings and return its raw rows."""
    # TODO: your implementation. Expected: reading, no judgement.
    # e.g. open input_path with csv.DictReader and return a list of one dict
    # per row, keeping every value as the string the file held.
    raise NotImplementedError


def transform(rows):
    """Validate each reading and compute per-station daily metrics."""
    # TODO: your implementation. Expected: every decision your requirements
    # name, applied here.
    # e.g. drop a row whose temp_c is empty or non-numeric, drop a humidity_pct
    # above 100, then group what survives by station_id and calendar day and
    # return min, max and mean temperature for each group.
    raise NotImplementedError


def load(data, output_path):
    """Write the result to output_path as JSON."""
    # TODO: your implementation. Expected: writing, no judgement.
    # e.g. json.dump(data, handle, indent=2, sort_keys=True), creating the
    # parent directory if it is missing.
    raise NotImplementedError


def run_metrics(input_paths, output_path):
    """Run extract on each path, then transform, then load."""
    # TODO: your implementation. Expected: the wiring, and nothing else.
    # e.g. extract each path in input_paths, concatenate the rows, pass them
    # through transform once, and hand the result to load.
    raise NotImplementedError
