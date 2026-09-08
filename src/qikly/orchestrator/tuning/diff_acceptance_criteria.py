import sys
"""
Turns the side-by-side output of gen_and_eval_acceptance_criteria.py into a
triage list: which real, hand-tuned criteria have no close counterpart in the
auto-generated set, ordered worst-covered first.

This does not judge anything. It orders. Deciding whether a real criterion is
genuinely missing from the generated set (a candidate worth investigating) or just
worded differently is still a human read -- the same standard every existing
confirmed gap was held to. What this removes is the part that makes that
read expensive: comparing every real criterion against every generated one by
eye, which is O(n*m) lines of dense domain text per task.

Deliberately makes no LLM calls and adds no dependencies. It re-reads
gen_and_eval reports already written to outputs/reports/acceptance_criteria/,
so running it costs nothing and is fully deterministic -- the same report in
always gives the same triage out, which matters when the output feeds a corpus
whose whole value is that entries were verified rather than generated.

Scoring is asymmetric IDF-weighted containment: what fraction of a real
criterion's distinctive vocabulary appears in its best-matching generated one.
IDF is computed over the two lists being compared, so vocabulary both sides
share heavily ("value", "rejected", and the task's own field names) is
discounted automatically, leaving the distinctive wording of the actual rule
to drive the score. That is a crude proxy for meaning and is meant to be: a
cheap, explainable ordering, not a semantic judgment dressed up as one.

Checked against the two confirmed gaps that were found by hand, before
this existed, to see whether it reproduces known-good results:
  - ETL_ADDRESS: the three street-abbreviation / directional-prefix criteria
    behind etl_address_street_abbreviation rank 1, 2, and 3 worst-covered.
  - ETL_EMAIL: the two dot-adjacency criteria behind etl_email_dot_adjacency
    rank 5th and 7th of 10 -- inside the flagged set, but not at the top.
So: reliable enough to decide what to read first, not reliable enough to
decide what's a finding. Read the whole flagged set, not just the top rows.

The absolute score is not meaningful on its own -- only the ordering is. The
default --threshold is a display cutoff tuned so the flagged set stays worth
reading end to end; it is not a claim that 0.45 separates covered from
uncovered.

    python -m orchestrator.tuning.diff_acceptance_criteria
    python -m orchestrator.tuning.diff_acceptance_criteria --task CALC_CALENDAR
    python -m orchestrator.tuning.diff_acceptance_criteria --report outputs/reports/acceptance_criteria/gen_and_eval_20260813_152901.txt
"""
import argparse
import glob
import math
import os
import re
from collections import Counter
from datetime import datetime

from qikly.paths import chdir_to_project_root

# Resolved from $QIKLY_PROJECT_ROOT, then the working directory, then this
# source tree -- see orchestrator/paths.py for why __file__ alone is wrong.
PROJECT_ROOT = chdir_to_project_root()

LOG_DIR = "outputs/reports/acceptance_criteria"

# Header lines gen_and_eval_acceptance_criteria.py's run() writes, e.g.
#   === CALC_CALENDAR: auto-generated (9) ===
#   === CALC_CALENDAR: real, hand-tuned (13) ===
_HEADER_RE = re.compile(r"^=== (?P<task_id>\S+): (?P<kind>auto-generated|real, hand-tuned) \((?P<n>\d+)\) ===$")
_ITEM_RE = re.compile(r"^  - (?P<text>.+)$")

# Structural filler, not domain content. Kept deliberately short: IDF already
# discounts anything both lists use heavily, so this only needs to cover words
# so ubiquitous they'd otherwise survive on rarity alone in a short list.
_STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "both", "but", "by",
    "each", "for", "from", "if", "in", "into", "is", "it", "its", "must", "not",
    "of", "on", "or", "that", "the", "their", "them", "then", "this", "to", "was",
    "were", "when", "which", "while", "with", "would",
}


def _stem(token):
    """
    Crude plural/participle stripping. Not linguistics -- just enough that
    "strings"/"string" and "rejected"/"reject" stop counting as unrelated
    vocabulary, which they otherwise do and which measurably distorted the
    ordering this module exists to produce.
    """
    for suffix in ("ies", "es", "s", "ing", "ed"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(text):
    """
    Lowercase tokens, stopwords dropped, 2-char minimum, lightly stemmed.

    snake_case identifiers are emitted both whole and split, so the real
    criteria's `customer_id` matches generated prose's "Customer ID" while
    still scoring an exact `customer_id` match higher (both forms hit).
    """
    out = []
    for raw in re.findall(r"[a-z0-9_]+", text.lower()):
        parts = [raw] + (raw.split("_") if "_" in raw else [])
        out.extend(_stem(p) for p in parts if len(p) > 1 and p not in _STOPWORDS)
    return out


def parse_report(path):
    """
    Returns {task_id: {"generated": [...], "real": [...]}} for every task in a
    gen_and_eval report. Raises ValueError if the file contains no recognizable
    section header, rather than silently returning an empty result -- a report
    whose format has drifted should be loud, not look like "no findings".
    """
    tasks = {}
    current = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            header = _HEADER_RE.match(line)
            if header:
                task_id = header.group("task_id")
                key = "generated" if header.group("kind") == "auto-generated" else "real"
                current = tasks.setdefault(task_id, {"generated": [], "real": []})[key]
                continue
            item = _ITEM_RE.match(line)
            if item and current is not None:
                current.append(item.group("text").strip())

    if not tasks:
        raise ValueError(
            f"No '=== <TASK>: auto-generated (n) ===' sections found in {path}. "
            "Is this a gen_and_eval report?"
        )
    return tasks


def _idf(all_token_lists):
    """Smoothed IDF over the documents being compared, so shared vocabulary is discounted."""
    n_docs = len(all_token_lists)
    doc_freq = Counter()
    for tokens in all_token_lists:
        for token in set(tokens):
            doc_freq[token] += 1
    return {t: math.log((n_docs + 1) / (df + 1)) + 1.0 for t, df in doc_freq.items()}


def _vector(tokens, idf):
    counts = Counter(tokens)
    return {t: c * idf.get(t, 1.0) for t, c in counts.items()}


def _containment(real_vec, gen_vec):
    """
    What fraction of this real criterion's IDF mass appears in the generated
    one. Deliberately asymmetric, unlike cosine: the question is "is this rule
    covered somewhere in the generated set", not "are these two the same
    length and shape". Cosine was tried first and scored short real criteria
    ("end_date must not be earlier than start_date") as uncovered purely
    because their nearest generated counterpart was three times longer.
    """
    if not real_vec:
        return 0.0
    total = sum(real_vec.values())
    if not total:
        return 0.0
    matched = sum(w for t, w in real_vec.items() if t in gen_vec)
    return matched / total


def coverage(real, generated):
    """
    For each real criterion, its best-matching generated criterion and that
    match's score. Returned sorted ascending, so the least-covered real
    criteria -- the candidates worth investigating -- come first.
    """
    real_tokens = [_tokens(c) for c in real]
    gen_tokens = [_tokens(c) for c in generated]
    idf = _idf(real_tokens + gen_tokens)

    real_vecs = [_vector(t, idf) for t in real_tokens]
    gen_vecs = [_vector(t, idf) for t in gen_tokens]

    rows = []
    for i, rv in enumerate(real_vecs):
        best_j, best_score = None, 0.0
        for j, gv in enumerate(gen_vecs):
            score = _containment(rv, gv)
            if score > best_score:
                best_j, best_score = j, score
        rows.append({
            "real": real[i],
            "score": best_score,
            "nearest": generated[best_j] if best_j is not None else None,
        })
    return sorted(rows, key=lambda r: r["score"])


def _out(f, line=""):
    print(line)
    if f is not None:
        f.write(line + "\n")


def _wrap(text, width, indent):
    """Word-wrap without importing textwrap for one call site."""
    words, lines, current = text.split(), [], ""
    for w in words:
        if current and len(current) + 1 + len(w) > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    return f"\n{indent}".join(lines)


def report(tasks, f=None, threshold=0.45, top=None):
    for task_id in sorted(tasks):
        real = tasks[task_id]["real"]
        generated = tasks[task_id]["generated"]
        if not real or not generated:
            _out(f, f"=== {task_id}: skipped (real={len(real)}, generated={len(generated)}) ===\n")
            continue

        rows = coverage(real, generated)
        flagged = [r for r in rows if r["score"] < threshold]
        shown = rows[:top] if top else flagged

        _out(f, f"=== {task_id}: {len(flagged)} of {len(real)} real criteria below {threshold:.2f} ===")
        if not shown:
            _out(f, "  (nothing below threshold -- every real criterion has a close generated counterpart)")
        for r in shown:
            _out(f, f"  [{r['score']:.2f}] REAL    {_wrap(r['real'], 96, ' ' * 17)}")
            if r["nearest"]:
                _out(f, f"         nearest {_wrap(r['nearest'], 96, ' ' * 17)}")
            _out(f)
        _out(f)


def _latest_report():
    candidates = sorted(glob.glob(os.path.join(LOG_DIR, "gen_and_eval_*.txt")))
    if not candidates:
        raise FileNotFoundError(
            f"No gen_and_eval_*.txt under {LOG_DIR}. Run "
            "`python -m orchestrator.tuning.gen_and_eval_acceptance_criteria` first."
        )
    return candidates[-1]


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Triage which real acceptance criteria the auto-generated set appears to miss."
    )
    parser.add_argument("--report", default=None, help="gen_and_eval report to read (default: most recent)")
    parser.add_argument("--task", default=None, help="Comma-separated task_ids to limit the diff to")
    parser.add_argument("--threshold", type=float, default=0.45, help="Flag real criteria whose best match scores below this (default: 0.45)")
    parser.add_argument("--top", type=int, default=None, help="Show this many worst-covered per task instead of everything below --threshold")
    parser.add_argument("--no-log", action="store_true", help="Print only, don't write a log file")
    return parser.parse_args()


def main():
    args = _parse_args()
    path = args.report or _latest_report()
    tasks = parse_report(path)

    if args.task:
        wanted = {t.strip() for t in args.task.split(",") if t.strip()}
        unknown = wanted - set(tasks)
        if unknown:
            raise SystemExit(f"Not in {os.path.basename(path)}: {', '.join(sorted(unknown))}. Has: {', '.join(sorted(tasks))}")
        tasks = {k: v for k, v in tasks.items() if k in wanted}

    f = None
    out_path = None
    if not args.no_log:
        os.makedirs(LOG_DIR, exist_ok=True)
        out_path = os.path.join(LOG_DIR, f"diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        f = open(out_path, "w", encoding="utf-8", newline="\n")

    try:
        _out(f, f"Source: {path}")
        _out(f, "Low score means: no generated criterion closely echoes this real one.")
        _out(f, "A candidate, not a finding -- verify against real code before treating it as one.\n")
        report(tasks, f=f, threshold=args.threshold, top=args.top)
    finally:
        if f is not None:
            f.close()

    if out_path:
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    # sys.exit(main()), not main(). The console-script wrapper setuptools
    # generates does this for you, so `qikly --validate` exited 2 on a
    # failure while `python -m qikly.cli --validate` exited 0 on the same
    # failure, printing the same message. A pipeline gating on the second
    # would have read every failure as a pass.
    sys.exit(main())
