"""
Tests for counting what a run costs and stopping it at a limit.

The unit of work is a loop of model calls that can run for hours, and nothing
counted them until now. A run that dies partway through a provider's limit
throws away everything it already paid for, which happened twice in two days
on this project alone.

Two properties matter more than the arithmetic. The cap counts CALLS, not the
money estimate, because a limit that depends on a price table staying current
is a limit that fails quietly. And nothing here may raise: a missing token
count costs a number in a summary line, while an exception would cost the run.
"""
import pytest

from qikly.agent_api import usage as u


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(u, "USAGE", u.Usage())
    monkeypatch.delenv(u.MAX_CALLS_ENV, raising=False)


class _Block:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, block, attr="usage_metadata"):
        setattr(self, attr, block)


# ---------------------------------------------------------------- counting --

def test_calls_and_tokens_accumulate():
    us = u.Usage()
    us.record("gemini-3.5-flash-lite", 100, 20)
    us.record("gemini-3.5-flash-lite", 50, 10)
    assert us.calls == 2
    assert us.input_tokens == 150 and us.output_tokens == 30


def test_usage_is_broken_down_by_model():
    us = u.Usage()
    us.record("a", 10, 1)
    us.record("b", 20, 2)
    assert us.by_model["a"]["calls"] == 1
    assert us.by_model["b"]["in"] == 20


def test_a_model_with_no_price_contributes_nothing_rather_than_a_guess():
    """
    The estimate is a floor. Inventing a price for an unknown model would make
    it a fiction instead.
    """
    us = u.Usage()
    us.record("some-model-nobody-priced", 1_000_000, 1_000_000)
    assert us.estimated_usd() == 0.0
    assert us.priced_fraction() == 0.0


def test_the_estimate_uses_input_and_output_rates_separately():
    us = u.Usage()
    us.record("gemini-3.5-flash-lite", 1_000_000, 1_000_000)
    assert us.estimated_usd() == pytest.approx(0.10 + 0.40)


def test_the_summary_says_the_money_is_an_estimate():
    us = u.Usage()
    us.record("gemini-3.5-flash-lite", 1_000_000, 0)
    assert "estimated" in us.summary()


def test_the_summary_flags_partial_price_coverage():
    us = u.Usage()
    us.record("gemini-3.5-flash-lite", 1_000_000, 0)
    us.record("unpriced-model", 1_000_000, 0)
    assert "50%" in us.summary()


def test_no_calls_reads_as_no_calls():
    assert "No model calls" in u.Usage().summary()


# ------------------------------------------------------------------- caps ---

def test_no_limit_by_default():
    assert u.call_limit() == 0
    us = u.Usage()
    for _ in range(50):
        us.record("m", 1, 1)
        us.check_limit()


def test_a_limit_stops_the_run_and_says_nothing_was_lost(monkeypatch):
    monkeypatch.setenv(u.MAX_CALLS_ENV, "3")
    us = u.Usage()
    for _ in range(2):
        us.record("m", 1, 1)
        us.check_limit()
    us.record("m", 1, 1)
    with pytest.raises(u.BudgetExceeded, match="Nothing is lost"):
        us.check_limit()


def test_a_malformed_limit_is_treated_as_no_limit(monkeypatch):
    """A typo in an env var must not silently cap a long run at zero."""
    for bad in ("", "lots", "-5", "3.7"):
        monkeypatch.setenv(u.MAX_CALLS_ENV, bad)
        assert u.call_limit() in (0, 3) if bad == "3.7" else u.call_limit() == 0


# ------------------------------------------------- reading the SDK response --

def test_gemini_style_token_counts_are_read():
    r = _Resp(_Block(prompt_token_count=120, candidates_token_count=30))
    assert u.extract_tokens(r) == (120, 30)


def test_openai_style_token_counts_are_read():
    r = _Resp(_Block(prompt_tokens=7, completion_tokens=3), attr="usage")
    assert u.extract_tokens(r) == (7, 3)


def test_anthropic_style_token_counts_are_read():
    r = _Resp(_Block(input_tokens=5, output_tokens=9), attr="usage")
    assert u.extract_tokens(r) == (5, 9)


def test_a_response_with_no_usage_block_yields_zeros_not_an_error():
    assert u.extract_tokens(object()) == (0, 0)
    assert u.extract_tokens(None) == (0, 0)


def test_recording_never_raises_on_a_strange_response():
    """An exception here would cost the run to save a number in a summary."""
    u.record_usage("m", object())
    u.record_usage(None, None)


# --------------------------------------------------- reporting what it cost --

def test_a_small_real_cost_is_not_printed_as_zero(tmp_path):
    """
    Two decimals hides exactly the runs people want reassurance about. A real
    cost of $0.0049 printed as "$0.00" reads as free rather than as cheap, and
    a genuine zero would print identically.
    """
    from qikly.agent_api.usage import Usage

    acc = Usage()
    acc.record("gemini-3.5-pro", 1000, 200)
    assert "$0.00 " not in acc.summary()
    assert "$0.0033" in acc.summary()


def test_a_single_model_run_does_not_repeat_itself_in_a_breakdown():
    from qikly.agent_api.usage import Usage

    acc = Usage()
    acc.record("gemini-3.5-pro", 10, 10)
    assert acc.breakdown() == []


def test_a_multi_model_run_reports_each_one_and_flags_the_unpriced():
    from qikly.agent_api.usage import Usage

    acc = Usage()
    acc.record("gemini-3.5-pro", 1000, 200)
    acc.record("nobody-priced-this", 10, 10)
    lines = "\n".join(acc.breakdown())
    assert "gemini-3.5-pro" in lines
    assert "unpriced" in lines, "a guessed price is worse than no price"


def test_totals_survive_the_process_boundary(tmp_path, monkeypatch):
    """
    Each task runs in its own process and --demo spawns the whole run as a
    child, so the printed line is the only record a parent would otherwise
    have, and by then it is text. Without a file on disk the demo reports a
    cost of zero for work it just paid for.
    """
    from qikly.agent_api import usage as u

    monkeypatch.chdir(tmp_path)
    acc = u.Usage()
    acc.record("gemini-3.5-pro", 1000, 200)
    acc.record("gemini-3.5-pro", 500, 100)
    assert u.write_record("TASK_A", acc) is not None

    other = u.Usage()
    other.record("claude-opus-5", 300, 50)
    assert u.write_record("TASK_B", other) is not None

    total = u.read_records(str(tmp_path))
    assert total.calls == 3
    assert total.input_tokens == 1800
    assert total.output_tokens == 350
    assert set(total.by_model) == {"gemini-3.5-pro", "claude-opus-5"}


def test_a_root_that_never_ran_sums_to_nothing_rather_than_failing(tmp_path):
    from qikly.agent_api.usage import read_records

    total = read_records(str(tmp_path))
    assert total.calls == 0
    assert total.summary() == "No model calls were made."


def test_an_unreadable_record_costs_the_record_not_the_summary(tmp_path, monkeypatch):
    import os

    from qikly.agent_api import usage as u

    monkeypatch.chdir(tmp_path)
    good = u.Usage()
    good.record("gemini-3.5-pro", 100, 10)
    u.write_record("GOOD", good)
    with open(os.path.join(tmp_path, u.REPORT_DIR, "broken.json"), "w",
              encoding="utf-8") as handle:
        handle.write("{not json")

    total = u.read_records(str(tmp_path))
    assert total.calls == 1, "one bad receipt must not empty the summary"


def test_filing_a_receipt_never_costs_the_run(monkeypatch, tmp_path):
    """
    A run that produced real output must not fail while recording what it
    spent. write_record returns None instead of raising.
    """
    from qikly.agent_api import usage as u

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(u.os, "makedirs",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert u.write_record("TASK") is None
