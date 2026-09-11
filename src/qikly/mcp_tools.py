"""
What an MCP host is allowed to ask qikly, and what it gets back.

These are plain functions returning plain dictionaries. The protocol wrapper
lives in `mcp_server.py` and does nothing but expose them, so the behaviour can
be tested without the SDK installed and without a protocol handshake.

**The rule this module exists to keep.** An MCP host is usually running its own
coding agent, and whatever a tool returns becomes that agent's context. So no
response here may contain acceptance criteria, or the key they live under. That
is the same property `tests/test_withholding.py` guards on the prompt path,
except that none of those tests can see this boundary: they watch the prompts,
and this is a tool response. `tests/test_mcp_withholding.py` watches this one,
and it asserts on the serialised JSON rather than the dict, because a dict that
holds the criteria under a key nobody prints is still a leak the moment
anything serialises it.

A failing run is where this is hardest. That is exactly when a helpful tool
wants to explain *why*, and "why" is the criterion. The host's agent may see
the error text. It may never see the rule it broke. That is the whole product.

**Where this boundary stops, stated plainly.** These tools control what a
*response* contains. They cannot control what the host's agent reads off disk,
and the generated tests under `outputs/tests/` are derived from the criteria.
An agent that opens them has the answer key, and no tool response was involved.

That matters more here than it looks, because the natural way to use this
server is to let the same agent both write the code and call `qikly_run`. If
that agent then reads the generated tests, the property is gone: not through a
leak, but because the user pointed it at the file.

So the responses are built to avoid handing over the route. `status` copies an
allowlist out of the transaction log rather than the whole row, because those
rows carry `test_path` and full failure text; `tests/test_runs.py` pins that
allowlist, since widening it to `update(last)` looks like a tidy-up and is not.
What the responses cannot do is stop a determined or careless reader, so
`docs/mcp.md` tells the user to exclude `outputs/tests/` from their agent's
reach. A mechanism where one exists, and a plain warning where none can.
"""
import os
import re

from qikly import runs

# Every tool, in one place, so the withholding tests can assert the list they
# cover matches the list that exists. A tool added without a test is a tool
# nobody has shown is safe.
TOOLS = ("qikly_run", "qikly_status", "qikly_check_criteria", "qikly_scaffold")


def _error(message, **extra):
    out = {"ok": False, "error": message}
    out.update(extra)
    return out


def qikly_run(task_id, provider=None, model=None):
    """
    Start a run and return its id immediately.

    It does not wait. A run takes minutes to hours and a tool call that blocks
    for that long is killed by the host, so the id is the answer and
    `qikly_status` is how the caller finds out what happened.

    The response deliberately does not echo the task back. Naming a task is the
    obvious convenience and it is the exact thing that would put the criteria
    in front of the host's agent.
    """
    if not task_id or not isinstance(task_id, str):
        return _error("task_id is required")

    env = None
    if provider or model:
        env = dict(os.environ)
        if provider:
            env["LLM_PROVIDER"] = provider
        if model:
            env["LLM_MODEL"] = model
        # A stale generic key outranks the provider's own and is never
        # overwritten, so switching provider without clearing it hands the
        # previous provider's key to the new one.
        if provider:
            env.pop("API_KEY", None)

    try:
        run_id = runs.start(task_id, env=env)
    except Exception as exc:                       # noqa: BLE001 - reported, not raised
        return _error("could not start the run: %s" % exc)

    return {"ok": True, "run_id": run_id, "state": "running",
            "next": "call qikly_status with this run_id"}


def qikly_status(run_id):
    """
    What is happening, or what happened, to one run.

    Everything here is derived from what the run itself wrote, so it is correct
    even when the process died: `stalled` means gone without a summary, which
    is a crash rather than a failing suite, and the two deserve different
    answers.
    """
    if not run_id or not isinstance(run_id, str):
        return _error("run_id is required")
    try:
        info = dict(runs.status(run_id))
    except Exception as exc:                       # noqa: BLE001
        return _error("could not read that run: %s" % exc)

    info["ok"] = info.get("state") != "unknown"
    return _redact(info)


def qikly_check_criteria(task_id):
    """
    Whether a task's criteria are usable, without quoting them.

    The tool is *about* the criteria, which makes it the easiest place in the
    whole surface to justify returning their text. A verdict is not the text,
    and only the verdict crosses this boundary.
    """
    if not task_id or not isinstance(task_id, str):
        return _error("task_id is required")
    try:
        from qikly import validate
        results = validate.check_all([task_id])
        errors, warnings = results.get(task_id, ([], []))
    except Exception as exc:                       # noqa: BLE001
        return _error("could not check that task: %s" % exc)

    # Counts, not text. A validation message can quote the criterion it is
    # complaining about, which is precisely what must not cross this boundary,
    # so the messages are counted and dropped rather than returned.
    return _redact({"ok": True, "task_id": task_id,
                    "valid": not errors,
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "note": "counts and a verdict only. Validation messages can "
                            "quote the criterion they are about, so they are not "
                            "returned to an MCP host. Run `qikly --validate` in a "
                            "terminal to read them."})


def qikly_scaffold(file_path):
    """
    Turn a Python file into a task skeleton.

    It writes `TODO` for requirements and acceptance criteria and will not fill
    them in, because criteria derived from an implementation can only describe
    what that implementation already does, which is the circularity this whole
    project exists to break. That refusal is the feature, not a gap.
    """
    if not file_path or not isinstance(file_path, str):
        return _error("file_path is required")
    if not os.path.isfile(file_path):
        return _error("no such file: %s" % file_path)
    try:
        from qikly import paths, scaffold
        yaml_text, problem = scaffold.build_task(file_path, paths.project_root())
    except Exception as exc:                       # noqa: BLE001
        return _error("could not scaffold that file: %s" % exc)
    if problem:
        return _error(problem)

    return _redact({"ok": True, "task_yaml": yaml_text,
                    "note": "requirements and acceptance_criteria are left as TODO "
                            "on purpose: criteria taken from code can only restate it"})


_FORBIDDEN_KEYS = ("acceptance_criteria", "criteria", "criterion")

# A criteria block inside a *string*, which is a place the key-based walk below
# cannot look. `qikly_scaffold` returns a whole task file as text, so the same
# criteria that are stripped as a dict key travel through untouched as YAML.
#
# Nothing leaks today: scaffold writes TODO placeholders and refuses to derive
# criteria from an implementation. The reason this exists anyway is that
# `--from-doc` now merges real criteria into exactly this YAML, so the two
# features are one plausible wiring change apart from a leak that the guard
# above would not see. A guard blind to the shape the code is moving toward is
# not much of a guard.
_CRITERIA_BLOCK_IN_TEXT = re.compile(
    r"^(?P<key>acceptance_criteria:[ \t]*\n)"
    r"(?P<items>(?:[ \t]+-[ \t]*.*\n?)+)",
    re.M)
_PLACEHOLDER = re.compile(r"""^[ \t]+-[ \t]*["']?TODO\b""", re.I)


def _scrub_text(text):
    """
    Blank out real criteria in a YAML blob, keeping TODO placeholders.

    The placeholders have to survive: a scaffold whose criteria section came
    back empty would be useless, and telling the user what to write is the
    whole point of that section. Anything that is not a placeholder is somebody
    real's answer key and does not cross this boundary.
    """
    def scrub(match):
        kept = []
        for line in match.group("items").splitlines(True):
            if line.strip() and not _PLACEHOLDER.match(line):
                indent = line[:len(line) - len(line.lstrip())]
                kept.append('%s- "[withheld: qikly does not return acceptance '
                            'criteria to an MCP host]"\n' % indent)
            else:
                kept.append(line)
        return match.group("key") + "".join(kept)

    return _CRITERIA_BLOCK_IN_TEXT.sub(scrub, text)


def _redact(payload):
    """
    Last line of defence.

    Every function above is written not to include criteria, and this removes
    them anyway if a future change to something upstream starts returning them.
    Belt and braces is right here: the cost of the belt is one dict walk, and
    the cost of being wrong is the product's central claim.
    """
    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()
                    if k.lower() not in _FORBIDDEN_KEYS}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return _scrub_text(value)
        return value

    return walk(payload)
