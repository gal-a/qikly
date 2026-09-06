"""
Criterion coverage: of the acceptance criteria a run was given, how many did
the suite it generated actually enforce?

Why this is the measurement that was missing
--------------------------------------------
Every other analysis here has had to infer its ground truth. This one does
not. The criteria are written down in the task file, they are what test
generation was handed, and the generated tests are on disk. So the question
"did the suite test what it was told to test" is answerable directly, with no
consensus, no mutation, and no model calls.

It matters because a green run means something very different depending on the
answer. Converging against a suite that enforces 13 of 13 criteria is a strong
claim. Converging against one that enforces 6 of 13 is mostly a statement
about the 7 that were never checked. The project's own notes record this
failure mode: a correct, hand-written criterion can end up with no test
asserting it, and long criteria lists get sampled down to a handful of tests.

Method and its limit
--------------------
Each generated test function becomes a document (its name plus its source),
and each criterion is matched against those documents using the same
IDF-weighted containment already used to compare criteria lists, reused rather
than reinvented so both analyses agree on what "similar" means.

That scoring is a crude proxy for meaning, deliberately so, and the same
caveat applies here as there: it ORDERS criteria by how likely they are to be
unenforced, it does not prove that any particular one is. A low score is a
candidate for inspection. Averaging over many independently generated suites
is what makes the ordering stable, since one suite's word choices are noise
but a criterion that scores low against every suite is a real signal.

    python criterion_coverage.py --task CALC_TAX --since 20260814_194155
    python criterion_coverage.py --all --suites 10 --since 20260814_194155
"""
import argparse
import ast
import json
import os
import statistics
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from qikly.orchestrator.tuning.diff_acceptance_criteria import coverage

TEST_ROOT = "outputs/tests"
REPORT_DIR = "outputs/reports/criterion_coverage"
STAGES = ("integration", "system", "unit")
THRESHOLD = 0.45  # same default the criteria-diff tool flags at


def task_criteria(task):
    for base in ("inputs_private/config/tasks",
                 "src/qikly/inputs_public/config/tasks"):
        path = os.path.join(base, f"{task}.yaml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f).get("acceptance_criteria") or []
    return []


def suite_versions(task, since=None):
    path = os.path.join(TEST_ROOT, task, "old")
    if not os.path.isdir(path):
        return []
    out = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))
    return [d for d in out if not since or d >= since]


def test_documents(task, suite_ts):
    """
    One document per test function: its name with underscores split into words,
    plus its source. Names carry most of the intent in generated tests, and the
    body carries the values and comparisons, so both are needed.
    """
    docs = []
    for stage in STAGES:
        sdir = os.path.join(TEST_ROOT, task, "old", suite_ts, stage)
        if not os.path.isdir(sdir):
            continue
        for name in os.listdir(sdir):
            if not name.endswith(".py"):
                continue
            src = open(os.path.join(sdir, name), encoding="utf-8").read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    body = ast.get_source_segment(src, node) or ""
                    docs.append(node.name.replace("_", " ") + "\n" + body)
    return docs


def analyse_task(task, n_suites, since):
    criteria = task_criteria(task)
    if not criteria:
        return None
    versions = suite_versions(task, since)
    if not versions:
        return None
    if n_suites < len(versions):
        step = len(versions) / n_suites
        versions = [versions[int(i * step)] for i in range(n_suites)]

    # scores[i] collects one score per suite for criterion i
    scores = [[] for _ in criteria]
    used = 0
    for ts in versions:
        docs = test_documents(task, ts)
        if not docs:
            continue
        used += 1
        for row in coverage(criteria, docs):
            scores[criteria.index(row["real"])].append(row["score"])

    if not used:
        return None

    per_criterion = []
    for text, s in zip(criteria, scores):
        mean = statistics.mean(s) if s else 0.0
        per_criterion.append({
            "criterion": text,
            "mean_score": mean,
            "suites_enforcing": sum(1 for x in s if x >= THRESHOLD),
            "suites": len(s),
        })
    per_criterion.sort(key=lambda r: r["mean_score"])

    covered = sum(1 for r in per_criterion if r["mean_score"] >= THRESHOLD)
    return {
        "task": task,
        "criteria": len(criteria),
        "suites_examined": used,
        "covered": covered,
        "coverage": covered / len(criteria),
        "weakest": per_criterion[:3],
        "per_criterion": per_criterion,
    }


def main():
    ap = argparse.ArgumentParser(description="Measure how much of the stated bar the generated tests enforce.")
    ap.add_argument("--task", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--suites", type=int, default=10)
    ap.add_argument("--since", default=None, metavar="TS")
    args = ap.parse_args()

    if args.all:
        tasks = sorted(d for d in os.listdir(TEST_ROOT)
                       if os.path.isdir(os.path.join(TEST_ROOT, d)) and not d.endswith("_DRAFT"))
    elif args.task:
        tasks = [t.strip() for t in args.task.split(",") if t.strip()]
    else:
        ap.error("give --task or --all")

    results = [r for r in (analyse_task(t, args.suites, args.since) for t in tasks) if r]
    if not results:
        print("no tasks with both criteria and retained suites")
        return

    print()
    print("=" * 76)
    print("CRITERION COVERAGE: share of the stated bar the generated tests enforce")
    print("=" * 76)
    print(f"{'TASK':<16}{'CRITERIA':<10}{'ENFORCED':<10}{'COVERAGE':<10}{'SUITES':<8}")
    for r in sorted(results, key=lambda r: -r["coverage"]):
        print(f"{r['task']:<16}{r['criteria']:<10}{r['covered']:<10}"
              f"{100 * r['coverage']:.0f}%{'':<6}{r['suites_examined']:<8}")
    tot_c = sum(r["criteria"] for r in results)
    tot_v = sum(r["covered"] for r in results)
    print(f"{'POOLED':<16}{tot_c:<10}{tot_v:<10}{100 * tot_v / tot_c:.0f}%")

    print("\nLeast-enforced criteria (candidates for inspection, not verdicts):")
    for r in sorted(results, key=lambda r: r["coverage"])[:4]:
        print(f"\n  {r['task']}")
        for w in r["weakest"]:
            text = w["criterion"][:96] + ("..." if len(w["criterion"]) > 96 else "")
            print(f"    [{w['mean_score']:.2f}] enforced by {w['suites_enforcing']}/{w['suites']} suites")
            print(f"           {text}")

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, "criterion_coverage.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
