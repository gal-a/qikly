# -*- coding: utf-8 -*-
"""
Did editing a prompt help?

Until now there was no way to answer that. `inputs_private/agent_defs/` has
always let anyone replace the prompts, and `--trends` would tell you after the
fact that *something* about a configuration had moved, but a run summary did
not record which prompts produced it, so two arms were indistinguishable once
they were on disk. People were invited to tune the most important text in the
tool and given no instrument.

Two halves, and the free one is the default:

  `qikly --compare-prompts TASK`
      Groups the run summaries already on disk by the prompts that produced
      them and prints both groups. No model calls, no runs, nothing written.

  `qikly --compare-prompts TASK --repeats N`
      Runs N more of each arm first, alternating, then reports. This spends
      real money and real hours, which is why it is opt-in and why the count
      is yours to choose.

**On not overclaiming.** A run is an artifact, never a rate, and the whole
reason this exists is that the project has been bitten before by reading one
run as a number. So this prints counts and ranges, says "3 of 5" rather than
"60%", and refuses to name a winner. Two arms whose medians differ by less
than their own interquartile range have not been shown to differ at all, and
the report says so in those words rather than leaving the reader to notice.

Arms are alternated rather than run in blocks, because a provider having a
bad hour would otherwise land entirely on whichever arm went second.
"""
import glob
import json
import os
import statistics
import subprocess
import sys

from qikly.paths import PROMPT_OVERRIDES_ENV

SUMMARY_DIR = os.path.join("outputs", "reports", "run_summary")
STOCK = "shipped prompts"


def arm_of(summary):
    """
    Which arm a run belongs to, read from the run's own summary.

    Summaries written before schema 7 have no `prompt_overrides` key at all.
    They are not stock, they are unknown, and calling them stock would pool
    an arm with runs that might be either. They get their own bucket.
    """
    if "prompt_overrides" not in summary:
        return None
    overrides = summary.get("prompt_overrides") or {}
    if not overrides:
        return STOCK
    return "overridden: " + ", ".join(
        "%s@%s" % (name, digest) for name, digest in sorted(overrides.items()))


def load(task_id, root=None):
    """Every summary on disk for one task, oldest first."""
    pattern = os.path.join(root or ".", SUMMARY_DIR, "%s_*.json" % task_id)
    rows = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            # The glob matches by prefix, so a task named PRICING also finds
            # every PRICING_V2 summary. Reproduced during an audit. The file
            # name is a convenience; the payload is the authority.
            if payload.get("task_id") == task_id:
                rows.append(payload)
        except (OSError, ValueError) as exc:
            print("skipping %s: %s" % (os.path.basename(path), exc),
                  file=sys.stderr)
    return rows


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _iqr(values):
    """
    The spread of the middle half, or None below three values.

    The noise yardstick, chosen over max minus min. The full range can only
    widen as runs are added, so the more evidence someone collected, the
    harder the verdict became to reach, and a single outlying run could veto
    any difference at all. The interquartile range settles as runs accumulate
    and ignores the one run where the provider had a bad hour.
    """
    if len(values) < 3:
        return None
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q3 - q1


def group(rows):
    """{arm: [summary, ...]}, with pre-schema-7 runs under None."""
    out = {}
    for row in rows:
        out.setdefault(arm_of(row), []).append(row)
    return out


def stats(rows):
    """What can honestly be said about one arm."""
    attempts = [r["total_fix_attempts"] for r in rows
                if isinstance(r.get("total_fix_attempts"), int)]
    seconds = [r["duration_seconds"] for r in rows
               if isinstance(r.get("duration_seconds"), int)]
    return {
        "n": len(rows),
        "converged": sum(1 for r in rows if r.get("passed_overall")),
        "attempts_median": _median(attempts),
        "attempts_min": min(attempts) if attempts else None,
        "attempts_max": max(attempts) if attempts else None,
        "attempts_iqr": _iqr(attempts),
        "seconds_median": _median(seconds),
    }


def _fmt(value, suffix=""):
    if value is None:
        return "-"
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return "%s%s" % (value, suffix)


def verdict(by_arm):
    """
    What the two arms do and do not show, in a sentence.

    Separated from the printing so it can be tested without parsing output,
    and so the wording lives in one place rather than being assembled from
    fragments at the call site.
    """
    everything = {k: v for k, v in by_arm.items() if k is not None}
    if len(everything) < 2:
        return ("Only one arm is present, so there is nothing to compare. "
                "Run the other arm, or check that the prompts you edited are "
                "under inputs_private/agent_defs/.")

    # Only the two best-evidenced arms are compared. Every edit produces a new
    # digest and therefore a new arm, so the ordinary way of working, edit,
    # try, edit again, leaves abandoned arms with one run each lying around.
    # Taking the smallest across all of them meant a single stale run blocked
    # that task's verdict permanently, which an audit reproduced.
    ranked = sorted(everything.items(), key=lambda kv: -len(kv[1]))
    arms = dict(ranked[:2])
    ignored = [name for name, _ in ranked[2:]]
    tail = ("" if not ignored else
            " (%d other arm(s) on disk were left out, having fewer runs.)"
            % len(ignored))
    smallest = min(len(v) for v in arms.values())
    if smallest < 3:
        return ("One arm has %d run(s). A run is an artifact, not a rate, so "
                "no comparison is made. Three or more of each is the least "
                "that is worth reading, and more is better.%s"
                % (smallest, tail))
    mismatch = incommensurable(arms)
    if mismatch:
        return ("These arms differ in more than their prompts (%s), so the "
                "comparison would not be of the prompts. Re-run both arms "
                "under one configuration.%s" % (mismatch, tail))

    # Convergence is checked before anything else, because fix attempts are
    # only comparable between arms that reached the same place. An arm that
    # collapses early takes few attempts, and on the attempts line alone that
    # reads as the faster arm. An audit reproduced exactly that: 3 of 3
    # converged at 6 attempts against 0 of 3 at 2 was reported as the second
    # arm being "worth following up", which would have sent somebody off to
    # adopt the prompt that broke their runs.
    converged = {}
    for name, rows in arms.items():
        s = stats(rows)
        converged[name] = (s["converged"], s["n"])
    if len({c / float(n) for c, n in converged.values()}) > 1:
        return ("The arms did not converge equally (%s), so their fix "
                "attempts are not comparable: an arm that gives up early "
                "takes few attempts, and that is not an improvement. "
                "Convergence is the outcome to read here, and more runs of "
                "each would be needed before even that is worth much.%s"
                % ("; ".join("%s %d of %d" % (name, c, n)
                            for name, (c, n) in sorted(converged.items())),
                   tail))

    spreads, medians = [], []
    for rows in arms.values():
        s = stats(rows)
        if s["attempts_iqr"] is None:
            return ("Not every run recorded its fix attempts, so no "
                    "comparison is made.%s" % tail)
        medians.append(s["attempts_median"])
        spreads.append(s["attempts_iqr"])
    gap = max(medians) - min(medians)
    if gap <= max(spreads):
        return ("The medians differ by %s fix attempts and the middle half "
                "of the wider arm spans %s on its own. That is a difference "
                "smaller than the noise, which is not evidence either way.%s"
                % (_fmt(gap), _fmt(max(spreads)), tail))
    return ("The medians differ by %s fix attempts, more than the middle half "
            "of either arm spans. That is worth following up with more runs; "
            "it is not yet a measurement.%s" % (_fmt(gap), tail))


def incommensurable(arms):
    """
    What differs between these arms besides the prompts, as a phrase, or "".

    `aggregate_report` already refuses to pool runs across a change of model,
    version or settings, and this reads the same provenance keys rather than
    inventing a second opinion about what makes two runs comparable. Without
    it the free mode would happily set last month's runs on one model against
    today's on another and call the difference a prompt effect.
    """
    from qikly.orchestrator.reports.aggregate_report import _COMMENSURABLE_ON

    differing = []
    for key, label in _COMMENSURABLE_ON:
        seen = set()
        for rows in arms.values():
            for row in rows:
                value = (row.get("provenance") or {}).get(key)
                if value is not None:
                    seen.add(value)
        if len(seen) > 1:
            differing.append(label)
    return ", ".join(differing)


def report(task_id, root=None):
    """Print the comparison. Returns the grouping, for tests and callers."""
    rows = load(task_id, root=root)
    by_arm = group(rows)
    if not rows:
        print("No run summaries for %s yet. Run the task first." % task_id)
        return by_arm

    print("%s: %d run(s) on disk\n" % (task_id, len(rows)))
    print("%-34s %4s %10s %18s %9s"
          % ("prompts", "runs", "converged", "fix attempts", "median"))
    print("%-34s %4s %10s %18s %9s"
          % ("", "", "", "median (min-max)", "minutes"))
    for arm in sorted(by_arm, key=lambda a: (a is None, a or "")):
        s = stats(by_arm[arm])
        name = "unrecorded (before schema 7)" if arm is None else arm
        minutes = (None if s["seconds_median"] is None
                   else round(s["seconds_median"] / 60.0, 1))
        print("%-34s %4d %10s %18s %9s"
              % (name[:34], s["n"], "%d of %d" % (s["converged"], s["n"]),
                 "%s (%s-%s)" % (_fmt(s["attempts_median"]),
                                 _fmt(s["attempts_min"]),
                                 _fmt(s["attempts_max"])),
                 _fmt(minutes)))
    if None in by_arm:
        print("\nRuns from before this was recorded cannot be assigned to an "
              "arm, so they are listed and not pooled.")
    print("\n%s" % verdict(by_arm))
    return by_arm


def load_overrides_present():
    """The agent_defs files this project overrides, ignoring the arm switch.

    Asked before spending a budget: with nothing overridden, both arms would
    be the shipped prompts and the comparison would be of a thing with
    itself.
    """
    import os as _os

    from qikly.paths import PUBLIC_INPUTS_DIR, private_inputs_dir, project_root

    mine = _os.path.join(project_root(), private_inputs_dir(), "agent_defs")
    shipped = _os.path.join(PUBLIC_INPUTS_DIR, "agent_defs")
    try:
        names = set(_os.listdir(shipped))
    except OSError:
        names = set()
    try:
        return sorted(n for n in _os.listdir(mine)
                      if n.endswith(".md") and n in names)
    except OSError:
        return []


def run_arms(task_id, repeats, runner=None):
    """
    Run `repeats` of each arm, alternating stock and overridden.

    `runner` exists so the alternation and the environment can be tested
    without spending a model budget on it. The real one shells out, because
    the arm is chosen per process and an in-process switch would have to
    survive every module that has already resolved a prompt.
    """
    runner = runner or _spawn
    order = []
    for _ in range(repeats):
        order.extend(["off", "on"])
    for i, arm in enumerate(order, 1):
        print("\n[%d/%d] %s prompts" % (i, len(order),
                                        "shipped" if arm == "off" else "your"))
        runner(task_id, arm)
    return order


def _spawn(task_id, arm):
    env = dict(os.environ)
    if arm == "off":
        env[PROMPT_OVERRIDES_ENV] = "off"
    else:
        env.pop(PROMPT_OVERRIDES_ENV, None)
    subprocess.run([sys.executable, "-m", "qikly", "--tasks", task_id],
                   env=env, stdin=subprocess.DEVNULL)
