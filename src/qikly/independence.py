"""
Evidence, from version control, that the criteria were settled before the code.

Withholding is a property of a run qikly performed. When this tool writes the
implementation, the agent that wrote it provably never saw the acceptance
criteria, because one process controlled both sides and neither prompt carried
the other's half. A seeded run cannot say that. `seed.implementation`, which is
what `qikly --scaffold` writes for code you already have, supplies an
implementation from outside: the suite is still written from the criteria by an
agent that never reads that code, so a failure is still a real finding, but what
the author of the code saw is outside this tool's knowledge.

Outside its knowledge is not outside all knowledge. If the criteria were
committed before the implementation first appeared, they cannot have been
fitted to it, because there was nothing to fit them to. Version control already
knows the answer and nobody was asking it. This module asks, and answers in one
of four ways:

    criteria_first   the task file's last change predates the implementation's
                     first commit, so the bar was fixed before this code existed
    not_evidenced    it does not, so the criteria may have been written, or
                     revised, with the code in view
    no_history       git has nothing to say here: not a repository, or a file
                     it does not track
    unavailable      git could not be run at all

What this does not show, and must never be read as showing, is that the two
sides were written independently. Independence dies in two directions, and git
witnesses neither act. It witnesses only when each side was committed:

    the bar was fitted to the code    someone read the implementation, then
                                      wrote criteria it already passed.
                                      Narrowed by criteria_first, not ruled
                                      out: code can live for weeks in a
                                      working tree, a local branch or a
                                      prototype before its first commit, and
                                      whoever wrote the criteria may have been
                                      reading it the whole time.

    the code was written to the bar   the developer read the criteria, then
                                      implemented against them. Not addressed
                                      at all by criteria_first, which is in
                                      fact the order this one requires.

So the verdict is worth most when it comes out badly. `not_evidenced` says a
task file moved after the code was committed, which is a question somebody
should answer. `criteria_first` is corroboration and never proof, and every
sentence this module writes says so. That is the same asymmetry the tool has
everywhere else: a failing test is a finding, a passing one is weaker evidence.

What version control can add is who:
the two sides committed by different people is the separation of duties the
method asks for, and by the same person means the separation rests on process
rather than on anything recorded here. Access is not observable at all, since
people who work together can read each other's repositories, so this module
reports the order and the authors and stops.

Two further choices are deliberately the conservative ones, because a claim
about independence that overstates itself is worse than no claim.

The criteria side uses the *last* change to the whole task file, not the first,
and not just the `acceptance_criteria` block. A criteria edit made after the
code existed is precisely the case a reader should look at, and pinning the
block alone would mean parsing a file whose shape users are free to change.

The implementation side uses its *first* commit, since that is the moment the
code entered the world. Later commits say only that it kept being worked on.

Nothing here raises. A run that produced real output must not fail while
recording a note about itself, so every failure path returns a verdict that
says plainly that nothing was evidenced.
"""
import os
import subprocess

CRITERIA_FIRST = "criteria_first"
NOT_EVIDENCED = "not_evidenced"
NO_HISTORY = "no_history"
UNAVAILABLE = "unavailable"

VERDICTS = (CRITERIA_FIRST, NOT_EVIDENCED, NO_HISTORY, UNAVAILABLE)

# Short labels for a report badge. The sentence in "detail" carries the dates.
HEADLINES = {
    # "committed before", not "predate": the file dates are commit dates, and
    # the difference between the two is the whole caveat.
    CRITERIA_FIRST: "Criteria committed before this implementation",
    NOT_EVIDENCED: "Order not evidenced",
    NO_HISTORY: "No version history",
    UNAVAILABLE: "Version history unavailable",
}

# Longer than `git log` on any sane repository, short enough that a wedged git
# cannot hang a run which has already done its real work.
_TIMEOUT_SECONDS = 10


def _git(args, cwd):
    """One git command's stdout, stripped, or None. Never raises."""
    try:
        done = subprocess.run(
            ["git"] + args, cwd=cwd, timeout=_TIMEOUT_SECONDS,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace").strip()


def _dir_of(path):
    """The directory to run git in for this path, whether file or directory."""
    full = os.path.abspath(path)
    if os.path.isdir(full):
        return full
    parent = os.path.dirname(full)
    return parent if os.path.isdir(parent) else None


def _repo_root(path):
    """The git work tree containing path, or None."""
    where = _dir_of(path)
    if where is None:
        return None
    return _git(["rev-parse", "--show-toplevel"], where)


def _relative(path, root):
    """path as git wants to hear it: relative to root, forward slashes."""
    try:
        return os.path.relpath(os.path.abspath(path), root).replace("\\", "/")
    except ValueError:
        # A different drive on Windows, so it cannot be inside this repository.
        return None


def _stamp(line):
    """One `%ct|%cI|%h|%ae` line as a dict, or None if git said otherwise."""
    parts = line.split("|")
    if len(parts) != 4:
        return None
    try:
        return {"unix": int(parts[0]), "date": parts[1],
                "commit": parts[2], "author": parts[3]}
    except ValueError:
        return None


def _commit_times(path, root, oldest):
    """
    The oldest or newest commit touching path. Compared by committer seconds
    rather than by the ISO string, because two commits made in different time
    zones sort wrongly as text and the whole point here is the ordering.
    """
    rel = _relative(path, root)
    if rel is None:
        return None
    args = ["log", "--format=%ct|%cI|%h|%ae"]
    if oldest:
        # A renamed file looks younger than it is. `git log -- path` stops at
        # the rename, so a module moved into src/ long after it was written
        # reports the move as its first commit, and criteria written in between
        # then read as settled first: the reassuring verdict, taken from the
        # wrong history. --follow reads through the rename. Git defines it for
        # a single file only, so a directory seed goes without it.
        if os.path.isfile(os.path.abspath(path)):
            args.append("--follow")
    else:
        args.append("-1")
    out = _git(args + ["--", rel], root)
    if not out:
        return None
    lines = out.splitlines()
    # No --reverse, which would be the obvious way to ask for the oldest first.
    # Measured on git 2.51: --reverse and --follow together silently drop the
    # pre-rename history, in either flag order, which is the bug this code was
    # written to fix. git log lists newest first, so the oldest is the last
    # line, and that holds for a directory query too.
    return _stamp(lines[-1] if oldest else lines[0])


def console_lines(task_id, evidence):
    """
    What a seeded run prints as it opens.

    The limit gets a line of its own rather than living only in the HTML
    report. The console is where most people read a run, and a claim about
    independence that travels without its bounds is the exact failure this
    module exists to avoid, so the two must not be separable by looking in a
    cheaper place.
    """
    lines = ["[%s] %s: %s" % (task_id, evidence.get("headline") or "",
                              evidence.get("detail") or "")]
    if evidence.get("limit"):
        lines.append("[%s]   %s" % (task_id, evidence["limit"]))
    return lines


def _blank(criteria_file, implementation, verdict, detail, limit=""):
    return {
        "verdict": verdict,
        "headline": HEADLINES[verdict],
        "detail": detail,
        # What the finding above stops short of. Carried as its own field so a
        # report cannot show the claim while dropping its bounds.
        "limit": limit,
        "criteria_file": criteria_file,
        "implementation": implementation,
        "criteria_last_changed": None,
        "criteria_commit": None,
        "criteria_author": None,
        "implementation_first_committed": None,
        "implementation_commit": None,
        "implementation_author": None,
        "same_author": None,
    }


def check(criteria_file, implementation):
    """
    Ask git whether criteria_file was settled before implementation appeared.

    criteria_file is the task YAML holding the acceptance criteria, and
    implementation is the seeded file or directory. The two need not live in
    the same repository: a task kept beside the spec and code kept in the
    product repo still have comparable commit times.

    Returns a dict with a verdict, a headline, a sentence for a person, and the
    two commits it compared. Never raises.
    """
    if not criteria_file or not implementation:
        return _blank(criteria_file, implementation, NO_HISTORY,
                      "this run generated its own implementation, so there is no "
                      "supplied code whose order needs evidencing")

    if _git(["--version"], os.getcwd()) is None:
        return _blank(criteria_file, implementation, UNAVAILABLE,
                      "git could not be run, so the order of the two cannot be "
                      "evidenced either way")

    criteria_root = _repo_root(criteria_file)
    implementation_root = _repo_root(implementation)
    if criteria_root is None or implementation_root is None:
        missing = criteria_file if criteria_root is None else implementation
        return _blank(criteria_file, implementation, NO_HISTORY,
                      "%s is not inside a git repository, so the order of the two "
                      "cannot be evidenced either way" % missing)

    criteria = _commit_times(criteria_file, criteria_root, oldest=False)
    code = _commit_times(implementation, implementation_root, oldest=True)
    if criteria is None or code is None:
        missing = criteria_file if criteria is None else implementation
        return _blank(criteria_file, implementation, NO_HISTORY,
                      "git tracks no commit touching %s, so the order of the two "
                      "cannot be evidenced either way" % missing)

    first = criteria["unix"] < code["unix"]
    same_author = bool(criteria["author"]) and criteria["author"] == code["author"]

    if first:
        detail = (
            "the criteria were last changed on %s, before this implementation's "
            "first commit on %s, so they were not written against code that was "
            "already in the repository"
            % (criteria["date"][:10], code["date"][:10])
        )
    else:
        detail = (
            "the task file last changed on %s, which is not before this "
            "implementation's first commit on %s, so the criteria may have been "
            "written or revised with the code in view"
            % (criteria["date"][:10], code["date"][:10])
        )

    # Neither bound below is a disclaimer to be trimmed. A reader who takes
    # criteria_first as proof of independence has been misled by this tool.
    limit = ("it evidences the order of two commits, not of two acts: code can "
             "exist uncommitted long before its first commit, and criteria "
             "committed first do not show whether the code's author read them. ")
    if same_author:
        limit += ("Both sides were committed by %s, so that separation rests on "
                  "your process rather than on anything recorded here."
                  % criteria["author"])
    else:
        limit += ("The two sides were committed by different people (%s and %s), "
                  "which is the separation the method asks for."
                  % (criteria["author"], code["author"]))

    out = _blank(criteria_file, implementation,
                 CRITERIA_FIRST if first else NOT_EVIDENCED, detail, limit)
    out["criteria_last_changed"] = criteria["date"]
    out["criteria_commit"] = criteria["commit"]
    out["criteria_author"] = criteria["author"]
    out["implementation_first_committed"] = code["date"]
    out["implementation_commit"] = code["commit"]
    out["implementation_author"] = code["author"]
    out["same_author"] = same_author
    return out
