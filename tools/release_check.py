"""
Everything in RELEASE_CHECKLIST.md that a machine can check, checked.

The checklist exists because every bug found in this project was found by
someone looking. The trouble with looking is that it is exactly as reliable as
the person doing it on the day, and the checklist itself has been wrong: it
told you to push the tag to `origin` for several releases, which is the private
repository, where nothing releases.

So this file is the checklist's teeth. It does not replace the prose, which
carries the reasoning. It refuses to let a release proceed past a failure that
has actually happened before.

    python tools/release_check.py              # before tagging
    python tools/release_check.py --after      # after the workflow finishes

Every check names the release it is defending against, because a check whose
reason nobody remembers is a check somebody eventually deletes.

The demo is not automated here. It needs an API key and spends real money, and
a script that quietly spends money is worse than one that reminds you to.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_REMOTE_URL = "github.com/gal-a/qikly"
DEFAULT_BRANCH = "main"

# Task files the research harnesses write and delete. A wheel built mid-sweep
# ships them as though they were bundled tasks.
LEFTOVER = re.compile(r"_(EFI|EFR|CONV|ARM\d*|BASE)\.yaml$")

_results = []


def check(name, ok, detail="", why=""):
    _results.append((name, bool(ok), detail, why))
    print("  %s  %s" % ("PASS" if ok else "FAIL", name))
    if detail:
        print("        " + detail.replace("\n", "\n        "))
    if not ok and why:
        print("        why this is checked: " + why)
    return bool(ok)


def run(args, **kw):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kw)


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


# --------------------------------------------------------------- versions --

def declared_versions():
    """
    Every place the version is written, and what it says.

    Six places have to agree. `server.json` alone holds three of them, and the
    third is a pin inside an argument string, which is the one a person reading
    quickly skips.
    """
    found = {}
    m = re.search(r'^version = "([^"]+)"', read("pyproject.toml"), re.M)
    found["pyproject.toml"] = m.group(1) if m else None

    m = re.search(r'__version__ = "([^"]+)"', read("src/qikly/__init__.py"))
    found["src/qikly/__init__.py"] = m.group(1) if m else None

    server = json.loads(read("server.json"))
    found["server.json:server"] = server.get("version")
    for pkg in server.get("packages") or []:
        found["server.json:package"] = pkg.get("version")
        for arg in pkg.get("runtimeArguments") or pkg.get("packageArguments") or []:
            value = arg.get("value") or ""
            m = re.search(r"qikly\[mcp\]==([\d.]+)", value)
            if m:
                found["server.json:mcp-pin"] = m.group(1)
    return found


def check_versions_agree():
    found = declared_versions()
    missing = [k for k, v in found.items() if not v]
    if missing:
        return check("version is readable everywhere", False,
                     "could not read: " + ", ".join(missing))
    distinct = sorted(set(found.values()))
    ok = len(distinct) == 1
    check("the six declared versions agree", ok,
          "\n".join("%-26s %s" % (k, v) for k, v in sorted(found.items())),
          "server.json's mcp pin is a version inside an argument string, and a "
          "missed bump there advertises one version and installs another")
    return distinct[0] if ok else None


def check_prose_pins(version):
    """
    The Action pins written in prose are examples people copy, so a stale one
    hands out a tag predating the fix they came for. `@v0` is the moving alias
    and is meant to stay as it is.
    """
    stale = []
    for path in ("README.md", "docs/PROVIDER_KEY_SETUP.md"):
        for pin in re.findall(r"gal-a/qikly@v(\d+\.\d+\.\d+)", read(path)):
            if pin != version:
                stale.append("%s: @v%s" % (path, pin))
        for pin in re.findall(r"`@v(\d+\.\d+\.\d+)`", read(path)):
            if pin != version:
                stale.append("%s: `@v%s`" % (path, pin))
    check("prose Action pins match the version", not stale,
          "\n".join(sorted(set(stale))) or "all exact pins read v" + version)


def check_changelog(version):
    text = read("CHANGELOG.md")
    heading = "## %s" % version
    present = heading in text
    provisional = re.search(re.escape(heading) + r"\s*\(", text)
    check("CHANGELOG has a finished entry for this version", present and not provisional,
          "missing '%s'" % heading if not present else
          "entry is still marked provisional" if provisional else heading)


# ------------------------------------------------------------ the working --

def check_tree_clean():
    out = run(["git", "status", "--porcelain"]).stdout.strip()
    check("working tree is clean", not out, out[:400],
          "a wheel is built from the tree, so anything uncommitted ships or "
          "silently does not")


def check_no_experiment_leftovers():
    tasks = os.path.join(ROOT, "src", "qikly", "inputs_public", "config", "tasks")
    junk = [n for n in os.listdir(tasks) if LEFTOVER.search(n)]
    check("no experiment task files in the bundled set", not junk, ", ".join(junk),
          "the research scripts write throwaway tasks here and delete them, so "
          "a wheel built mid-sweep ships them as bundled tasks")


# The names cannot appear here as literals. CI greps the whole tree for them
# and does not exempt this file, so the one file whose job is to find the old
# name became the only thing either grep found, and the public workflow failed
# on its own checker. Assembled from halves instead, the way docs/index.html
# splits its own copy, so no exclusion is needed for this file and a real leak
# in it would still be caught.
OLD_NAMES = ("v_and" + "_v", "v-and" + "-v", "test_qik" + "ly", "test-qik" + "ly")


def check_stale_names():
    patterns = []
    for name in OLD_NAMES:
        patterns += ["-e", name]
    out = run(["git", "grep", "-In"] + patterns + [
        "--", ".", ":!CHANGELOG.md", ":!RELEASE_CHECKLIST.md",
        ":!.github/workflows/ci.yml"]).stdout.strip()
    check("no stale project names", not out, out[:400],
          "three files name the old project on purpose; everywhere else is a leak")


# ------------------------------------------------------------------ tests --

def check_suite():
    env = dict(os.environ)
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "LLM_PROVIDER", "LLM_MODEL", "QIKLY_PROJECT_ROOT"):
        env.pop(key, None)
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    done = run([sys.executable, "-m", "pytest", "tests/", "-q"], env=env)
    tail = (done.stdout or done.stderr).strip().splitlines()[-1:]
    check("suite passes with no API key set", done.returncode == 0,
          " ".join(tail),
          "a suite that needs credentials gets skipped in CI, and a skipped "
          "suite catches nothing")

    done = run([sys.executable, "-m", "pytest", "tests/test_withholding.py", "-q"], env=env)
    check("the central claim holds", done.returncode == 0,
          " ".join((done.stdout or "").strip().splitlines()[-1:]),
          "this is the one test whose failure invalidates the project rather "
          "than the build; never 'fix' it by changing the test")


# ------------------------------------------------------------- the wheel ---

def check_wheel(version):
    """
    Build, then install into a throwaway venv and look at what shipped.

    The source tree has every file whether or not the wheel carries it, so
    anything verified only in the working directory is not verified. An
    editable install imports the source tree and reports the release version
    while exercising nothing that ships, which nearly shipped a broken 0.4.3.
    """
    shutil.rmtree(os.path.join(ROOT, "dist"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
    done = run([sys.executable, "-m", "build"])
    if not check("wheel and sdist build", done.returncode == 0,
                 (done.stderr or "").strip()[-300:]):
        return

    wheels = [n for n in os.listdir(os.path.join(ROOT, "dist")) if n.endswith(".whl")]
    named = [w for w in wheels if version in w]
    if not check("the wheel carries this version", bool(named), ", ".join(wheels)):
        return

    venv = tempfile.mkdtemp(prefix="qikly-release-")
    try:
        subprocess.run([sys.executable, "-m", "venv", venv], check=True,
                       capture_output=True)
        binary = "Scripts" if os.name == "nt" else "bin"
        python = os.path.join(venv, binary, "python" + (".exe" if os.name == "nt" else ""))
        done = subprocess.run([python, "-m", "pip", "install", "-q",
                               os.path.join(ROOT, "dist", named[0])],
                              capture_output=True, text=True)
        if not check("the wheel installs into a clean venv", done.returncode == 0,
                     (done.stderr or "").strip()[-300:]):
            return

        probe = ("import qikly, os, sys;"
                 "p=os.path.dirname(qikly.__file__);"
                 "print(qikly.__version__);"
                 "print(os.path.exists(os.path.join(p,'inputs_public/config/settings.yaml')),"
                 "os.path.isdir(os.path.join(p,'inputs_public/agent_defs')),"
                 "os.path.isdir(os.path.join(p,'inputs_public/config/tasks')))")
        done = subprocess.run([python, "-c", probe], capture_output=True, text=True)
        lines = (done.stdout or "").strip().splitlines()
        installed = lines[0] if lines else "?"
        data = lines[1] if len(lines) > 1 else ""
        check("the installed wheel reports this version", installed == version,
              "wheel says %s, tree says %s" % (installed, version))
        check("packaged data shipped", data == "True True True", data,
              "a missing package-data entry is invisible from the source tree "
              "and fatal on a user's machine")

        site = os.path.join(venv, "Lib" if os.name == "nt" else "lib")
        editable = [r for base, _, files in os.walk(site) for r in files
                    if r.startswith("__editable__")]
        check("it is a real install, not editable", not editable, ", ".join(editable),
              "an editable venv imports the source tree and reports the release "
              "version while exercising nothing that ships")
    finally:
        shutil.rmtree(venv, ignore_errors=True)


# ------------------------------------------------------------- the remote --

def public_remote():
    """
    The remote that actually releases, found by URL rather than by name.

    Named remotes are the trap: `origin` here is the private repository, and
    the checklist told you to push tags there for several releases.
    """
    out = run(["git", "remote", "-v"]).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        # Exact repository path, not a substring. `gal-a/qikly` is a prefix of
        # `gal-a/qikly-initial`, which is the private one, so a substring test
        # picks the wrong remote and then reports confidently about it. This
        # function fell into that on its first run.
        url = parts[1].rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        if url.endswith("/" + PUBLIC_REMOTE_URL.split("/", 1)[1]) and                 PUBLIC_REMOTE_URL.split("/")[0] in url:
            return parts[0]
    return None


def check_remote_ready(version):
    remote = public_remote()
    if not check("the public remote is identifiable by URL", bool(remote),
                 "looking for %s; found: %s" % (PUBLIC_REMOTE_URL,
                                                run(["git", "remote"]).stdout.split() or "none"),
                 "pushing a tag to the private remote publishes nothing and "
                 "fails silently"):
        return
    print("        public remote is '%s'" % remote)

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    heads = run(["git", "ls-remote", "--heads", remote]).stdout
    remote_main = None
    for line in heads.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == "refs/heads/%s" % DEFAULT_BRANCH:
            remote_main = sha.strip()

    check("%s on the public remote is the commit being released" % DEFAULT_BRANCH,
          remote_main == head,
          "remote %s = %s\nlocal HEAD   = %s\n"
          "fix with: git push %s %s:%s"
          % (DEFAULT_BRANCH, (remote_main or "missing")[:12], head[:12],
             remote, head[:12], DEFAULT_BRANCH),
          "0.4.9 tagged and released while the default branch stayed four "
          "commits behind. The tag still published, so nothing looked wrong, "
          "but every visitor saw the old code, the README's images resolve "
          "against this branch, and the CI badge reads it")

    tag = "v%s" % version
    exists_locally = run(["git", "rev-parse", "-q", "--verify",
                          "refs/tags/%s" % tag]).returncode == 0
    if exists_locally:
        at = run(["git", "rev-parse", tag]).stdout.strip()
        check("the tag %s points at HEAD" % tag, at == head,
              "tag = %s, HEAD = %s" % (at[:12], head[:12]),
              "0.4.7 pushed a tag at a commit the remote did not have, so the "
              "workflow had no tree to build and the tag had to be recreated")
    else:
        print("  ----  tag %s does not exist yet (expected before release)" % tag)


# -------------------------------------------------------------- after it --

def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "qikly-release-check"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def check_published(version):
    """
    The three places a release lands, which can disagree silently.

    PyPI is guarded by the workflow. The registry is not guarded by anything,
    and a stale entry there installs the old software by pin rather than
    merely looking out of date.
    """
    try:
        data = fetch_json("https://pypi.org/pypi/qikly/json")
        live = data["info"]["version"]
        check("PyPI serves this version", live == version, "PyPI latest: " + live)
    except Exception as exc:                          # pragma: no cover
        check("PyPI serves this version", False, "could not reach PyPI: %s" % exc)

    try:
        data = fetch_json("https://registry.modelcontextprotocol.io/v0/servers?search=qikly")
        pins, versions = set(), set()
        for server in data.get("servers", data if isinstance(data, list) else []):
            body = json.dumps(server)
            versions.update(re.findall(r'"version":\s*"([\d.]+)"', body))
            pins.update(re.findall(r"qikly\[mcp\]==([\d.]+)", body))
        check("the MCP registry lists this version", version in versions,
              "versions listed: " + ", ".join(sorted(versions)),
              "nothing in CI republishes the registry; it needs a human login")
        check("the registry's install pin matches", version in pins,
              "pins listed: " + ", ".join(sorted(pins)),
              "the listing installs by pin, so a stale pin installs stale "
              "software rather than merely looking out of date")
    except Exception as exc:                          # pragma: no cover
        check("the MCP registry lists this version", False,
              "could not reach the registry: %s" % exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--after", action="store_true",
                        help="verify what actually got published, after the "
                             "release workflow has finished")
    parser.add_argument("--skip-wheel", action="store_true",
                        help="skip the build and clean-venv install, which is "
                             "the slow part")
    args = parser.parse_args()

    print("\nqikly release check, %s\n" % ("after release" if args.after else "before tagging"))
    version = check_versions_agree()
    if not version:
        print("\nStopping: the version is not consistent, so nothing below can mean anything.")
        return 1
    print("        version under test: %s\n" % version)

    if args.after:
        check_published(version)
        check_remote_ready(version)
    else:
        check_prose_pins(version)
        check_changelog(version)
        check_tree_clean()
        check_no_experiment_leftovers()
        check_stale_names()
        check_suite()
        if not args.skip_wheel:
            check_wheel(version)
        check_remote_ready(version)

    failed = [name for name, ok, _, _ in _results if not ok]
    print("\n%d checks, %d failed" % (len(_results), len(failed)))
    for name in failed:
        print("  FAILED: " + name)

    if not args.after and not failed:
        print("\nStill yours to do, because it spends money:")
        print("  the demo, from a directory that is NOT this repository,")
        print("  using the wheel rather than an editable install.")
        print("\nThen, in this order:")
        remote = public_remote() or "public"
        print("  git push %s HEAD:%s" % (remote, DEFAULT_BRANCH))
        print("  git tag v%s && git push %s v%s" % (version, remote, version))
        print("  mcp-publisher login github && mcp-publisher publish")
        print("  python tools/release_check.py --after")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
