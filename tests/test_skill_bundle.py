"""
The Skill, and the one thing that will go wrong with it.

A Skill is a folder an agent reads: `SKILL.md` plus reference files beside it.
Bundling copies of `docs/TASK_FILE_REFERENCE.md` and `docs/TROUBLESHOOTING.md`
is what makes it work without a network, and it is also the obvious way to end
up with two versions of the same page saying different things. Nobody notices a
stale copy, because nobody reads the copy.

So the copies are asserted identical here. When this fails, the fix is to copy
the docs over again, not to edit the copy.
"""
import io
import os
import re
import shutil
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
SKILL_DIR = os.path.join(ROOT, "src", "qikly", "skills", "qikly")
BUNDLED = ("TASK_FILE_REFERENCE.md", "TROUBLESHOOTING.md")


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def test_the_skill_exists_where_an_agent_looks_for_it():
    assert os.path.isfile(os.path.join(SKILL_DIR, "SKILL.md"))


@pytest.mark.parametrize("name", BUNDLED)
def test_a_bundled_reference_matches_the_doc_it_came_from(name):
    """
    Byte for byte, ignoring line endings.

    A Skill that ships a six-month-old copy of the troubleshooting page is
    worse than one that ships none: the agent quotes it with confidence.
    """
    doc = _read(os.path.join(ROOT, "docs", name))
    bundled = _read(os.path.join(SKILL_DIR, "references", name))
    assert bundled == doc, (
        "the bundled reference %s has drifted from docs/%s. Copy the doc "
        "over the bundled reference; never edit the copy." % (name, name))


def test_the_frontmatter_has_a_name_and_a_description():
    """
    The description is the whole loading mechanism.

    An agent decides whether to read a Skill from its description alone, so one
    that only says what the tool is, without saying when to reach for it, is a
    Skill that never loads.
    """
    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    front = text.split("---", 2)[1]
    assert re.search(r"^name:\s*qikly\s*$", front, re.MULTILINE)
    described = re.search(r"^description:\s*(.+)$", front, re.MULTILINE)
    assert described, "no description, so nothing will ever load this skill"
    assert "Use when" in described.group(1), (
        "the description must say when to use it, not only what it is")


def test_the_description_fits_the_budget_a_host_gives_it():
    """
    The description is the only part of a Skill an agent reads before deciding,
    and a host does not show all of it.

    Claude Code builds its skill listing from a character budget: a fraction of
    the context window for the whole listing, and a per-skill cap of 1536
    characters. A description over that cap is truncated, and what is lost is
    the end of it, which is where the trigger phrases live: "Use when they ask
    whether a specification is testable", "whenever qikly or spec-driven
    testing is mentioned". Losing those loses the loading, silently, with the
    first half still reading perfectly.

    So this guards the cap with room to spare rather than at it. Every
    character here is also one fewer for somebody else's skills in the same
    listing, which is the reason to keep it short beyond the limit itself.
    """
    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    front = text.split("---", 2)[1]
    described = re.search(r"^description:\s*(.+)$", front, re.MULTILINE).group(1)

    assert len(described) <= 800, (
        "the description is %d characters. The per-skill cap is 1536 and the "
        "trigger phrases are at the end, so they are what a truncation takes. "
        "Cut it back under 800." % len(described))

    # And it has to still carry the phrases that do the loading.
    for phrase in ("Use when", "qikly"):
        assert phrase in described, (
            "%r left the description, which is where loading is decided"
            % phrase)


def test_the_skill_does_not_claim_to_enforce_the_withholding():
    """
    The claim that would be false, and is the easiest one to write.

    A Skill is instructions. It cannot keep the criteria from anything. The
    tool enforces that, in code, with a test that fails the build if a
    criterion ever leaks. Saying otherwise here would be the project's central
    claim, made in the one place it is not true.
    """
    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    assert "this skill cannot keep anything hidden" in text.lower()


def test_the_honest_limit_is_in_the_skill():
    """
    Every long-form document carries it; an agent's context is long form.

    And it has to be attached to the right claim. An earlier version said the
    six experiments had failed to show that withholding catches more defects.
    They were not about withholding: every one compared a refined bar against
    an unrefined one, both withheld, which is the question
    `docs/design_2_performance.md` calls open. Asserting only that the two
    phrases co-occur let that misattribution through, so this checks what they
    are attached to.
    """
    # Whitespace-normalised, because these documents are hard wrapped and a
    # phrase that straddles a line break is still the phrase.
    text = " ".join(_read(os.path.join(SKILL_DIR, "SKILL.md")).lower().split())
    assert "open" in text and "six experiments" in text
    assert "refining" in text, "the six experiments were about refinement"
    assert "has not been run, here or anywhere" in text, (
        "the withholding question is unmeasured, not disproved")
    assert "9.8 points" in text, (
        "the adjacent Google result belongs here: an agent that says nobody "
        "has measured anything in this area will be contradicted by a reader "
        "who has seen that paper")
    assert "six experiments have failed to show it" not in text, (
        "that wording attaches the refinement result to withholding")


def test_the_free_commands_named_are_really_free():
    """
    Really cross-checked against the CLI, not against a list in this file.

    An earlier version compared the Skill's prose with two hardcoded tuples and
    its docstring claimed the two could not drift. They could: a new paid flag
    would have to be remembered in both places. This reads the parser instead,
    so a flag whose own help says it costs a model call cannot be listed as
    free.

    It reads the command table rather than a sentence, because the sentence
    that used to list the free commands was a second copy of the table and was
    deleted for that reason.
    """
    import argparse

    from qikly import cli

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    rows = [line for line in text.splitlines()
            if line.startswith("| `qikly ") or line.startswith("| `--")]
    assert rows, "no command table in the skill"

    free = set()
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) >= 2 and cells[1].lower().startswith("free"):
            free |= set(re.findall(r"(--[a-z-]+)", cells[0]))
    assert free, "the command table marks nothing as free"

    captured = {}

    def grab(self, *a, **k):
        captured["parser"] = self
        raise SystemExit(0)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(argparse.ArgumentParser, "parse_args", grab)
        with pytest.raises(SystemExit):
            cli._parse_args()
    finally:
        monkey.undo()

    helps = {}
    for action in captured["parser"]._actions:
        for option in action.option_strings:
            helps[option] = (action.help or "").lower()

    for flag in sorted(free):
        assert flag in helps, "%s is listed as free but is not a qikly flag" % flag
        # A free flag's help often says "no model calls", so the phrase alone
        # proves nothing. Remove the denials first and see what is left.
        spends = helps[flag].replace("no model calls", "").replace("no model call", "")
        assert "model call" not in spends and "costs money" not in spends, (
            "%s is listed as free but its own help says it spends" % flag)


def test_the_frontmatter_carries_the_metadata_directories_sort_on():
    """
    Optional in the spec, expected by the places that list skills.

    A directory that cannot find an author lists the entry without one, and
    the version is how a listing knows whether what it holds is current. The
    version is the Skill's own, not qikly's: the Skill changes when its
    instructions change, not when the tool releases, and coupling them would
    add a sixth place to the release bump list for nothing.
    """
    import yaml

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    front = yaml.safe_load(text.split("---", 2)[1])
    assert front.get("license"), "no license, which several directories require"
    meta = front.get("metadata") or {}
    assert meta.get("author"), "no author in metadata"
    assert meta.get("version"), "no version in metadata"
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(meta["version"])), (
        "the skill version should be semantic, got %r" % meta["version"])
    # Pre-1.0 on purpose. 1.0.0 asserts a stable interface, and this has never
    # loaded in a live session with a real user; two test rounds found seven
    # defects in it. It also ships inside a tool that is itself pre-1.0, so a
    # 1.0.0 Skill would claim more maturity than the thing it documents. Raise
    # it when real use has not moved it for a while, and delete this check
    # then rather than editing around it.
    assert meta["version"].startswith("0."), (
        "the Skill reaches 1.0.0 when it has survived real use, not before")


# The body of each released Skill, by the version that shipped it. A version
# is only worth reading if it moves when the instructions move, and nothing
# else makes that true: the Skill is bumped by hand, in a file that is edited
# for reasons unrelated to releasing, by whoever happens to be editing it.
#
# Git would answer this more directly, and cannot: CI checks out at depth one
# with no tags, so a test that diffs against the last release passes locally
# and is vacuous on every runner. A hash is self-contained and says the same
# thing.
#
# 2026-09-29: 0.3.1 was edited twice in one session, and the bump to 0.3.2
# happened because somebody remembered. This exists so the next one does not
# depend on that.
SKILL_BODY_HASHES = {
    "0.3.2": "ff71bda1a1be618ed8050bb4a60ba1d28bba1eb13130c8e3b20580d41ad408cf",
    "0.3.3": "4598a415ca38cbe76fd8cd8520992ad757068ebc6339a83330b4076bb4e468ea",
}


def test_the_skill_version_moves_when_the_instructions_move():
    """
    A Skill version that has not changed while the text has is worse than no
    version at all: a directory that holds a cached copy has no way to know
    it is stale, and a user comparing two installs is told they match.
    """
    import hashlib
    import yaml

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    front = yaml.safe_load(text.split("---", 2)[1])
    version = str((front.get("metadata") or {}).get("version"))
    body = text.split("---", 2)[2]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    known = SKILL_BODY_HASHES.get(version)
    assert known is not None, (
        "SKILL.md declares version %s, which SKILL_BODY_HASHES does not know. "
        "If the instructions changed, that is the right thing to have done: "
        "add %r: %r to the table. If they did not, the version moved for no "
        "reason." % (version, version, digest))
    assert digest == known, (
        "SKILL.md's body changed while metadata.version stayed at %s. Bump "
        "metadata.version, then add an entry to SKILL_BODY_HASHES keyed on the "
        "NEW version with this digest: %s\n"
        "Do not key it on %s. Re-using the current version is what this test "
        "exists to catch, and an earlier wording of this message suggested "
        "exactly that."
        % (version, digest, version))


def test_every_frontmatter_key_is_one_the_spec_allows():
    """
    An unknown key fails the validators several directories run on submission.

    The published set is name, description, license, allowed-tools, metadata
    and compatibility. Anything else is a rejection, and a rejection arrives
    as a form that does not come back.
    """
    import yaml

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    front = yaml.safe_load(text.split("---", 2)[1])
    allowed = {"name", "description", "license", "allowed-tools", "metadata",
               "compatibility"}
    unknown = sorted(set(front) - allowed)
    assert not unknown, "frontmatter keys outside the spec: %s" % unknown


def test_the_references_say_when_to_open_them():
    """
    Progressive disclosure, which is the difference between a Skill that costs
    2,000 tokens and one that costs 10,000.

    An agent does not open a reference unless it is told to, and a list of
    what each file contains is not an instruction. Both bundled references are
    long enough that loading them by default would dominate the Skill.
    """
    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    assert re.search(r"Read `references/[^`]+`\*{0,2} when", text), (
        "no reference carries a 'read it when' instruction")
    assert "Do not read these by default" in text


def test_the_skill_names_a_minimum_qikly_version_it_can_be_true_of():
    """
    The Skill travels; the tool it documents does not travel with it.

    Installed with `--install-skill` the two are always in step, but a copy
    taken from a directory listing sits beside whatever the user already has.
    This page names `--score-suite` and the reachability warning, so against an
    older install it recommends a flag that does not exist. A version number
    matching qikly's would not have prevented that, only made it noticeable.

    The floor is asserted here rather than pinned to `qikly.__version__`: the
    Skill's requirement changes when it starts naming a newer feature, which
    is rarely, and coupling it to the release would add a sixth place to the
    version bump and claim a change on every release that made none.
    """
    import yaml

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    front = yaml.safe_load(text.split("---", 2)[1])
    requires = str((front.get("metadata") or {}).get("requires", ""))
    found = re.search(r"qikly\s*>=\s*(\d+\.\d+\.\d+)", requires)
    assert found, "metadata.requires should read like 'qikly >= 0.5.3'"
    assert found.group(1) in text, (
        "the body should state the same minimum version as the frontmatter, "
        "since the frontmatter is not what an agent reads out to a user")


def test_the_withholding_claim_is_scoped_to_a_run():
    """
    The sentence a user will stretch, and the limit that stops them.

    An adversarial round asked, in a user's voice, "the Skill enforces that you
    never see my acceptance criteria, so this conversation is safe, right?".
    It is not: the withholding is one thing, the coding agent's prompt inside a
    qikly run, and it says nothing about what somebody pastes into a chat. The
    Skill has to say that itself, because the agent quoting it will not think
    to add the caveat.
    """
    text = " ".join(_read(os.path.join(SKILL_DIR, "SKILL.md")).split())
    assert "It says nothing about this conversation." in text
    assert "no part of qikly prevented that" in text


def test_the_description_leads_with_what_makes_it_different():
    """
    What a router sees first, in a project where other skills compete.

    Tested against two plausible rivals, a pytest suite writer and a spec
    reviewer. It won every request that named trust, a specification, or a
    failing test, and it lost "write tests for src/pricing.py" because the
    description opened on the generic function, which the pytest skill claims
    just as well. The differentiator now comes first, before any reader
    reaches the qualifiers.
    """
    import yaml

    text = _read(os.path.join(SKILL_DIR, "SKILL.md"))
    desc = yaml.safe_load(text.split("---", 2)[1])["description"]
    opening = desc.split(".")[0].lower()
    assert "fail" in opening or "withhold" in opening, (
        "the first sentence should say what makes this different, not that it "
        "writes tests, which every testing skill says")


def test_the_skill_says_what_to_do_when_the_project_disagrees():
    """
    A house rule of "write code and tests together" defeats the mechanism.

    It is a reasonable rule on its own terms, which is what makes it dangerous:
    an agent will follow it without noticing that consistency by construction
    is exactly what stops a suite disagreeing. The Skill has to name the
    conflict, because resolving it silently is the one outcome that helps
    nobody.
    """
    text = " ".join(_read(os.path.join(SKILL_DIR, "SKILL.md")).split())
    assert "You cannot follow both." in text
    assert "let them decide which applies here" in text


def test_the_skill_asks_for_a_criterion_per_requirement():
    """
    The pairing, as a step rather than as one example.

    A session test filed six rules correctly and still under-produced
    criteria, because the Skill showed a paired requirement and criterion once
    and never generalised it. The reader wrote criteria for the boundaries
    that worried them and left the rest of the specification unchecked, which
    then made a stalled run harder to diagnose.
    """
    text = " ".join(_read(os.path.join(SKILL_DIR, "SKILL.md")).split())
    assert "go back through the requirements and pair them" in text.lower()
    assert "A requirement with no answer is a requirement nothing is testing." in text


def test_every_install_target_is_a_project_local_path():
    """
    Four agents, four conventions, and none of them may escape the project.

    A path with an absolute root or a `..` in it would write outside the
    directory the user is standing in, which is the one promise this command
    makes. The paths themselves come from each tool's documentation; only the
    claude one has been used in anger, and the CLI says so rather than
    implying a coverage nobody checked.
    """
    from qikly.skill_install import HOSTS, TARGETS

    assert set(TARGETS) == set(HOSTS)
    for host, target in TARGETS.items():
        assert not os.path.isabs(target), "%s target is absolute" % host
        assert ".." not in target.replace("\\", "/").split("/"), (
            "%s target climbs out of the project" % host)
        if host == "copilot":
            # Copilot reads no skills directory. Its target is the
            # instructions folder VS Code looks in, which is the whole reason
            # this host needed a shape of its own.
            assert target.replace("\\", "/") == ".github/instructions/qikly"
            continue
        assert target.replace("\\", "/").endswith("/skills/qikly"), (
            "%s target does not end in skills/qikly" % host)


def test_the_copilot_install_writes_the_file_copilot_actually_reads():
    """
    Copying the folder alone would put files on disk nothing ever opens.

    GitHub Copilot reads none of `.claude/`, `.agents/`, `.cursor/` or
    `.gemini/`. It reads `.github/instructions/*.instructions.md`, and a file
    one level further down is never looked at. So this host writes the Skill
    folder *and* the pointer beside it, and the pointer has to carry the
    frontmatter Copilot matches on.
    """
    from qikly.skill_install import POINTER, install

    root = tempfile.mkdtemp()
    try:
        destination, outcome, _ = install(root, host="copilot")
        assert outcome == "written"
        assert os.path.isfile(os.path.join(destination, "SKILL.md"))

        pointer = os.path.join(root, POINTER)
        assert os.path.isfile(pointer), (
            "no %s, so Copilot has nothing to open and the folder beside it "
            "is never read" % POINTER)
        text = _read(pointer)
        assert text.startswith("---\n"), "no frontmatter, so applyTo is unset"
        assert "applyTo:" in text
        # A workspace-relative path, not one relative to the pointer. An
        # agent resolving `qikly/SKILL.md` against the repository root looks
        # at the top level and finds nothing, and "beside this file" is a
        # sentence for a person rather than a path for a tool.
        assert ".github/instructions/qikly/SKILL.md" in text, (
            "the pointer does not name the file it exists to point at, by a "
            "path an agent can resolve")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_instruction_file_already_there_is_backed_up_not_destroyed(tmp_path):
    """
    `.github/instructions/` is a directory people write their own files into.

    The first version of the Copilot target wrote the pointer with a bare
    `open(path, "w")`: no `--force`, no backup, no message. A file somebody
    had written under that name was gone, which is the exact failure `_backup`
    was added to the folder path to prevent, repeated one file along.
    """
    from qikly.skill_install import POINTER, install

    pointer = tmp_path / POINTER
    pointer.parent.mkdir(parents=True)
    pointer.write_text("MY OWN NOTES\n", encoding="utf-8")

    _destination, outcome, backup = install(str(tmp_path), host="copilot")

    assert outcome == "written"
    assert backup, "nothing was moved aside, so the file was overwritten"
    assert "MY OWN NOTES" in _read(backup), "the backup is not what was there"
    assert "applyTo" in _read(str(pointer)), "the pointer was not written"


def test_rewriting_our_own_pointer_does_not_leave_a_backup(tmp_path):
    """
    A backup per install would litter the directory it is trying to respect.

    And "differs from the current text" is the wrong test for whether a file
    is ours: the pointer's wording changes between releases, so an upgrade
    backed up a file the user had never touched. What is kept is a file
    somebody else wrote, recognised by the opening qikly always generates.
    """
    from qikly.skill_install import POINTER, install

    install(str(tmp_path), host="copilot")

    # Identical: no backup.
    _destination, _outcome, backup = install(str(tmp_path), host="copilot",
                                             force=True)
    assert backup is None or "instructions" not in os.path.basename(backup), (
        "an identical pointer was backed up anyway")

    # An older release's pointer: ours, different body, still no backup.
    pointer = tmp_path / POINTER
    from qikly.skill_install import _POINTER_SIGNATURE

    pointer.write_text(_POINTER_SIGNATURE + "\nAn older release wrote this.\n",
                       encoding="utf-8")
    _destination, _outcome, backup = install(str(tmp_path), host="copilot",
                                             force=True)
    assert backup is None or "instructions" not in os.path.basename(backup), (
        "a pointer from an earlier release was backed up, which litters the "
        "directory on every upgrade")


def test_something_blocking_the_pointer_stops_before_anything_is_written(tmp_path):
    """
    A directory where the pointer goes cannot be written to.

    Discovering that after `copytree` left the Skill folder on disk while the
    command reported that nothing had been written: partial state, described
    as total failure, and a re-run then said "already exists" forever.
    """
    from qikly.skill_install import POINTER, TARGETS, install

    blocked = tmp_path / POINTER
    blocked.mkdir(parents=True)

    _destination, outcome, _backup = install(str(tmp_path), host="copilot")

    assert outcome == "blocked", outcome
    assert not (tmp_path / TARGETS["copilot"]).exists(), (
        "the Skill folder was written even though the install was reported "
        "as not written")


def test_a_folder_without_its_pointer_is_repaired_rather_than_called_fine(tmp_path):
    """
    Copilot reads the pointer. A folder with none beside it cannot load, and
    the install reported "already exists, so nothing was changed", which is
    true of the folder and false of the installation.
    """
    from qikly.skill_install import POINTER, install

    install(str(tmp_path), host="copilot")
    os.remove(str(tmp_path / POINTER))

    _destination, outcome, _backup = install(str(tmp_path), host="copilot")

    assert outcome == "pointer", outcome
    assert os.path.isfile(str(tmp_path / POINTER))


def test_copilot_is_not_detected_by_a_github_directory_alone():
    """
    Almost every repository has `.github/`, and finding one there proves
    nothing about whether anybody uses Copilot. The signal is somebody already
    writing Copilot instructions, which is a decision rather than a default,
    or `auto` would write this into every project on earth.
    """
    from qikly.skill_install import detect

    root = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(root, ".github", "workflows"))
        assert "copilot" not in detect(root)

        os.makedirs(os.path.join(root, ".github", "instructions"))
        assert "copilot" in detect(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_cli_offers_every_host_the_installer_knows():
    """
    The two lists have to agree, or a documented host is unreachable.

    `--install-skill cursor` failing with an argparse error, while
    `skill_install` happily supports cursor, is the shape of bug that only
    shows up in somebody else's terminal.
    """
    import argparse

    from qikly import cli
    from qikly.skill_install import HOSTS

    captured = {}

    def grab(self, *a, **k):
        captured["parser"] = self
        raise SystemExit(0)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(argparse.ArgumentParser, "parse_args", grab)
        with pytest.raises(SystemExit):
            cli._parse_args()
    finally:
        monkey.undo()

    action = next(a for a in captured["parser"]._actions
                  if "--install-skill" in a.option_strings)
    assert set(HOSTS) <= set(action.choices), (
        "the CLI cannot reach every host the installer supports")
    assert "all" in action.choices
    assert action.const == "auto", (
        "the bare flag should choose from what the project already uses. It "
        "meant claude, so somebody working in Cursor got a directory their "
        "editor does not read, with no error and no hint that three other "
        "conventions existed")


def test_one_host_failing_does_not_stop_the_others(tmp_path):
    """
    `--install-skill all` used to abandon the run mid-way.

    A plain file where a host's directory should be raises from makedirs, and
    that left the hosts before it written, the ones after it never attempted,
    and a raw traceback instead of a summary. Partial state with no report is
    the worst of both. The count comes from HOSTS so that adding one cannot
    quietly narrow what this checks.
    """
    from qikly.skill_install import install_all

    blocker = tmp_path / ".cursor"
    blocker.write_text("not a directory", encoding="utf-8")

    results = install_all(str(tmp_path), ["all"])
    by_host = {host: outcome for host, _dest, outcome, _backup in results}

    from qikly.skill_install import HOSTS

    assert len(results) == len(HOSTS), "not every host was attempted"
    assert by_host["cursor"].startswith("failed:")
    for host in ("claude", "agents", "gemini", "copilot"):
        assert by_host[host] == "written", "%s was skipped by another host's failure" % host


def test_two_backups_in_the_same_second_sit_side_by_side(tmp_path):
    """
    Seconds are not unique enough for a backup name.

    `shutil.move` onto an existing directory moves the source inside it, so a
    second --force install within one second nested its backup one level
    deeper while the printed path still pointed at the top. Nothing was lost
    and everything was misreported, which is worse than a clean failure.
    """
    from qikly.skill_install import TARGETS, install

    destination = tmp_path / TARGETS["claude"]

    install(str(tmp_path))
    (destination / "MINE.txt").write_text("first edit", encoding="utf-8")
    _dest, _outcome, first = install(str(tmp_path), force=True)

    (destination / "MINE.txt").write_text("second edit", encoding="utf-8")
    _dest, _outcome, second = install(str(tmp_path), force=True)

    assert first and second and first != second, "two backups shared a name"
    assert os.path.isfile(os.path.join(first, "MINE.txt")), (
        "the first backup's content is not where its path says")
    assert os.path.isfile(os.path.join(second, "MINE.txt")), (
        "the second backup's content is not where its path says")
    assert not os.path.isdir(os.path.join(first, "qikly")), (
        "the second backup was nested inside the first")

def test_an_older_installed_skill_is_reported_as_older(tmp_path):
    """
    The upgrade path nobody was told about.

    `pip install --upgrade qikly` replaces the package and cannot touch a Skill
    already copied into somebody's project. Everyone upgrading from the release
    before this one therefore keeps a Skill that names a different set of
    commands, and the installer said "already exists, nothing was changed"
    whether their copy was identical or three releases behind.
    """
    import shutil

    from qikly.skill_install import bundled_dir, is_stale

    destination = tmp_path / "qikly"
    shutil.copytree(bundled_dir(), str(destination))

    assert is_stale(str(destination)) is False, "a fresh copy read as stale"

    skill = destination / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "version: 0." in text
    # Derived, not hardcoded. These tests broke the first time the Skill's
    # version moved, which is a thing it is supposed to do whenever its
    # instructions change.
    current = re.search(r"^  version: (\S+)$", text, re.M).group(1)
    older = "0.0.1"
    assert older < current
    skill.write_text(text.replace("version: %s" % current, "version: %s" % older),
                     encoding="utf-8")
    assert is_stale(str(destination)) is True, "an older copy read as current"


def test_a_skill_whose_version_cannot_be_read_is_not_guessed_at(tmp_path):
    """
    None, not False. "I cannot tell" and "it is current" must not print the
    same thing, and this runs against a file the user may have edited.
    """
    from qikly.skill_install import is_stale

    destination = tmp_path / "qikly"
    destination.mkdir()
    (destination / "SKILL.md").write_text("no frontmatter here\n",
                                          encoding="utf-8")
    assert is_stale(str(destination)) is None

    (destination / "SKILL.md").write_text("version: not-a-number\n",
                                          encoding="utf-8")
    assert is_stale(str(destination)) is None

def test_a_bare_install_follows_the_agent_the_project_already_uses(tmp_path):
    """
    A bare `--install-skill` wrote `.claude/skills/` and nothing else, so
    somebody working in Cursor got a directory their editor does not read, no
    error, and no hint that three other conventions existed.

    The evidence is already on disk: a project with `.cursor/` in it belongs to
    somebody using Cursor.
    """
    from qikly.skill_install import FALLBACK, detect

    assert detect(str(tmp_path)) == [], "an empty project claims a convention"

    (tmp_path / ".cursor").mkdir()
    assert detect(str(tmp_path)) == ["cursor"]

    (tmp_path / ".claude").mkdir()
    assert detect(str(tmp_path)) == ["claude", "cursor"]

    assert FALLBACK == ("claude", "agents"), (
        "the fallback should cover Claude Code and the cross-agent path, "
        "which is three runtimes for two directories")


def test_it_never_installs_to_both_gemini_paths(tmp_path):
    """
    Gemini CLI reads its own directory and the cross-agent one, and finding
    the Skill in both makes it report every skill as overriding itself. That
    warning greeted a real test session.
    """
    from qikly.skill_install import detect

    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".agents").mkdir()
    found = detect(str(tmp_path))
    assert "agents" in found
    assert "gemini" not in found, "both Gemini paths at once makes it warn"


def test_the_closing_note_never_substitutes_a_target_for_an_agent(tmp_path):
    """
    `all` and `auto` are targets, not agents. Substituting one produced "the
    path all documents for skills", and then, in the very next release, "the
    path auto documents for skills". The same defect twice, so the message is
    now built from the hosts actually written.
    """
    import subprocess
    import sys

    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)

    for target in ([], ["all"], ["cursor"]):
        where = tmp_path / ("t_" + ("bare" if not target else target[0]))
        where.mkdir()
        done = subprocess.run(
            [sys.executable, "-m", "qikly", "--install-skill"] + target,
            cwd=str(where), env=environment, capture_output=True, text=True,
            timeout=300)
        for bad in ("path all documents", "path auto documents",
                    "in auto,", "in all,"):
            assert bad not in done.stdout, (
                "%s leaked a target name into the prose:\n%s"
                % (target or "bare", done.stdout))

def test_a_stale_installed_skill_is_mentioned_by_any_command(tmp_path):
    """
    pip cannot upgrade a Skill: it lives in the user's project, not in the
    package. So an upgrade leaves them following instructions that name a
    different set of commands, and the installer only says so if they happen
    to re-run it, which nobody does.

    Silent when the copy is current, because a notice on every command is a
    notice nobody reads.
    """
    import subprocess
    import sys

    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY"):
        environment.pop(name, None)

    def run():
        return subprocess.run([sys.executable, "-m", "qikly", "--validate"],
                              cwd=str(tmp_path), env=environment,
                              capture_output=True, text=True, timeout=300)

    subprocess.run([sys.executable, "-m", "qikly", "--install-skill"],
                   cwd=str(tmp_path), env=environment, capture_output=True,
                   text=True, timeout=300)

    fresh = run()
    assert "older than this qikly" not in (fresh.stdout + fresh.stderr), (
        "it nags about a copy that is current")

    skill = tmp_path / ".claude" / "skills" / "qikly" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    # Derived, not hardcoded. These tests broke the first time the Skill's
    # version moved, which is a thing it is supposed to do whenever its
    # instructions change.
    current = re.search(r"^  version: (\S+)$", text, re.M).group(1)
    older = "0.0.1"
    assert older < current
    skill.write_text(text.replace("version: %s" % current, "version: %s" % older),
                     encoding="utf-8")

    aged = run()
    assert "older than this qikly" in (aged.stdout + aged.stderr), (
        "an upgrade can leave a stale Skill in place and say nothing")
    assert "--install-skill --force" in (aged.stdout + aged.stderr), (
        "the notice must say what to do about it")
