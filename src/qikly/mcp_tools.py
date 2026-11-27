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
TOOLS = ("qikly_run", "qikly_status", "qikly_validate", "qikly_scaffold",
         "qikly_score", "qikly_score_result")


def _error(message, **extra):
    out = {"ok": False, "error": message}
    out.update(extra)
    return out


def where_we_looked(task_id):
    """
    Why this task could not be found, or None if it can.

    The failure this exists for is quiet and therefore expensive. An MCP host
    starts the server in *its* working directory, which is the folder the
    editor has open, and that is routinely the parent of the qikly project or
    an unrelated workspace. The task then looks absent, and "no such task" is
    true, useless, and reads as "qikly is broken" rather than "qikly is pointed
    at the wrong folder". Naming the directory we resolved is most of the fix.

    **Keyed on whether the task resolves, not on whether `inputs_private/`
    exists**, and that distinction is the whole reason this is written twice.
    Bundled tasks ship inside the package and work with no `inputs_private/`
    at all, so a precondition on that directory declares every fresh install
    broken. That is the same false alarm `validate._input_exists` was written
    to undo, and it is worth not reintroducing through a different door.
    """
    # The shape check comes first and its refusal is returned unchanged. A
    # traversing id like "../../evil" is a security answer, not a lookup
    # answer, and a friendly "we could not find that, check your project root"
    # would both bury it and invite the caller to go looking for the path.
    try:
        runs.check_task_id(task_id)
    except Exception as exc:                         # noqa: BLE001
        return str(exc)
    try:
        from qikly.agent_api.agent_interface import task_config_path
        # It returns where the file *would* be and does not check, so the
        # existence test has to happen here or every id looks findable.
        if os.path.isfile(task_config_path(task_id)):
            return None
    except Exception:                                # noqa: BLE001
        pass
    try:
        from qikly import paths
        root = paths.project_root()
    except Exception:                                # noqa: BLE001
        root = "(could not be resolved)"
    return ("no task %r under %s. An MCP host starts the server in the folder "
            "your editor has open, which is often not the qikly project: if "
            "that is the wrong directory, set QIKLY_PROJECT_ROOT in the "
            "server's env to the one holding your tasks." % (task_id, root))


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
    # Before spending anything. A run started against the wrong root fails
    # minutes later with a message about a missing task, which is true and
    # useless.
    problem = where_we_looked(task_id)
    if problem:
        return _error(problem)
    # The schema's enum is advice to the host, not a check: a run started
    # with provider "evil", 5 or a list, and failed inside the run instead
    # of here. An agent fills these in with no person reading them, and an
    # empty string is how many hosts say "not given".
    from qikly.agent_api.providers.router import _PROVIDERS
    if provider in (None, ""):
        provider = None
    elif not isinstance(provider, str) or provider.strip().lower() not in _PROVIDERS:
        return _error("provider must be one of %s, or left out for the project's "
                      "setting, not %r" % (", ".join(_PROVIDERS), provider))
    else:
        provider = provider.strip().lower()
    if model in (None, ""):
        model = None
    elif not isinstance(model, str) or not model.strip() or re.search(r"\s", model.strip()):
        return _error("model must be one model name with no spaces, such as "
                      "gemini-2.5-pro, or left out for the provider's default, "
                      "not %r" % (model,))
    else:
        model = model.strip()

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


def qikly_validate(task_id):
    """
    Whether a task's criteria are usable, without quoting them.

    The tool is *about* the criteria, which makes it the easiest place in the
    whole surface to justify returning their text. A verdict is not the text,
    and only the verdict crosses this boundary.
    """
    if not task_id or not isinstance(task_id, str):
        return _error("task_id is required")
    problem = where_we_looked(task_id)
    if problem:
        # Not an _error: the verdict is still "this bar is unusable", which is
        # what the caller asked. The detail says why without quoting anything.
        return _redact({"ok": True, "task_id": task_id, "valid": False,
                        "error_count": 1, "warning_count": 0,
                        "detail": problem})
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
                    # The first sentence travels with the data because a host
                    # summarises the reply, not the tool description it read at
                    # startup: Copilot relayed these counts as "no contradictions".
                    "note": "This is the free offline check of the task file: "
                            "structure, fixture paths, placeholders and vague "
                            "criteria. It does not look for contradictions; "
                            "`qikly --check-criteria` does. Counts and a verdict "
                            "only. Validation messages can "
                            "quote the criterion they are about, so they are not "
                            "returned to an MCP host. Run `qikly --validate` in a "
                            "terminal to read them."})


def qikly_scaffold(file_path):
    """
    Turn a Python file into a task that tests that code, returned as text.

    It writes `TODO` for the acceptance criteria and will not fill them in,
    because criteria derived from an implementation can only describe what
    that implementation already does, which is the circularity this whole
    project exists to break. That refusal is the feature, not a gap.
    `requirements` starts as the module's docstring, or a line to keep what
    the code does, marked `TODO: MODIFY THIS:` for the person to replace in
    their own words.
    """
    if not file_path or not isinstance(file_path, str):
        return _error("file_path is required")
    try:
        from qikly import paths, scaffold
        root = paths.project_root()
    except Exception as exc:                         # noqa: BLE001
        return _error("could not resolve a project root: %s" % exc)

    # A relative path used to be resolved against the process's own working
    # directory, which under an MCP host is the folder the *editor* has open,
    # not the project. So a caller who correctly set QIKLY_PROJECT_ROOT and
    # then passed a project-relative path got "no such file" and no hint that
    # two different directories were in play. Resolve against the project
    # first, since that is the one the caller named, and fall back to the
    # working directory so an absolute or genuinely cwd-relative path still
    # works.
    candidates = [file_path] if os.path.isabs(file_path) else [
        os.path.join(root, file_path), os.path.abspath(file_path)]
    found = next((c for c in candidates if os.path.isfile(c)), None)
    folder = next((c for c in candidates if os.path.isdir(c)), None)
    if found is None and folder is not None:
        return _error("%s is a folder. Pass one Python file in it, such as "
                      "%s" % (file_path, os.path.join(file_path, "module.py")))
    if found is not None and not found.lower().endswith(".py"):
        return _error("%s is not a Python file. qikly_scaffold reads a .py "
                      "module and returns a task that tests it" % file_path)
    if found is None:
        return _error(
            "no such file: %s. Looked under the project root %s and under the "
            "server's working directory %s, which an MCP host sets to the "
            "folder your editor has open. Pass an absolute path, or set "
            "QIKLY_PROJECT_ROOT to the project this file belongs to."
            % (file_path, root, os.getcwd()))
    file_path = found
    try:
        from qikly import scaffold
        # The same task `qikly --scaffold` writes by default: one that tests the
        # code in the file, which is why someone points a tool at a file.
        yaml_text, problem = scaffold.build_task(file_path, root, seed="existing")
        if not problem:
            # As `qikly --scaffold` does: a module that imports its siblings
            # is seeded as its whole package, or qikly's copy cannot import.
            from qikly import start
            yaml_text = start.package_seed(yaml_text, file_path, root)
    except Exception as exc:                       # noqa: BLE001
        return _error("could not scaffold that file: %s" % exc)
    if problem:
        return _error(problem)

    import re

    named = re.search(r'task_id:\s*"([^"]+)"', yaml_text)
    task_id = named.group(1) if named else "<task_id>"
    return _redact({"ok": True, "task_yaml": yaml_text,
                    "note": "This task tests the code in that file. Save it as "
                            "inputs_private/config/tasks/%s.yaml. acceptance_criteria "
                            "is left as TODO on purpose, since criteria taken from code "
                            "can only restate it, and requirements is a starting line "
                            "for the person to replace in their own words" % task_id})


def _existing_path(path, root):
    """The one place `path` exists: under the project root, else as given."""
    candidates = [path] if os.path.isabs(path) else [
        os.path.join(root, path), os.path.abspath(path)]
    return next((c for c in candidates if os.path.exists(c)), None)


_WALK_LIMIT = 200000


def _plain(path):
    """`path` without a Windows long-path prefix, which realpath keeps."""
    bs = chr(92)
    unc = bs * 2 + "?" + bs + "UNC" + bs
    if path.startswith(unc):
        return bs * 2 + path[len(unc):]
    for prefix in (bs * 2 + "?" + bs, bs * 2 + "." + bs):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _identity(path):
    """(device, file id) of what `path` is, whatever it is spelled as."""
    st = os.stat(path)
    if st.st_ino:
        return (st.st_dev, st.st_ino)
    return ("path", os.path.normcase(os.path.realpath(path)))


def _identities_under(top):
    """
    The identity of every folder and file in `top`, through links, plus `top`.
    Raises OverflowError past the limit, so a huge tree is refused, not skipped.
    """
    found, seen, count = {_identity(top)}, set(), 0
    for here, dirs, files in os.walk(top, followlinks=True):
        try:
            mark = _identity(here)
        except OSError:
            continue
        if mark in seen:
            dirs[:] = []                              # a loop through a link
            continue
        seen.add(mark)
        found.add(mark)
        for name in dirs + files:
            count += 1
            if count > _WALK_LIMIT:
                raise OverflowError
            try:
                found.add(_identity(os.path.join(here, name)))
            except OSError:
                continue
    return found


def _touches_outputs(path, root):
    """
    Whether `path` is inside qikly's `outputs/` folder, holds it, or holds a
    link or hard link to anything in it.

    The generated tests under `outputs/tests/` are written from the acceptance
    criteria. Scoring them would put their failure text (a failing assertion
    quotes the rule it broke) and their constants (a missed fault names a
    number from a test) into the response. `docs/mcp.md` tells the user to
    keep the agent from reading that folder, and the server process is not
    bound by that rule, so the tool has to enforce it itself.

    Compared by file identity, not by spelling: long-path and UNC forms, 8.3
    names, junctions, symlinks and hard links all name the same file. A path
    that cannot be examined is refused rather than allowed.
    """
    try:
        homes = {os.path.join(root, "outputs"), os.path.join(os.getcwd(), "outputs")}
        marks = set()
        for home in homes:
            if os.path.exists(home):
                marks |= _identities_under(home)
        if not marks:
            return False
        path = _plain(os.path.realpath(path))
        # Inside it, or at it: a folder on the way up is one of its folders.
        here = path
        while True:
            if _identity(here) in marks:
                return True
            above = os.path.dirname(here)
            if above == here:
                break
            here = above
        # Holding it, or a link into it: a file or folder below is one of its own.
        if os.path.isdir(path):
            return bool(_identities_under(path) & marks)
        return False
    except (OSError, ValueError, OverflowError):
        return True


def qikly_score(code_path, tests_path=None, mutants=None):
    """
    Start scoring an existing test suite and return an id at once.

    Plants small faults in a copy of the code and reports which ones the tests
    miss: free, no model call, nothing of the caller's modified. It does not
    wait, for the reason `qikly_run` does not: scoring takes seconds to over an
    hour and no host holds a call that long. `qikly_score_result` is how the
    caller finds out what happened.

    This tool never reads a task, and it refuses any path inside or holding
    `outputs/` (see `_touches_outputs`), so there are no acceptance criteria
    for it to return. It is the one tool here a caller can point at code they did not
    write through qikly, which is why it exists: "how good are my tests?" is
    the first question most people arrive with.
    """
    if not code_path or not isinstance(code_path, str):
        return _error("code_path is required")
    try:
        from qikly import paths
        root = paths.project_root()
    except Exception as exc:                         # noqa: BLE001
        return _error("could not resolve a project root: %s" % exc)

    code = _existing_path(code_path, root)
    if code is None:
        return _error(
            "no such path: %s. Looked under the project root %s and under the "
            "server's working directory %s. Pass an absolute path, or set "
            "QIKLY_PROJECT_ROOT to the project this code belongs to."
            % (code_path, root, os.getcwd()))
    if os.path.isfile(code) and not code.lower().endswith(".py"):
        return _error("%s is not a Python file. qikly_score plants faults in a "
                      ".py module or a folder of them" % code_path)

    tests = None
    if tests_path not in (None, ""):
        if not isinstance(tests_path, str):
            return _error("tests_path must be a path, or left out so qikly "
                          "finds the test files that import the code")
        tests = _existing_path(tests_path, root)
        if tests is None:
            return _error("no such tests path: %s. Name a test file or a "
                          "folder of them, or leave it out so qikly finds the "
                          "tests that import the code" % tests_path)

    if tests is None:
        # Left out, the command looks for the test files that import the code,
        # following links. What it would pick is checked here, before it runs.
        try:
            from qikly.start import auto_tests
            picked = auto_tests(os.path.abspath(code), root)
        except Exception as exc:                     # noqa: BLE001
            return _error("could not look for the tests: %s" % exc)
        if picked and _touches_outputs(picked, root):
            return _error(
                "the tests found for that code lead into qikly's outputs/ "
                "folder, which holds the generated tests. Name your own tests "
                "with tests_path.")

    for given, found in ((code_path, code), (tests_path, tests)):
        if found and _touches_outputs(found, root):
            return _error(
                "%s is inside, or contains, qikly's outputs/ folder. That "
                "folder holds the generated tests, which are written from the "
                "acceptance criteria and are kept from the agent, so "
                "qikly_score does not read it. Score your own module and your "
                "own tests." % given)

    if mutants in (None, ""):
        mutants = None
    elif isinstance(mutants, bool) or not isinstance(mutants, int) or not 1 <= mutants <= 1000:
        return _error("mutants must be a whole number from 1 to 1000, or left "
                      "out so qikly plants every fault it can up to its cap, "
                      "not %r" % (mutants,))

    try:
        score_id = runs.start_score(os.path.abspath(code),
                                    os.path.abspath(tests) if tests else None,
                                    mutants=mutants)
    except Exception as exc:                         # noqa: BLE001 - reported, not raised
        return _error("could not start the score: %s" % exc)
    return _redact({"ok": True, "score_id": score_id, "state": "running",
                    "next": "call qikly_score_result with this score_id"})


def qikly_score_result(score_id):
    """
    What happened to one `qikly_score`: still running, scored, or why not.

    Derived from what the score wrote to its own log, so it stays correct if
    the process died. A suite that fails on the untouched code is `not_scored`
    with the reason, not a score of zero: every fault would fail for the
    original's reason, and the number would mean nothing.
    """
    if not score_id or not isinstance(score_id, str):
        return _error("score_id is required")
    try:
        info = dict(runs.score_result(score_id))
    except Exception as exc:                         # noqa: BLE001
        return _error("could not read that score: %s" % exc)
    info["ok"] = info.get("state") not in ("unknown",)
    return _redact(info)


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
