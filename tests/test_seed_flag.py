"""
--seed: independent samples without editing an environment variable.

Every model call reads AGENT_SEED, default 42. Three runs of jambo's task
under the default wrote byte-identical tests, so a study that meant to take
three samples took one. --seed sets AGENT_SEED before any command runs.
"""
import os
import sys

from qikly import cli


def _seed_seen_by_a_command(monkeypatch, argv):
    seen = {}

    def fake(host):
        seen["seed"] = os.environ.get("AGENT_SEED")
        return 0
    monkeypatch.setattr(cli, "_do_mcp_config", fake)
    monkeypatch.setattr(sys, "argv", ["qikly", *argv, "--mcp-config", "claude"])
    assert cli.main() == 0
    return seen["seed"]


def test_seed_sets_agent_seed_before_the_command_runs(monkeypatch):
    monkeypatch.delenv("AGENT_SEED", raising=False)
    assert _seed_seen_by_a_command(monkeypatch, ["--seed", "7"]) == "7"


def test_without_seed_the_environment_is_left_alone(monkeypatch):
    monkeypatch.setenv("AGENT_SEED", "3")
    assert _seed_seen_by_a_command(monkeypatch, []) == "3"
