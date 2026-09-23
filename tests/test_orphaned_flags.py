"""
A flag that modifies another flag must say so, not start a paid run.

Every modifier in this CLI is read inside its partner's dispatch branch, so on
its own it was simply never looked at. That is not harmless here: the dispatch
chain ends in a normal run, so `qikly --fresh`, meaning `qikly --scaffold X
--fresh` with the target forgotten, fell through and ran every task in the
project. The cost of a typo was a full run across every task.

`--html` has carried this check since it shipped; the others had none. These
pin the guard, one case per flag, and pin that the legitimate pairing still
reaches its command.

`--by` is deliberately not here. It carries a default, so a `--by` the user
typed cannot be told apart from the one argparse supplies, and it only chooses
how `--trends` groups rows.
"""
import pytest

from qikly import cli


def _main(argv, monkeypatch):
    """Run main() with argv and return (exit code, what it printed to stderr)."""
    monkeypatch.setattr("sys.argv", ["qikly"] + argv)
    return cli.main()


ORPHANS = [
    (["--fresh"], "--fresh", "--scaffold"),
    (["--from-doc", "feature.md"], "--from-doc", "--scaffold"),
    (["--task-id", "MY_TASK"], "--task-id", "--scaffold"),
    (["--force"], "--force", "--install-mcp"),
    (["--demo-dir", "./try-it"], "--demo-dir", "--demo"),
]


@pytest.mark.parametrize("argv,flag,partner", ORPHANS)
def test_a_modifier_on_its_own_explains_itself_and_stops(argv, flag, partner,
                                                         monkeypatch, capsys):
    code = _main(argv, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2, "%s alone should stop with 2, not run tasks" % flag
    assert flag in err and partner in err, (
        "%s alone printed %r, which does not name what it goes with" % (flag, err))


@pytest.mark.parametrize("argv,flag,partner", ORPHANS)
def test_the_guard_never_fires_on_a_real_pairing(argv, flag, partner,
                                                 monkeypatch, capsys):
    """
    The half that matters more. A guard that also blocks the correct command
    is worse than no guard, so each modifier is paired with something that
    satisfies it and the message must not appear.

    --dry-run and --validate keep this free: no model is called either way.
    """
    paired = {
        "--fresh": ["--scaffold", "missing_module.py"],
        "--from-doc": ["--scaffold", "missing_module.py"],
        "--task-id": ["--scaffold", "missing_module.py"],
        "--force": ["--install-mcp", "claude", "--dry-run"],
        "--demo-dir": ["--demo", "--validate"],
    }[flag]
    _main(paired + argv, monkeypatch)
    err = capsys.readouterr().err
    assert "goes with" not in err, (
        "the guard fired on a legitimate pairing: %r" % err)


def test_example_is_one_flag_and_needs_no_partner(monkeypatch):
    """
    --example replaced `--init --with-example`. It is an action, not a
    modifier: it adds files rather than varying what --init writes, and a
    reader whose project is already initialised should not have to type --init
    again to get it. So it must parse on its own, and --with-example must be
    gone rather than lingering as a second way to say the same thing.
    """
    monkeypatch.setattr("sys.argv", ["qikly", "--example"])
    assert cli._parse_args().example is True

    with pytest.raises(SystemExit):
        monkeypatch.setattr("sys.argv", ["qikly", "--with-example"])
        cli._parse_args()
