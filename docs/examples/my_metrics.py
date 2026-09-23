"""Summarise sensor readings into per-station daily metrics."""


def extract(input_path):
    """Read one CSV of readings and return its raw rows."""
    raise NotImplementedError


def transform(rows):
    """Validate each reading and compute per-station daily metrics."""
    raise NotImplementedError


def load(data, output_path):
    """Write the result to output_path as JSON."""
    raise NotImplementedError


def run_metrics(input_paths, output_path):
    """Run extract on each path, then transform, then load."""
    raise NotImplementedError
