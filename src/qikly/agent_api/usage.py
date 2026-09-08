"""
What a run cost, and stopping it before it costs more than you meant.

The unit of work here is a loop of model calls that can run for hours, and
until now nothing counted them. No estimate before, no cap during, no total
after. That is not a reporting nicety: a run that dies partway through a
provider's limit throws away everything it already paid for, and the only
warning is the failure itself.

Two numbers are kept, and they are different in kind. Calls and tokens are
counted, because the providers report them. Money is *estimated* from a price
table that will drift, so it is always labelled as an estimate and never used
for anything except showing a person roughly where they are.

The cap is enforced on calls, not on the estimate, because a limit that
depends on a price table going stale is a limit that fails quietly.
"""
import os
import threading

# Rough prices per million tokens, input and output. Wrong the moment a
# provider changes them, which is why nothing depends on them being right:
# they produce a number with "estimated" attached, and the cap counts calls.
PRICES = {
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.5-pro": (1.25, 10.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (2.50, 10.00),
}

MAX_CALLS_ENV = "QIKLY_MAX_CALLS"


class BudgetExceeded(RuntimeError):
    """Raised when a run reaches the call limit it was given."""


class Usage:
    """Running totals for one process. Thread safe, since stages may overlap."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.by_model = {}

    def record(self, model, input_tokens=0, output_tokens=0):
        with self._lock:
            self.calls += 1
            self.input_tokens += int(input_tokens or 0)
            self.output_tokens += int(output_tokens or 0)
            slot = self.by_model.setdefault(model or "unknown",
                                            {"calls": 0, "in": 0, "out": 0})
            slot["calls"] += 1
            slot["in"] += int(input_tokens or 0)
            slot["out"] += int(output_tokens or 0)

    def estimated_usd(self):
        """
        Best effort, and only that. A model with no price entry contributes
        nothing rather than a guess, so the estimate is a floor and says so.
        """
        total = 0.0
        for model, s in self.by_model.items():
            price = PRICES.get(model)
            if not price:
                continue
            total += s["in"] / 1e6 * price[0] + s["out"] / 1e6 * price[1]
        return total

    def priced_fraction(self):
        """How much of the usage the price table actually covers."""
        if not self.calls:
            return 1.0
        known = sum(s["calls"] for m, s in self.by_model.items() if m in PRICES)
        return known / self.calls

    def check_limit(self):
        limit = call_limit()
        if limit and self.calls >= limit:
            raise BudgetExceeded(
                f"stopped after {self.calls} model calls, the limit set by "
                f"{MAX_CALLS_ENV}. Nothing is lost: the run's outputs, reports and "
                f"logs are on disk up to this point. Raise or unset {MAX_CALLS_ENV} "
                f"to continue further next time.")

    @staticmethod
    def _money(usd):
        """
        Two decimals hides exactly the runs people most want reassurance about:
        a real cost of $0.0049 printed as "$0.00" reads as free rather than as
        cheap, and the same rounding would print a genuine zero identically.
        """
        if usd >= 0.01:
            return f"${usd:.2f}"
        return f"${usd:.4f}"

    def summary(self):
        if not self.calls:
            return "No model calls were made."
        parts = [f"{self.calls} model call(s)",
                 f"{self.input_tokens:,} in / {self.output_tokens:,} out tokens"]
        usd = self.estimated_usd()
        if usd:
            covered = self.priced_fraction()
            note = "" if covered > 0.99 else f", covering {covered:.0%} of calls"
            parts.append(f"about {self._money(usd)} estimated from a "
                         f"static price table{note}")
        return "Usage: " + "; ".join(parts) + "."

    def breakdown(self):
        """
        One line per model, for a run that used more than one. A single-model
        run says nothing here that summary() has not already said, so it
        returns nothing rather than repeating itself.
        """
        if len(self.by_model) < 2:
            return []
        lines = []
        for model in sorted(self.by_model, key=lambda m: -self.by_model[m]["calls"]):
            counts = self.by_model[model]
            priced = model in PRICES
            money = ""
            if priced:
                rate_in, rate_out = PRICES[model]
                cost = (counts["in"] * rate_in + counts["out"] * rate_out) / 1_000_000
                money = f"  about {self._money(cost)}"
            else:
                money = "  unpriced"
            lines.append(f"  {model:<24}{counts['calls']:>4} calls  "
                         f"{counts['in']:>9,} in {counts['out']:>8,} out{money}")
        return lines


    def as_dict(self):
        return {"calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_usd": round(self.estimated_usd(), 4),
                "priced_fraction": round(self.priced_fraction(), 4),
                "by_model": {m: dict(v) for m, v in self.by_model.items()}}


USAGE = Usage()

REPORT_DIR = os.path.join("outputs", "reports", "usage")


def write_record(task_id, accumulator=None):
    """
    Leave this process's totals on disk, so a parent can add them up.

    Each task runs in its own process and each prints its own total, which is
    fine to read but impossible to sum: by the time the parent sees the line
    it is text. `--demo` spawns the whole run as a child, so without a file on
    disk the demo can only report a cost of zero for work it just paid for.

    Returns the path written, or None. Never raises: a run that produced real
    output must not fail while filing a receipt for it.
    """
    import json
    from datetime import datetime

    acc = accumulator if accumulator is not None else USAGE
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(REPORT_DIR, f"{task_id}_{stamp}.json")
        payload = {"task": task_id, **acc.as_dict()}
        with open(path, "w", encoding="utf-8", newline='\n') as handle:
            json.dump(payload, handle, indent=2)
        return path
    except Exception:
        return None


def read_records(root):
    """
    Every usage record under one project root, summed into a fresh Usage.

    Used by --demo, which reads the records its own child processes wrote
    inside the throwaway demo directory. A missing directory sums to nothing
    rather than failing, because a run that never started has no cost to
    report and that is not an error. A record that will not parse is skipped
    for the same reason: an unreadable receipt should cost you the receipt,
    not the summary.
    """
    import json

    total = Usage()
    directory = os.path.join(root, REPORT_DIR)
    if not os.path.isdir(directory):
        return total
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        for model, counts in (data.get("by_model") or {}).items():
            slot = total.by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0})
            slot["calls"] += int(counts.get("calls") or 0)
            slot["in"] += int(counts.get("in") or 0)
            slot["out"] += int(counts.get("out") or 0)
            total.calls += int(counts.get("calls") or 0)
            total.input_tokens += int(counts.get("in") or 0)
            total.output_tokens += int(counts.get("out") or 0)
    return total


def call_limit():
    """Maximum model calls for this process, or 0 for no limit."""
    try:
        return max(0, int(os.environ.get(MAX_CALLS_ENV) or 0))
    except (TypeError, ValueError):
        return 0


def extract_tokens(response):
    """
    Pull input and output token counts out of whatever the SDK returned.

    Every provider names this differently and any of them may omit it, so
    this returns zeros rather than raising. A missing count costs a number in
    a summary line; an exception here would cost the run.
    """
    for attr in ("usage_metadata", "usage"):
        block = getattr(response, attr, None)
        if block is None and isinstance(response, dict):
            block = response.get(attr)
        if block is None:
            continue
        def _get(*names):
            for n in names:
                v = getattr(block, n, None)
                if v is None and isinstance(block, dict):
                    v = block.get(n)
                if isinstance(v, (int, float)):
                    return int(v)
            return 0
        return (_get("prompt_token_count", "input_tokens", "prompt_tokens"),
                _get("candidates_token_count", "output_tokens", "completion_tokens"))
    return (0, 0)


def record_usage(model, response):
    """
    Count one call, then stop the run if it has reached its limit.

    The limit is checked after recording rather than before, so the call that
    reaches it still returns its answer and the work it did is not thrown
    away. Stopping is deliberate and loud: the alternative is discovering the
    cost from a provider dashboard the next morning.
    """
    try:
        USAGE.record(model, *extract_tokens(response))
    except Exception:
        pass
    USAGE.check_limit()
