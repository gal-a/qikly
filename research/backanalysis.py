"""
Back-analysis: treat each generated test suite as a binary classifier of
implementations, and measure how good a classifier it is -- using only
artifacts already on disk. No LLM calls, so this is free to run.

The idea
--------
Every run leaves behind both an implementation (outputs/agent_src/code/<task>/
old/<ts>/) and the test suite that judged it (outputs/tests/<task>/old/<ts>/).
Across ~55 runs per task there are ~55 independently generated suites, all
written from the same acceptance_criteria. Cross-running them -- suite B
against implementation A -- costs nothing and reveals what a single run cannot:
whether the suites agree.

Ground truth for "is this implementation actually correct?" is not observable.
But with many independent suites, consensus is a defensible proxy: if 9 of 11
suites accept an implementation, the 2 that reject it are very likely wrong
about it. This is the same move as inter-rater agreement with no gold standard.

From that, the usual binary-classifier quantities follow, with the meanings:

    TP  suite rejects an implementation the consensus also rejects  (real bug caught)
    TN  suite accepts one the consensus accepts                     (correctly cleared)
    FP  suite REJECTS one the consensus accepts   -> a WRONG TEST. This is what
        produces the stuck loops: no implementation can satisfy an impossible
        assertion, so the FIX loop burns its budget. Documented cases exist
        (CALC_TAX's tax_rate test, MERGE_STOCK's adjust test, ETL_ADDRESS's
        title-case test).
    FN  suite ACCEPTS one the consensus rejects   -> a MISSED BUG. This is the
        dangerous one: the run converges, reports success, and ships wrong code.

Note the polarity: "positive" here means "flags a defect", so a false positive
is a false alarm (wrong test) and a false negative is a miss (silent bad pass).

Only integration and system tests are used. Unit tests are generated against a
specific implementation's function names, so they are not transplantable by
construction -- integration and system tests are black-box against the declared
interface, which is exactly what makes this comparison meaningful.

    python backanalysis.py --task CALC_TAX
    python backanalysis.py --task CALC_TAX,ETL_ADDRESS --code 10 --suites 10
    python backanalysis.py --all --code 8 --suites 8
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

CODE_ROOT = "outputs/agent_src/code"
TEST_ROOT = "outputs/tests"
DATA_ROOT = "inputs_private/data"
REPORT_DIR = "outputs/reports/backanalysis"
STAGES = ("integration", "system")

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors)")


def versions(root, task, sub="old", since=None):
    """
    Retained versions, optionally restricted to those created on or after
    `since` (a run_timestamp string).

    The window matters more than it looks. Sampling evenly across a task's
    whole history mixes suites generated under different acceptance criteria
    and different agent prompts, both of which changed over the days these
    artifacts accumulated. Suites either side of a criteria edit are not
    independent draws from one distribution, so disagreement between them
    measures the edit rather than the generator. Restricting to a window
    where nothing changed is what makes the comparison mean anything.
    """
    path = os.path.join(root, task, sub)
    if not os.path.isdir(path):
        return []
    out = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))
    if since:
        out = [d for d in out if d >= since]
    return out


def pick(items, k):
    """Evenly spaced sample, so we span the whole history rather than a burst."""
    if k >= len(items):
        return list(items)
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def run_suite(workspace, suite_dir):
    """
    Returns (passed, total). A collection/import error counts as total failure
    rather than being skipped: a suite that cannot even load against an
    implementation has rejected it, which is the outcome that matters here.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", suite_dir, "-q", "--tb=no",
         "-p", "no:cacheprovider"],
        cwd=workspace, capture_output=True, text=True,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    counts = defaultdict(int)
    for num, kind in _COUNT_RE.findall(tail):
        counts["failed" if kind.startswith("error") else kind] += int(num)
    passed, failed = counts["passed"], counts["failed"]
    total = passed + failed
    if total == 0:
        return 0, 0
    return passed, total


def build_workspace(task, code_ts, tmp):
    """A minimal project root: the implementation under test, plus its fixtures."""
    ws = os.path.join(tmp, "ws")
    for sub in (os.path.join("outputs", "agent_src", "code", task),
                os.path.join("outputs", "data", task),
                os.path.join(DATA_ROOT, task)):
        os.makedirs(os.path.join(ws, sub), exist_ok=True)

    src = os.path.join(CODE_ROOT, task, "old", code_ts)
    dst = os.path.join(ws, "outputs", "agent_src", "code", task)
    for name in os.listdir(src):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))

    data_src = os.path.join(DATA_ROOT, task)
    if os.path.isdir(data_src):
        for name in os.listdir(data_src):
            p = os.path.join(data_src, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(ws, DATA_ROOT, task, name))
    return ws


def matrix_for_task(task, n_code, n_suites, since=None):
    code_all = versions(CODE_ROOT, task, since=since)
    suite_all = versions(TEST_ROOT, task, since=since)
    codes, suites = pick(code_all, n_code), pick(suite_all, n_suites)
    if not codes or not suites:
        return None
    # An implementation is never scored by the suite from its own run: that is
    # a guaranteed pass and would inflate the accept cells. Only that one pair
    # is skipped, not the whole suite, which would throw away every other
    # verdict the suite can give.

    scores = {}  # (code_ts, suite_ts) -> pass fraction
    with tempfile.TemporaryDirectory() as tmp:
        for ci, code_ts in enumerate(codes, 1):
            ws = build_workspace(task, code_ts, tmp)
            for suite_ts in suites:
                if suite_ts == code_ts:
                    continue
                passed = total = 0
                for stage in STAGES:
                    sdir = os.path.join(TEST_ROOT, task, "old", suite_ts, stage)
                    if not os.path.isdir(sdir):
                        continue
                    p, t = run_suite(ws, os.path.abspath(sdir))
                    passed += p
                    total += t
                scores[(code_ts, suite_ts)] = (passed / total) if total else 0.0
            shutil.rmtree(ws, ignore_errors=True)
            print(f"  [{task}] implementation {ci}/{len(codes)} scored against "
                  f"{len(suites)} suites", flush=True)
    return {"task": task, "codes": codes, "suites": suites, "scores": scores}


def analyse(m, accept_threshold=1.0, consensus=0.5):
    """
    A suite ACCEPTS an implementation when every one of its tests passes --
    that is exactly the rule the orchestrator itself uses to call a stage
    converged, so the classifier being measured is the real one.

    Consensus truth: an implementation is "correct" when more than `consensus`
    of the suites accept it.
    """
    codes, suites, s = m["codes"], m["suites"], m["scores"]
    # Self-pairs are absent from `scores`, so every loop works off the pairs
    # that were actually run rather than the full cross product.
    accepted = {k: (v >= accept_threshold) for k, v in s.items()}
    truth = {}
    for c in codes:
        judges = [q for q in suites if (c, q) in accepted]
        if not judges:
            continue
        votes = sum(1 for q in judges if accepted[(c, q)])
        truth[c] = votes / len(judges) > consensus
    codes = [c for c in codes if c in truth]

    per_suite, tot = {}, defaultdict(int)
    for q in suites:
        tp = fp = tn = fn = 0
        for c in codes:
            if (c, q) not in accepted:
                continue
            good, acc = truth[c], accepted[(c, q)]
            if good and acc:
                tn += 1                      # correctly cleared
            elif good and not acc:
                fp += 1                      # WRONG TEST: rejected a good impl
            elif not good and not acc:
                tp += 1                      # real defect caught
            else:
                fn += 1                      # MISSED BUG: passed a bad impl
        per_suite[q] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
        for k, v in per_suite[q].items():
            tot[k] += v

    def safe(a, b):
        return (a / b) if b else None

    tp, fp, tn, fn = tot["tp"], tot["fp"], tot["tn"], tot["fn"]
    metrics = {
        "sensitivity_recall": safe(tp, tp + fn),        # defects caught
        "specificity": safe(tn, tn + fp),               # good impls left alone
        "precision": safe(tp, tp + fp),                 # rejections that were right
        "false_alarm_rate": safe(fp, fp + tn),          # wrong tests
        "miss_rate": safe(fn, fn + tp),                 # silent bad passes
        "accuracy": safe(tp + tn, tp + tn + fp + fn),
    }
    if metrics["precision"] and metrics["sensitivity_recall"]:
        p, r = metrics["precision"], metrics["sensitivity_recall"]
        metrics["f1"] = 2 * p * r / (p + r) if (p + r) else None

    # ROC over the continuous score (fraction of tests passed). Label is
    # "implementation is defective", score is 1 - pass_fraction, so a higher
    # score means a stronger defect signal.
    points = [(1 - s[(c, q)], not truth[c]) for c in codes for q in suites if (c, q) in s]
    auc = _auc(points)

    return {
        "task": m["task"], "n_code": len(codes), "n_suites": len(suites),
        "counts": dict(tot), "metrics": metrics, "auc": auc,
        "consensus_correct": sum(1 for c in codes if truth[c]),
        "per_suite": per_suite,
    }


def _auc(points):
    """Rank-based AUC (Mann-Whitney U); None when one class is absent."""
    pos = [s for s, lab in points if lab]
    neg = [s for s, lab in points if not lab]
    if not pos or not neg:
        return None
    ranked = sorted(points, key=lambda x: x[0])
    ranks, i = {}, 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum = sum(ranks[k] for k, (_, lab) in enumerate(ranked) if lab)
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def _fmt(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def report(results):
    print()
    print("=" * 78)
    print("TEST SUITE AS A CLASSIFIER OF IMPLEMENTATIONS")
    print("  positive = 'suite flags a defect'")
    print("  FP = wrong test (rejects a good implementation) -> stuck loops")
    print("  FN = missed bug (accepts a bad implementation)  -> silent bad pass")
    print("=" * 78)
    hdr = f"{'TASK':<16}{'GRID':<9}{'GOOD':<7}{'RECALL':<9}{'SPEC':<8}{'FALSE-AL':<10}{'MISS':<8}{'AUC':<6}"
    print(hdr)
    for r in results:
        m = r["metrics"]
        print(f"{r['task']:<16}{r['n_code']}x{r['n_suites']:<7}"
              f"{r['consensus_correct']}/{r['n_code']:<5}"
              f"{_fmt(m['sensitivity_recall']):<9}{_fmt(m['specificity']):<8}"
              f"{_fmt(m['false_alarm_rate']):<10}{_fmt(m['miss_rate']):<8}"
              f"{'n/a' if r['auc'] is None else format(r['auc'], '.2f'):<6}")
    print()
    for r in results:
        c = r["counts"]
        print(f"  {r['task']}: TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--task", default=None, help="Comma-separated task_ids")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--code", type=int, default=8, help="implementations sampled per task")
    ap.add_argument("--suites", type=int, default=8, help="test suites sampled per task")
    ap.add_argument("--since", default=None, metavar="TS",
                    help="Only use versions from this run_timestamp onwards, so every suite "
                         "was generated under the same criteria and prompts (e.g. 20260814_194155)")
    args = ap.parse_args()

    if args.all:
        tasks = sorted(d for d in os.listdir(CODE_ROOT)
                       if os.path.isdir(os.path.join(CODE_ROOT, d)) and not d.endswith("_DRAFT"))
    elif args.task:
        tasks = [t.strip() for t in args.task.split(",") if t.strip()]
    else:
        ap.error("give --task or --all")

    results = []
    for t in tasks:
        print(f"\n=== {t} ===", flush=True)
        m = matrix_for_task(t, args.code, args.suites, since=args.since)
        if not m:
            print(f"  no retained versions for {t}, skipped")
            continue
        results.append(analyse(m))

    if not results:
        return
    report(results)
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, "backanalysis.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
