"""
A check for a newer release, run once per invocation. This is the one network
call this project makes that is not to your configured LLM provider.

Design constraints, in the order they mattered:

**It must never change how a run behaves.** Every failure path is silent. No
network, a proxy that refuses, DNS failure, a rate limit, malformed JSON: all
mean no message and nothing else. A tool that failed because it could not check
its own version would be worse than one that never checked.

**It must not be a channel.** It reads the public package index and the public
releases API, both of which users already understand as part of installing
software. It does not fetch arbitrary text from a server the maintainer
controls: a mechanism that prints whatever the maintainer decides later is a
different thing from a version check, and users are right to object to it.

**Once per invocation, not once per task.** Called from the CLI entry point, so
a sweep of ten tasks, or `run_all --repeat 10`, still checks once. Spawned child
processes inherit QIKLY_NO_VERSION_CHECK so they stay quiet. There is deliberately
no cache: a run costs real money in model calls and takes tens of seconds, so
one request with a short timeout is noise, and a cache file would add staleness
and a failure mode in exchange for saving something that costs nothing.

**One flag switches it off.** See NO_CHECK_ENV.
"""
import json
import os
import urllib.request

from qikly import __version__

# Renaming the project changes these two lines and nothing else here.
DIST_NAME = "qikly"
GITHUB_REPO = "gal-a/qikly"

NO_CHECK_ENV = "QIKLY_NO_VERSION_CHECK"
TIMEOUT_SECONDS = 1.5  # a slow index must not visibly delay a run


def _get_json(url):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": f"{DIST_NAME}/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.load(resp)


def _parse(version):
    """
    Compare release segments numerically, so 1.0.10 sorts above 1.0.9 where a
    string comparison would not. A non-numeric suffix (rc, dev, post) ends the
    parse rather than being interpreted: this only needs to answer "is there
    something newer", and treating a prerelease as newer would nag people who
    deliberately installed a stable version.
    """
    parts = []
    for chunk in str(version).split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _release_title():
    """The GitHub release name, or None. Cosmetic, so failure is fine."""
    try:
        data = _get_json(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
        return ((data.get("name") or "").strip()) or None
    except Exception:
        return None


def check_for_update():
    """
    Print one line if a newer release exists. Returns the message printed, or
    None, so callers and tests can assert on it without capturing stdout.
    """
    if os.environ.get(NO_CHECK_ENV):
        return None

    try:
        latest = _get_json(f"https://pypi.org/pypi/{DIST_NAME}/json")["info"]["version"]
    except Exception:
        return None  # offline, blocked, unpublished, rate limited: say nothing

    if not latest or _parse(latest) <= _parse(__version__):
        return None

    # Only now is there something to announce, so only now is the second
    # request worth making.
    title = _release_title()
    suffix = f" + {title}" if title else ""
    message = f"{DIST_NAME} {latest} is available{suffix} (you have {__version__})"
    print(message)
    return message
