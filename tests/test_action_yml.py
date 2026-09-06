"""
The GitHub Action, checked against the code it drives.

An action file is the one thing in this repository that nothing executes
locally. Its paths, its environment variable names and its flags are all
strings, and every one of them can rot without a single test failing, until
someone's workflow uploads an empty artifact and they conclude the tool does
not work.

That already nearly happened here: the first version uploaded
`outputs/generated_tests/` and `outputs/generated_code/`, neither of which
exists. The real directories are `outputs/tests/` and `outputs/agent_src/`.
Nothing would have caught it.
"""
import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def action():
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _run_step(action):
    return next(s for s in action["runs"]["steps"] if s.get("id") == "run")


def test_it_is_a_composite_action_with_the_documented_outputs(action):
    assert action["runs"]["using"] == "composite"
    assert set(action["outputs"]) == {"junit-xml", "converged"}


def test_every_directory_it_uploads_is_one_the_code_writes(action):
    """
    The check that would have caught the original mistake. Each path is
    compared against the constant the code actually uses, not against a second
    copy of the same guess.
    """
    from qikly.agent_tools import junit
    from qikly.orchestrator import orchestrator

    upload = next(s for s in action["runs"]["steps"]
                  if s.get("uses", "").startswith("actions/upload-artifact"))
    paths = [p.strip().rstrip("/") for p in upload["with"]["path"].split("\n") if p.strip()]

    assert orchestrator.GENERATED_TESTS_ROOT in paths, (
        f"the generated suite lives in {orchestrator.GENERATED_TESTS_ROOT}, "
        f"which the action does not upload: {paths}")
    # The JUnit directory has to be inside something uploaded, or the one
    # artifact another system can read never leaves the runner.
    assert any(junit.JUNIT_DIR.startswith(p + "/") or junit.JUNIT_DIR == p
               for p in paths), (
        f"{junit.JUNIT_DIR} is not covered by any uploaded path: {paths}")


def test_the_junit_glob_excludes_the_per_stage_files(action):
    """
    Both the merged document and the per-stage files sit in one directory, and
    the merged one is the run-level answer. Handing an importer a single stage
    would report part of a run as the whole of it.
    """
    from qikly.orchestrator.orchestrator import resolve_stage_order

    script = _run_step(action)["run"]
    for stage in resolve_stage_order({}):
        assert stage in script, (
            f"stage {stage!r} is not excluded by the action's JUnit glob, so a "
            f"per-stage file could be reported as the run's result")


def test_the_version_check_is_disabled_by_the_real_variable_name(action):
    """A typo here is silent: the check simply runs, on every job, forever."""
    from qikly.version_check import NO_CHECK_ENV

    assert NO_CHECK_ENV in _run_step(action)["env"]


def test_the_provider_variables_match_what_the_code_reads(action):
    env = _run_step(action)["env"]
    for name in ("LLM_PROVIDER", "LLM_MODEL"):
        assert name in env, f"{name} is not passed through"


def test_a_stall_does_not_fail_the_build_by_default(action):
    """
    A run that does not converge is an expected outcome rather than a broken
    pipeline. A tool whose first impression is a red X on someone's main branch
    does not get a second look, so enforcement is opt-in.
    """
    assert action["inputs"]["fail-on-stall"]["default"] == "false"
    assert "fail-on-stall" in _run_step(action)["run"]


def test_the_api_key_is_required_and_never_defaulted(action):
    key = action["inputs"]["api-key"]
    assert key["required"] is True
    assert "default" not in key, "an API key must never have a default"


def test_the_exit_code_survives_the_pipe_to_tee(action):
    """
    `qikly | tee log` reports tee's status, not qikly's, so without this the
    action would call every run converged. The console log is worth having, so
    the fix is to read PIPESTATUS rather than to drop the pipe.
    """
    script = _run_step(action)["run"]
    assert "PIPESTATUS" in script or "pipefail" in script


def test_every_documented_repo_url_points_at_the_real_one():
    """
    Six places named `qikly/qikly`, an owner that does not exist. Four were
    prose links; two were `uses:` lines in workflow templates, where a wrong
    owner does not fail loudly, it fails on a stranger's first CI run with
    "unable to resolve action".

    A seventh survived in `.pre-commit-hooks.yaml`, which this test did not
    read, so the file list now covers every place that names the repo: the
    hook template a stranger copies, and `pyproject.toml`, whose Homepage is
    what PyPI renders.

    The owner is read from the code rather than repeated here, per MAINTAIN's
    rule: anything referenced by string gets a test resolving it against the
    real thing, never against a second copy of the same guess.
    """
    import glob
    import re

    from qikly.version_check import GITHUB_REPO

    owner = GITHUB_REPO.split("/")[0]
    bad = {}
    for path in (["README.md", "action.yml", "pyproject.toml",
                  ".pre-commit-hooks.yaml"] + glob.glob("docs/*.md")
                 + ["docs/index.html"] + glob.glob(".github/workflows/*.yml")):
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            text = handle.read()
        # Two different questions. A github.com link in prose should be this
        # project's. A `uses:` line may legitimately name somebody else's
        # action, so only one naming a repo called qikly under the wrong owner
        # is a mistake.
        wrong = sorted(
            {m for m in re.findall(r"github\.com/([\w.-]+/[\w.-]+)", text)
             if not m.startswith(owner + "/")}
            | {m for m in re.findall(r"uses:\s*([\w.-]+/[\w.-]+)", text)
               if m.split("/")[-1] == "qikly" and not m.startswith(owner + "/")})
        if wrong:
            bad[path] = wrong
    assert not bad, f"documents naming a repo that is not {owner}'s: {bad}"


def test_pyproject_and_the_version_check_agree_on_the_repo():
    """
    The update notice reads GitHub for a release title, and pyproject tells
    PyPI where the project lives. Two names for one repository is how a link
    on a package page goes to a 404.
    """
    from qikly.version_check import GITHUB_REPO

    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
        text = handle.read()
    assert f"github.com/{GITHUB_REPO}" in text
