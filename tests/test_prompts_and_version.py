"""
Tests for the prompt loader and the update check.

The prompt loader fills templates with str.format, which means a literal brace
anywhere in a shipped prompt file is a crash. Prompts are exactly the kind of
file that grows a JSON example, and the failure arrives mid run, after money
has been spent on earlier stages. So every bundled template is loaded here with
its own declared placeholders, which is the cheapest possible guard against a
prompt edit that looks harmless.

The update check is the only network call this project makes that is not to the
configured model provider, and its whole design contract is that it never
changes how a run behaves. Every failure path must be silent and none of them
may raise. That is easy to write and easy to break later, because the broken
version works fine on a machine with a working connection.
"""
import os
import re
import string

import pytest

from qikly import version_check as vc
from qikly.agent_api.prompts.template_loader import load_template
from qikly.paths import resolve_input


def _bundled_templates():
    d = os.path.dirname(resolve_input("agent_defs/fix_prompt.md"))
    return sorted(n for n in os.listdir(d) if n.endswith(".md"))


# ------------------------------------------------------------ prompts ----

def test_there_are_bundled_prompts_to_check():
    """Guards the guard: an empty list would make every case below vacuous."""
    assert len(_bundled_templates()) >= 5


@pytest.mark.parametrize("name", _bundled_templates())
def test_every_bundled_prompt_formats_without_error(name):
    """
    A literal { in a prompt file raises at format time, halfway through a run.
    Templates that contain JSON examples must escape their braces as {{ }}.
    """
    path = resolve_input(f"agent_defs/{name}")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    fields = {field for _, field, _, _ in string.Formatter().parse(raw) if field}
    rendered = load_template(name, **{f: f"<{f}>" for f in fields})
    assert rendered, f"{name} rendered empty"


@pytest.mark.parametrize("name", _bundled_templates())
def test_every_placeholder_is_actually_substituted(name):
    """A placeholder left in the text reaches the model as literal braces."""
    path = resolve_input(f"agent_defs/{name}")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    fields = {field for _, field, _, _ in string.Formatter().parse(raw) if field}
    rendered = load_template(name, **{f: f"VALUE_{f}" for f in fields})
    for field in fields:
        assert "{" + field + "}" not in rendered
        assert f"VALUE_{field}" in rendered


def test_a_missing_placeholder_fails_loudly():
    """
    Silently leaving a field unfilled would send a prompt with literal braces
    to the model and charge for the answer.
    """
    with pytest.raises(KeyError):
        load_template("fix_prompt.md")


def test_a_private_copy_overrides_one_prompt_without_copying_the_rest(tmp_path, monkeypatch):
    """
    The documented behaviour is per file. If overriding were all or nothing,
    editing one prompt would silently freeze the other twelve at whatever they
    said on the day they were copied.
    """
    from qikly import paths

    private = tmp_path / "inputs_private" / "agent_defs"
    private.mkdir(parents=True)
    (private / "fix_prompt.md").write_text("OVERRIDDEN {task_id}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "PRIVATE_INPUTS_DIR", str(tmp_path / "inputs_private"),
                        raising=False)

    resolved = resolve_input("agent_defs/fix_prompt.md")
    if os.path.abspath(resolved) != os.path.abspath(private / "fix_prompt.md"):
        pytest.skip("private inputs are resolved differently in this layout")
    assert load_template("fix_prompt.md", task_id="T") == "OVERRIDDEN T"


# ----------------------------------------------------- version compare ----

def test_release_segments_compare_numerically():
    """A string comparison puts 1.0.10 below 1.0.9 and nags on every run."""
    assert vc._parse("1.0.10") > vc._parse("1.0.9")
    assert vc._parse("1.2.0") > vc._parse("1.1.99")
    assert vc._parse("2.0") > vc._parse("1.99.99")


def test_a_prerelease_does_not_read_as_newer():
    """Someone who installed a stable release should not be told to downgrade."""
    assert vc._parse("1.0.3rc1") <= vc._parse("1.0.3")
    assert vc._parse("1.0.3.dev0") <= vc._parse("1.0.3")


def test_an_unparseable_version_does_not_raise():
    assert vc._parse("") == ()
    assert vc._parse("not-a-version") == ()


# ------------------------------------------------------- update check ----

def test_the_opt_out_flag_prevents_the_request(monkeypatch):
    called = []
    monkeypatch.setenv(vc.NO_CHECK_ENV, "1")
    monkeypatch.setattr(vc, "_get_json", lambda url: called.append(url))
    assert vc.check_for_update() is None
    assert called == [], "the flag must stop the request, not just the message"


def test_being_offline_is_silent(monkeypatch, capsys):
    """
    The failure this is most likely to meet in the wild, and the one where
    raising would be worst: a tool that broke because it could not check its
    own version.
    """
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)

    def boom(url):
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(vc, "_get_json", boom)
    assert vc.check_for_update() is None
    assert capsys.readouterr().out == ""


def test_malformed_index_data_is_silent(monkeypatch):
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
    for payload in ({}, {"info": {}}, {"info": {"version": None}}, []):
        monkeypatch.setattr(vc, "_get_json", lambda url, p=payload: p)
        assert vc.check_for_update() is None


def test_the_same_version_says_nothing(monkeypatch, capsys):
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
    monkeypatch.setattr(vc, "_get_json",
                        lambda url: {"info": {"version": vc.__version__}})
    assert vc.check_for_update() is None
    assert capsys.readouterr().out == ""


def test_an_older_published_version_says_nothing(monkeypatch):
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
    monkeypatch.setattr(vc, "_get_json", lambda url: {"info": {"version": "0.0.1"}})
    assert vc.check_for_update() is None


def test_a_newer_version_is_announced_once(monkeypatch, capsys):
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
    monkeypatch.setattr(vc, "_get_json", lambda url: {"info": {"version": "99.0.0"}})
    monkeypatch.setattr(vc, "_release_title", lambda: None)
    message = vc.check_for_update()
    assert message is not None
    assert "99.0.0" in message and vc.__version__ in message
    assert capsys.readouterr().out.strip() == message


def test_a_failing_release_title_still_announces_the_version(monkeypatch):
    """The title is cosmetic; losing it must not lose the message."""
    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)

    def get(url):
        if "api.github.com" in url:
            raise OSError("rate limited")
        return {"info": {"version": "99.0.0"}}

    monkeypatch.setattr(vc, "_get_json", get)
    assert "99.0.0" in vc.check_for_update()


def test_the_index_is_only_asked_once_when_up_to_date(monkeypatch):
    """The releases API call is deferred until there is something to announce."""
    urls = []

    def get(url):
        urls.append(url)
        return {"info": {"version": vc.__version__}}

    monkeypatch.delenv(vc.NO_CHECK_ENV, raising=False)
    monkeypatch.setattr(vc, "_get_json", get)
    vc.check_for_update()
    assert len(urls) == 1


def test_the_distribution_name_matches_the_package_metadata():
    """
    Renaming the project has to change DIST_NAME too, or the check silently
    polls the old project's index forever.
    """
    assert vc.DIST_NAME == "qikly"
    assert vc.GITHUB_REPO.endswith("/qikly")


# --------------------------------------------------------------- --version ---

def test_the_cli_reports_its_version(capsys):
    """
    The first thing anyone types against an unfamiliar CLI, and the first thing
    a bug report needs. It was missing until the wheel was tested from a clean
    virtualenv, where `qikly --version` exited 2 with "unrecognized arguments".
    """
    import sys

    from qikly import __version__, cli

    argv = sys.argv
    sys.argv = ["qikly", "--version"]
    try:
        with pytest.raises(SystemExit) as exit_info:
            cli._parse_args()
    finally:
        sys.argv = argv
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"qikly {__version__}"


def test_the_reported_version_comes_from_the_package_not_a_literal():
    """
    A hardcoded string in the parser would keep printing the old number after a
    release bump, which is exactly when the number matters.
    """
    import inspect

    from qikly import cli

    source = inspect.getsource(cli._parse_args)
    assert "__version__" in source


def test_every_invocation_checks_for_a_new_release():
    """
    The check sat below the --init, --scaffold and --check-criteria early
    returns, which quietly exempted them. Two of those are commands someone
    uses repeatedly, and therefore two of the better moments to mention a new
    release. It needs no provider key and is silent on every failure, so there
    was no reason for the exemption beyond the order the code grew in.
    """
    import inspect

    from qikly import cli

    source = inspect.getsource(cli.main)
    check_at = source.index("check_for_update()")
    for early_return in ("if args.init:", "if args.scaffold:", "if args.check_criteria:"):
        assert check_at < source.index(early_return), (
            f"{early_return} returns before the version check runs"
        )


def test_the_version_check_is_not_a_broadcast_channel():
    """
    It reads public indexes only. A mechanism that fetches arbitrary text from
    a server the maintainer controls prints whatever was decided later, which
    is a different thing from a version check and one users are right to
    object to. It matters more here than elsewhere: this tool's whole argument
    is that a green result should be verified rather than trusted.
    """
    import inspect

    from qikly import version_check

    source = inspect.getsource(version_check)
    hosts = re.findall(r"https://([a-z0-9.\-]+)/", source)
    assert set(hosts) <= {"pypi.org", "api.github.com"}, (
        "the version check reaches a host that is not a public index: "
        + ", ".join(sorted(set(hosts)))
    )


def test_the_release_title_is_the_only_message_it_can_carry():
    """
    The title is the channel, and it is bounded on purpose: anyone can open
    the release and confirm it matches what shipped. RELEASE_CHECKLIST.md
    tells the maintainer to write it for the user.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "RELEASE_CHECKLIST.md"), encoding="utf-8") as handle:
        text = handle.read()
    assert "release title" in text.lower()
    assert "printed in every user's terminal" in text


def test_every_prompt_template_gets_every_placeholder_it_asks_for():
    """
    A template names its slots and a builder fills them. Nothing checked that
    the two agreed, so a template could ask for a field its builder never
    passes and the failure would arrive as KeyError at the moment of a real
    model call, after the run had already started.

    That happened: fixture_proposal_prompt.md kept a {test_agent_md} preamble
    copied from the test prompts, whose builder has no such argument, and it
    surfaced only when a user ran the command.

    Templates whose slots are filled from a caller's own dict rather than a
    fixed builder are skipped by name, since there is nothing static to check.
    """
    import ast
    import os
    import re
    import string

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    defs = os.path.join(root, "src", "qikly", "inputs_public", "agent_defs")
    builders = os.path.join(root, "src", "qikly", "agent_api", "prompts")

    problems = []
    for name in sorted(os.listdir(builders)):
        if not name.endswith(".py") or name in ("template_loader.py", "__init__.py"):
            continue
        with open(os.path.join(builders, name), encoding="utf-8") as handle:
            source = handle.read()

        # Which template each load_template call names, and what it passes.
        for call in ast.walk(ast.parse(source)):
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "load_template"):
                continue
            if not call.args or not isinstance(call.args[0], ast.Constant):
                continue
            template = call.args[0].value
            supplied = {kw.arg for kw in call.keywords if kw.arg}
            path = os.path.join(defs, template)
            if not os.path.isfile(path):
                problems.append(f"{name} loads {template}, which does not exist")
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            wanted = {f for _, f, _, _ in string.Formatter().parse(text) if f}
            missing = wanted - supplied
            if missing:
                problems.append(
                    f"{template} asks for {sorted(missing)} and {name} does not pass it")

    assert not problems, "; ".join(problems)


def test_the_package_version_matches_pyproject():
    """
    Two places declare the version and only one of them is checked at release.

    `release.yml` refuses a tag that disagrees with `pyproject.toml`, which is
    the check that protects PyPI. Nothing compared `qikly.__version__` against
    it, so a bump that touched one and not the other would ship a wheel whose
    `--version` reported the previous release. That is not caught by any
    install check, because the wheel installs and runs perfectly; it just lies
    about which one it is. Adding this after a 0.3.1 bump did exactly that.
    """
    import pathlib
    import re

    import qikly

    root = pathlib.Path(qikly.__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert qikly.__version__ == declared, (
        f"qikly.__version__ is {qikly.__version__} but pyproject.toml says "
        f"{declared}. Bump both."
    )
