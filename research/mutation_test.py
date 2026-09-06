"""
Mutation testing for the generated suites, with supplied labels instead of
inferred ones. No LLM calls, so this is free to run.

Why this exists
---------------
The cross-suite analysis in backanalysis.py has to guess whether an
implementation is correct, by asking whether most independently generated
suites accept it. That guess is contaminated: suites cover different subsets
of the criteria, so "most suites accept it" can just mean most of them never
tested the thing it gets wrong.

Mutation testing removes the guess for one half of the question. Take an
implementation a suite already accepts, break it deliberately in one known
place, and re-run that same suite:

    caught  the suite fails on the mutant     -> true positive, real detection
    missed  the suite still passes            -> false negative, a real gap

Each suite acts as its own control, so nothing depends on consensus, on which
run an implementation came from, or on any other suite's opinion. The fraction
caught is the mutation score, the standard measure of test-suite strength in
the testing literature since the late 1970s.

What it still does not measure: false positives. A suite rejecting genuinely
correct code needs a known-correct reference implementation to detect, and
that has to be written by hand. This covers detection only.

The honest caveat, which is inherent to the method rather than to this
implementation: some mutants are semantically equivalent to the original and
cannot be caught by any test. There is no general way to identify them, so a
share of every "missed" count is undetectable by construction, and the true
miss rate is lower than the measured one. Measured miss is an upper bound.

    python mutation_test.py --task CALC_TAX --since 20260814_194155
    python mutation_test.py --all --mutants 12 --suites 6 --since 20260814_194155
"""
import argparse
import ast
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

CODE_ROOT = "outputs/agent_src/code"
TEST_ROOT = "outputs/tests"
DATA_ROOT = "inputs_private/data"
REPORT_DIR = "outputs/reports/mutation"
STAGES = ("integration", "system")

# Swaps chosen to stay syntactically valid and to mirror the bug classes the
# findings taxonomy actually records: boundary conditions that are off by one
# inclusive/exclusive step (insufficient_strictness), inverted predicates, and
# constants that shift a threshold.
_CMP_SWAP = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
_BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


_NORMALISERS = {"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "title"}

# Two fault families, because they answer different questions.
#
# "arithmetic" perturbs existing computation: a comparison operator, a boolean
# connective, a constant. It is the classic mutation-testing set and it probes
# whether a suite pins down the logic it already covers.
#
# "validation" perturbs the code's strictness: it disables a guard, strips the
# anchors off a regex, drops a normalisation call, or swallows a raise. Those
# four map onto the finding categories the criteria-refinement loop actually
# produces (insufficient_strictness, parsing_looseness, domain_normalization,
# silent_failure), which the arithmetic family does not touch. Comparing
# refined criteria against arithmetic faults asks a question refinement was
# never about; this family is the one that matches the hypothesis.
FAMILIES = ("arithmetic", "validation")


def _is_guard(node):
    """An `if` that rejects, raises, skips or records a problem."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Raise, ast.Continue)):
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr == "append":
                return True
    return False


def _looks_like_regex(v):
    return isinstance(v, str) and ("^" in v or "$" in v) and any(
        t in v for t in ("\\d", "\\w", "\\s", "[", "+", "*", "(", "{"))


class _Mutator(ast.NodeTransformer):
    """Applies exactly the nth candidate mutation of one family, nothing else."""

    def __init__(self, target, family="arithmetic"):
        self.target = target
        self.family = family
        self.seen = -1
        self.applied = None

    def _hit(self, kind):
        self.seen += 1
        if self.seen == self.target:
            self.applied = kind
            return True
        return False

    # ------------------------------------------------------- arithmetic ----
    def visit_Compare(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_SWAP:
            old = type(node.ops[0])
            if self._hit(f"{old.__name__} -> {_CMP_SWAP[old].__name__}"):
                node.ops = [_CMP_SWAP[old]()]
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self.family != "arithmetic":
            return node
        if type(node.op) in _BOOL_SWAP:
            old = type(node.op)
            if self._hit(f"{old.__name__} -> {_BOOL_SWAP[old].__name__}"):
                node.op = _BOOL_SWAP[old]()
        return node

    # ------------------------------------------------------- both ----------
    def visit_Constant(self, node):
        if self.family == "arithmetic":
            if isinstance(node.value, bool):
                if self._hit(f"bool {node.value} -> {not node.value}"):
                    return ast.copy_location(ast.Constant(value=not node.value), node)
            elif isinstance(node.value, int):
                if self._hit(f"int {node.value} -> {node.value + 1}"):
                    return ast.copy_location(ast.Constant(value=node.value + 1), node)
            return node

        # validation: a regex that no longer anchors matches substrings, so a
        # malformed value with a valid fragment inside it starts passing.
        if _looks_like_regex(node.value):
            loosened = node.value.lstrip("^").rstrip("$")
            if loosened != node.value and self._hit("regex anchors stripped"):
                return ast.copy_location(ast.Constant(value=loosened), node)
        return node

    # ------------------------------------------------------- validation ----
    def visit_If(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        if _is_guard(node):
            if self._hit("guard disabled"):
                node.test = ast.copy_location(ast.Constant(value=False), node.test)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if self.family != "validation":
            return node
        # x.strip() -> x, so one code path stops normalising while others do.
        if (isinstance(node.func, ast.Attribute) and node.func.attr in _NORMALISERS
                and not node.args and not node.keywords):
            if self._hit(f".{node.func.attr}() dropped"):
                return node.func.value
        return node

    def visit_Raise(self, node):
        if self.family != "validation":
            return node
        if self._hit("raise swallowed"):
            return ast.copy_location(ast.Pass(), node)
        return node


def count_sites(source, family="arithmetic"):
    tree = ast.parse(source)
    m = _Mutator(-1, family)
    m.visit(tree)
    return m.seen + 1


def make_mutant(source, index, family="arithmetic"):
    """Returns (mutated_source, description) or (None, None) if index is out of range."""
    tree = ast.parse(source)
    m = _Mutator(index, family)
    tree = m.visit(tree)
    if m.applied is None:
        return None, None
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree), m.applied
    except Exception:
        return None, None


def versions(root, task, since=None):
    path = os.path.join(root, task, "old")
    if not os.path.isdir(path):
        return []
    out = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))
    return [d for d in out if not since or d >= since]


def build_workspace(task, tmp):
    ws = os.path.join(tmp, "ws")
    for sub in (os.path.join("outputs", "agent_src", "code", task),
                os.path.join("outputs", "data", task),
                os.path.join(DATA_ROOT, task)):
        os.makedirs(os.path.join(ws, sub), exist_ok=True)
    src = os.path.join(DATA_ROOT, task)
    if os.path.isdir(src):
        for name in os.listdir(src):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(ws, DATA_ROOT, task, name))
    return ws


def write_code(ws, task, filename, source):
    path = os.path.join(ws, "outputs", "agent_src", "code", task, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(source)


def suite_passes(ws, task, suite_ts):
    """True only if every integration and system test passes."""
    for stage in STAGES:
        sdir = os.path.abspath(os.path.join(TEST_ROOT, task, "old", suite_ts, stage))
        if not os.path.isdir(sdir):
            continue
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", sdir, "-q", "--tb=no",
             # Neutralise the project's own addopts. This repo sets
             # addopts = "-q", which combines with the -q above into -qq,
             # and -qq suppresses the final count line entirely. Every
             # parsed count then reads as zero, which looks exactly like a
             # suite that ran and passed.
             "-o", "addopts=", "-p", "no:cacheprovider"],
            cwd=ws, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False
    return True


def run_task(task, n_mutants, n_suites, since, rng):
    codes = versions(CODE_ROOT, task, since)
    suites = versions(TEST_ROOT, task, since)
    if not codes or not suites:
        return None

    # Search outwards from the middle for a base that actually parses. Runs
    # that exhausted their budget can leave syntactically broken code on disk
    # (a half-applied idea, an unfinished edit), and such a file has no
    # mutation sites and would fail every suite anyway, so it cannot serve as
    # a control.
    order = sorted(range(len(codes)), key=lambda i: abs(i - len(codes) // 2))
    base_ts = filename = base_source = None
    total_sites = 0
    for i in order:
        ts = codes[i]
        src_dir = os.path.join(CODE_ROOT, task, "old", ts)
        py = [f for f in os.listdir(src_dir)
              if f.endswith(".py") and not f.endswith(".orig.py")]
        if not py:
            continue
        # Archived code is not guaranteed to be readable: a stalled run can
        # leave a syntax error behind, and at least one file on disk is not
        # valid UTF-8. Neither could serve as a control, so skip and keep
        # looking rather than failing the task.
        try:
            source = open(os.path.join(src_dir, py[0]), encoding="utf-8").read()
            sites = count_sites(source)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        if sites:
            base_ts, filename, base_source, total_sites = ts, py[0], source, sites
            break
    if not base_source:
        return None
    chosen = sorted(rng.sample(range(total_sites), min(n_mutants, total_sites)))
    suite_sample = [suites[i] for i in
                    sorted(rng.sample(range(len(suites)), min(n_suites, len(suites))))]

    caught = missed = 0
    per_mutant = []
    with tempfile.TemporaryDirectory() as tmp:
        ws = build_workspace(task, tmp)

        # Only suites that accept the unmutated implementation can act as a
        # control: if a suite already fails the base, its verdict on a mutant
        # says nothing about detection.
        write_code(ws, task, filename, base_source)
        controls = [s for s in suite_sample if suite_passes(ws, task, s)]
        if not controls:
            return {"task": task, "base": base_ts, "controls": 0, "sites": total_sites,
                    "caught": 0, "missed": 0, "score": None, "mutants": []}

        for idx in chosen:
            mutant, desc = make_mutant(base_source, idx)
            if mutant is None or mutant == base_source:
                continue
            write_code(ws, task, filename, mutant)
            c = m = 0
            for s in controls:
                if suite_passes(ws, task, s):
                    m += 1
                else:
                    c += 1
            caught += c
            missed += m
            per_mutant.append({"mutation": desc, "caught_by": c, "missed_by": m})
            print(f"  [{task}] {desc:<28} caught by {c}/{len(controls)}", flush=True)

    total = caught + missed
    return {
        "task": task, "base": base_ts, "controls": len(controls), "sites": total_sites,
        "caught": caught, "missed": missed,
        "score": (caught / total) if total else None,
        "mutants": per_mutant,
    }


def main():
    ap = argparse.ArgumentParser(description="Mutation-test the generated suites.")
    ap.add_argument("--task", default=None, help="Comma-separated task_ids")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--mutants", type=int, default=12)
    ap.add_argument("--suites", type=int, default=6)
    ap.add_argument("--since", default=None, metavar="TS",
                    help="Only use suites from this run_timestamp onwards")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.all:
        tasks = sorted(d for d in os.listdir(CODE_ROOT)
                       if os.path.isdir(os.path.join(CODE_ROOT, d)) and not d.endswith("_DRAFT"))
    elif args.task:
        tasks = [t.strip() for t in args.task.split(",") if t.strip()]
    else:
        ap.error("give --task or --all")

    rng = random.Random(args.seed)
    results = []
    for t in tasks:
        print(f"\n=== {t} ===", flush=True)
        # One task failing must not lose the whole sweep: the same reasoning
        # run_all applies to its stages. Every task here is independent.
        try:
            r = run_task(t, args.mutants, args.suites, args.since, rng)
        except Exception as e:
            print(f"  skipped: {type(e).__name__}: {e}")
            continue
        if r:
            results.append(r)
        else:
            print(f"  skipped: no usable versions for {t}")

    if not results:
        return
    print()
    print("=" * 74)
    print("MUTATION SCORE: injected faults caught, per (mutant, suite) pair")
    print("=" * 74)
    print(f"{'TASK':<16}{'CONTROLS':<10}{'CAUGHT':<9}{'MISSED':<9}{'SCORE':<8}")
    tc = tm = 0
    for r in results:
        tc += r["caught"]
        tm += r["missed"]
        score = "n/a" if r["score"] is None else f"{100 * r['score']:.0f}%"
        print(f"{r['task']:<16}{r['controls']:<10}{r['caught']:<9}{r['missed']:<9}{score:<8}")
    if tc + tm:
        print(f"{'POOLED':<16}{'':<10}{tc:<9}{tm:<9}{100 * tc / (tc + tm):.0f}%")
    print("\nMissed is an upper bound: some mutants are semantically equivalent to")
    print("the original and cannot be caught by any test.")

    os.makedirs(REPORT_DIR, exist_ok=True)
    # Timestamped, because the unstamped name overwrote itself on every run and
    # took the evidence for a published claim with it. The article cited a
    # result from one of these reports; by the time anyone went to check it,
    # the run that produced it had been overwritten several times over.
    from datetime import datetime as _dt
    out = os.path.join(REPORT_DIR, f"mutation_{_dt.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
