# -*- coding: utf-8 -*-
"""
Planting several faults at once must give the score one at a time gives.

`--score` re-runs the suite once per planted fault, and on a four-minute
suite sixty faults took over four hours. Running several at once, each in its
own copy of the workspace, cuts that by the number of copies, and is only
worth having if nothing else changes: the same faults for a seed, the same
verdict for each, the same order in the report. These pin that on the
repository's own examples, pin that 1 still means one at a time, and pin the
fall back for a suite that cannot share the machine with itself.
"""
import os
import shutil

import pytest

from qikly import cli
from qikly import mutation_score as ms

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "docs", "examples")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _snapshot(result):
    """Everything about a score that must not depend on the worker count."""
    def rows(items):
        return [(i["file"], i["family"], i["change"]) for i in items]
    return (result["baseline"], rows(result["caught"]), rows(result["missed"]),
            result["unscorable"], result["total"], result["unreached"])


def _example(tmp_path, name):
    """A copy of one of the docs examples, so nothing in the repo is touched."""
    where = str(tmp_path / name)
    shutil.copytree(os.path.join(EXAMPLES, name), where,
                    ignore=shutil.ignore_patterns("__pycache__"))
    return where


@pytest.mark.parametrize("name,code", [("pricing", "pricing.py"),
                                       ("shop_folder", "shop")])
def test_parallel_scores_the_same_as_one_at_a_time(tmp_path, name, code,
                                                   monkeypatch, capsys):
    where = _example(tmp_path, name)
    target = ms.from_paths(os.path.join(where, code),
                           os.path.join(where, "tests"))
    one = ms.score(target, mutants=10, seed=3, workers=1)
    # A heartbeat on every pass, to show the progress line stays right with
    # faults finishing out of order.
    monkeypatch.setattr(ms, "HEARTBEAT_SECONDS", 0)
    capsys.readouterr()
    three = ms.score(target, mutants=10, seed=3, workers=3)
    beats = [line for line in capsys.readouterr().out.splitlines()
             if "still scoring" in line]

    assert one["workers"] == 1 and three["workers"] == 3
    assert not three["parallel_fallback"]
    assert one["total"] >= 5, one
    assert _snapshot(one) == _snapshot(three)
    counts = [int(line.split("still scoring: ")[1].split(" of ")[0])
              for line in beats]
    assert counts == sorted(counts)
    assert all(f"of {one['total'] + one['unscorable']} faults planted" in line
               for line in beats)
    assert all(0 < c < one["total"] + one["unscorable"] for c in counts)


def test_parallel_leaves_the_original_files_alone(tmp_path):
    where = _example(tmp_path, "pricing")
    before = open(os.path.join(where, "pricing.py"), "rb").read()
    ms.score(ms.from_paths(os.path.join(where, "pricing.py"),
                           os.path.join(where, "tests")),
             mutants=6, seed=1, workers=3)
    assert open(os.path.join(where, "pricing.py"), "rb").read() == before
    assert not list((tmp_path / "pricing").rglob("__pycache__"))


def _two_functions(root):
    """`f` is tested, `g` is not, and both have same-size mutants."""
    _write(os.path.join(root, "calc.py"),
           "def f(x):\n    if x == 3:\n        return 1\n    return 2\n\n\n"
           "def g(y):\n    if y == 5:\n        return 7\n    return 0\n")
    _write(os.path.join(root, "tests", "test_f.py"),
           "from calc import f\n\n\ndef test_f():\n"
           "    assert f(3) == 1\n    assert f(4) == 2\n")
    return ms.from_paths(os.path.join(root, "calc.py"),
                         os.path.join(root, "tests"))


def test_the_bytecode_rule_holds_in_every_copy(tmp_path):
    """
    The 0.5.9 fault: a same-size mutant within one second ran the previous
    mutant's cached bytecode. With several copies each copy plants faults in
    turn, so the rule has to hold per copy: only `g`, lines 7 to 10, is ever
    reported missed.
    """
    for seed in (0, 1):
        result = ms.score(_two_functions(str(tmp_path / str(seed))),
                          mutants=8, seed=seed, workers=3)
        assert result["workers"] == 3
        lines = [int(m["change"].rsplit("line ", 1)[1])
                 for m in result["missed"]]
        assert all(line >= 7 for line in lines), result["missed"]


def test_a_src_layout_imports_each_copy_s_own_code(tmp_path):
    """
    A src/ layout scores with the copy's src/ on PYTHONPATH. A second copy
    given the first one's path would run whatever fault the first held.
    """
    root = str(tmp_path)
    _write(os.path.join(root, "src", "rater", "__init__.py"),
           "from .calc import rate\n")
    _write(os.path.join(root, "src", "rater", "calc.py"),
           "def rate(x):\n    if x <= 100:\n        return x * 2\n    return 200\n")
    _write(os.path.join(root, "tests", "test_calc.py"),
           "from rater import rate\n\n\ndef test_caps():\n"
           "    assert rate(150) == 200\n    assert rate(10) == 20\n")
    target = ms.from_paths(os.path.join(root, "src", "rater"),
                           os.path.join(root, "tests"))
    one = ms.score(target, mutants=8, seed=0, workers=1)
    two = ms.score(target, mutants=8, seed=0, workers=2)
    assert one["caught"]
    assert _snapshot(one) == _snapshot(two)


def test_moved_env_points_each_copy_at_its_own_workspace():
    old = os.path.join("tmp", "ws")
    new = os.path.join("tmp", "ws2")
    elsewhere = os.path.join("tmp", "wsx")
    env = {"PYTHONPATH": os.pathsep.join(
        [os.path.join(old, "src"), elsewhere, old]), "KEEP": "1"}
    moved = ms._moved_env(env, old, new)
    assert moved["PYTHONPATH"].split(os.pathsep) == [
        os.path.join(new, "src"), elsewhere, new]
    assert moved["KEEP"] == "1"
    assert env["PYTHONPATH"].startswith(os.path.join(old, "src"))


def test_one_worker_never_takes_the_parallel_path(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("workers=1 went through the parallel path")
    monkeypatch.setattr(ms, "_plant_in_parallel", refuse)
    result = ms.score(_two_functions(str(tmp_path)), mutants=4, seed=0,
                      workers=1)
    assert result["workers"] == 1 and result["total"]
    # And the library default is one at a time: only the command line picks
    # a parallel default.
    result = ms.score(_two_functions(str(tmp_path / "again")), mutants=4,
                      seed=0)
    assert result["workers"] == 1


def test_a_suite_that_cannot_run_beside_itself_falls_back(tmp_path,
                                                          monkeypatch, capsys):
    """
    A suite that takes a fixed resource outside its folder, here a lock
    directory standing in for a port or a database, passes alone and fails
    with a second copy running. Its parallel verdicts would be copies
    tripping over each other, read as faults caught, so it is scored one
    fault at a time and the output says so.
    """
    lock = str(tmp_path / "shared.lock")
    monkeypatch.setenv("QIKLY_TEST_LOCK", lock)
    root = str(tmp_path / "proj")
    _write(os.path.join(root, "calc.py"),
           "def add(a, b):\n    return a + b\n\n\n"
           "def big(x):\n    return x > 10\n")
    _write(os.path.join(root, "tests", "test_calc.py"),
           "import os, time\nfrom calc import add, big\n\n\n"
           "def test_add():\n"
           "    os.mkdir(os.environ['QIKLY_TEST_LOCK'])\n"
           "    try:\n"
           "        time.sleep(2)\n"
           "        assert add(2, 3) == 5\n"
           "        assert big(11) and not big(10)\n"
           "    finally:\n"
           "        os.rmdir(os.environ['QIKLY_TEST_LOCK'])\n")
    target = ms.from_paths(os.path.join(root, "calc.py"),
                           os.path.join(root, "tests"))
    capsys.readouterr()
    result = ms.score(target, mutants=3, seed=0, workers=3)
    out = capsys.readouterr().out
    assert result["parallel_fallback"] is True
    assert result["workers"] == 1
    assert "one fault at a time" in out
    # The file holds two sites, so asking for three plants both.
    assert result["total"] + result["unscorable"] == 2
    assert result["total"] and len(result["caught"]) == result["total"]
    assert "planted one at a time" in ms.render(result, [])
    assert not os.path.exists(lock)


def _main(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["qikly"] + argv)
    return cli.main()


@pytest.mark.parametrize("value", ["0", "-2"])
def test_a_worker_count_below_one_is_refused(value, monkeypatch, capsys):
    code = _main(["--score", "pricing.py", "--score-tests", "tests",
                  "--score-workers", value], monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "--score-workers needs a whole number of 1 or more" in err


def test_a_worker_count_that_is_not_a_number_is_refused(monkeypatch):
    with pytest.raises(SystemExit) as stopped:
        _main(["--score", "pricing.py", "--score-tests", "tests",
               "--score-workers", "many"], monkeypatch)
    assert stopped.value.code == 2


def test_the_worker_flag_alone_explains_itself(monkeypatch, capsys):
    code = _main(["--score-workers", "2"], monkeypatch)
    err = capsys.readouterr().err
    assert code == 2
    assert "--score-workers goes with" in err and "--score" in err


@pytest.mark.parametrize("given,expected", [(None, "default"), (1, 1), (5, 5)])
def test_the_command_passes_the_worker_count_on(given, expected, tmp_path,
                                                monkeypatch):
    where = _example(tmp_path, "pricing")
    seen = {}

    def fake_run(target, **kwargs):
        seen.update(kwargs)
        return "report.md"
    monkeypatch.setattr(ms, "run", fake_run)
    code = cli._do_score_suite(None, 3, 0, code=os.path.join(where, "pricing.py"),
                               tests=os.path.join(where, "tests"),
                               workers=given)
    assert code == 0
    want = ms.default_workers() if expected == "default" else expected
    assert seen["workers"] == want


def test_the_default_worker_count_is_at_most_four(monkeypatch):
    monkeypatch.setattr(ms.os, "cpu_count", lambda: 64)
    assert ms.default_workers() == 4
    monkeypatch.setattr(ms.os, "cpu_count", lambda: 2)
    assert ms.default_workers() == 2
    monkeypatch.setattr(ms.os, "cpu_count", lambda: None)
    assert ms.default_workers() == 1


def test_a_failing_worker_is_reported_not_swallowed(tmp_path, monkeypatch):
    """
    A worker that raises must fail the score with its own error, and the
    faults not yet started must not run afterwards.
    """
    started = []
    real = ms._plant_one

    def flaky(workspace, target, env, candidate, fault_timeout):
        started.append(candidate[5])
        if len(started) == 2:
            raise RuntimeError("worker blew up")
        return real(workspace, target, env, candidate, fault_timeout)
    monkeypatch.setattr(ms, "_plant_one", flaky)
    target = _two_functions(str(tmp_path))
    with pytest.raises(RuntimeError, match="worker blew up"):
        ms.score(target, mutants=8, seed=0, workers=2)
    # Original source is restored whatever happened.
    assert "return 7" in open(os.path.join(str(tmp_path), "calc.py")).read()
