"""
`--scaffold` starts the data file for code that is called with values.

The step people stopped at after `--scaffold` was the data file: what goes in
it, and whether it has a header line. For code called with values the header
is one column per argument, so it is written for them; the rows have to be
real and are left to them.
"""
import os

from qikly import cli, scaffold

PRICING = ('def apply_discount(price, rate):\n'
           '    if rate < 0 or rate > 100:\n'
           '        raise ValueError("rate out of range")\n'
           '    return round(price * (1 - rate / 100), 2)\n\n\n'
           'def label(code):\n'
           '    return "gold" if code.strip().lower() == "vip" else "standard"\n')


def _data(tmp_path):
    return tmp_path / "inputs_private" / "data" / "PRICING" / "input_01.csv"


def _scaffold(tmp_path, monkeypatch, source=PRICING):
    (tmp_path / "pricing.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("pricing.py", None) == 0


def test_the_header_is_the_arguments_in_order_and_there_are_no_rows(
        tmp_path, monkeypatch, capsys):
    _scaffold(tmp_path, monkeypatch)
    assert _data(tmp_path).read_text(encoding="utf-8") == "price,rate,code\n"
    out = capsys.readouterr().out
    assert "add a few example rows" in out
    assert str(_data(tmp_path)) in out, "the file is named in full"


def test_data_that_is_already_there_is_left_alone(tmp_path, monkeypatch, capsys):
    _data(tmp_path).parent.mkdir(parents=True)
    _data(tmp_path).write_text("price,rate\n80,25\n", encoding="utf-8")
    _scaffold(tmp_path, monkeypatch)
    assert _data(tmp_path).read_text(encoding="utf-8") == "price,rate\n80,25\n"
    assert "add a few example rows" not in capsys.readouterr().out


def test_code_that_is_given_a_file_gets_no_made_up_header(
        tmp_path, monkeypatch, capsys):
    _scaffold(tmp_path, monkeypatch,
              "def load(input_path):\n    return open(input_path).read()\n")
    assert not _data(tmp_path).exists()
    assert "header line included if it has one" in capsys.readouterr().out


def test_starter_columns_skips_self_and_repeats():
    source = ("def a(x, y):\n    pass\n\n"
              "def b(y, z=1, *rest, k=2, **more):\n    pass\n\n"
              "def _hidden(secret):\n    pass\n")
    assert scaffold.starter_columns(source) == ["x", "y", "z", "k"]
    assert scaffold.starter_columns("def f():\n    pass\n") == []


# ------------------------------------------- found by the audit, 2026-10-15 --

def test_names_that_merely_contain_a_file_word_are_values():
    source = ("def heading(direction, fps, offpeak_rate, profile_id):\n"
              "    pass\n\n"
              "def save(result, output_path):\n    pass\n")
    assert scaffold.starter_columns(source) == [
        "direction", "fps", "offpeak_rate", "profile_id", "result"]
    assert scaffold.starter_columns("def load(input_path):\n    pass\n") is None


def test_a_header_only_data_file_draws_a_validate_warning(
        tmp_path, monkeypatch, capsys):
    from qikly import validate
    _scaffold(tmp_path, monkeypatch)
    task = tmp_path / "inputs_private" / "config" / "tasks" / "PRICING_VERIFY.yaml"
    monkeypatch.chdir(tmp_path)
    errors, warnings = validate.check_task(str(task))
    assert any("only its header line" in w for w in warnings), warnings
    _data(tmp_path).write_text("price,rate,code\n80,25,vip\n", encoding="utf-8")
    errors, warnings = validate.check_task(str(task))
    assert not any("only its header line" in w for w in warnings), warnings


def test_a_bundled_example_s_data_folder_is_never_written(
        tmp_path, monkeypatch, capsys):
    """calc_tax.py names CALC_TAX, whose fixture ships with qikly."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "calc_tax.py").write_text(
        "def tax(subtotal, region):\n    return subtotal\n", encoding="utf-8")
    monkeypatch.setattr(cli, "INVOKED_FROM", str(tmp_path))
    assert cli._do_scaffold("calc_tax.py", None) == 0
    assert not (tmp_path / "inputs_private" / "data" / "CALC_TAX").exists()
    assert "--task-id" in capsys.readouterr().out
