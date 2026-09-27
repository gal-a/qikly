"""
What a public Skill validator will say about ours, before one does.

Skill directories and linters check more than the spec: referential integrity,
whether the description says when to use the skill as well as what it does,
content density, how many tokens the thing costs an agent, and whether a
description is keyword-stuffed. None of that fails a build here, so this
prints the numbers and leaves the judgement to a person.

    python tools/measure_skill.py

Written 2026-09-25 from the criteria published by agentskills.io, the
agent-ecosystem skill-validator and Anthropic's authoring guidance. Re-read
those before trusting this: the checks move.
"""
import io
import os
import re
import sys

ROOT = r"C:\Code\GitHub\v_and_v\test-qikly\src\qikly\skills\qikly"


def read(path):
    return io.open(path, encoding="utf-8").read()


def frontmatter(text):
    body = text.split("---", 2)
    return body[1], body[2]


def main():
    text = read(os.path.join(ROOT, "SKILL.md"))
    front, body = frontmatter(text)

    print("=" * 66)
    print("STRUCTURE AND SPEC")
    print("=" * 66)
    name = re.search(r"^name:\s*(.+)$", front, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", front, re.M).group(1).strip()
    keys = re.findall(r"^([a-z-]+):", front, re.M)
    allowed = {"name", "description", "license", "allowed-tools", "metadata",
               "compatibility"}
    print("name              %-28s %s" % (
        name, "ok" if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
        and len(name) <= 64 else "FAILS SPEC"))
    print("description       %d chars %-19s %s" % (
        len(desc), "", "ok" if len(desc) <= 1024 else "OVER 1024"))
    print("frontmatter keys  %-28s %s" % (
        ",".join(keys), "ok" if set(keys) <= allowed else "UNKNOWN KEY"))

    print()
    print("=" * 66)
    print("DESCRIPTION QUALITY, the field that decides whether it ever loads")
    print("=" * 66)
    triggers = ("use when", "when the user", "when you")
    print("says WHEN to use it        %s" % (
        "yes" if any(t in desc.lower() for t in triggers) else "NO"))
    print("says WHAT it does         %s" % (
        "yes" if desc.split(".")[0].strip() else "NO"))
    commas = desc.count(",")
    quoted = len(re.findall(r"[\"']", desc))
    print("commas                    %d %s" % (
        commas, "(keyword-stuffing heuristics flag long comma runs)"
        if commas > 6 else ""))
    print("quote characters          %d %s" % (
        quoted, "ok" if quoted == 0 else "check: quoted terms vs prose"))
    longest = max(len(s.strip()) for s in desc.split(","))
    print("longest comma segment     %d chars" % longest)

    print()
    print("=" * 66)
    print("CONTENT DENSITY")
    print("=" * 66)
    words = body.split()
    sentences = [s for s in re.split(r"(?<=[.!?])\s", body) if s.strip()]
    code_blocks = re.findall(r"```", body)
    imperative = re.compile(
        r"^\s*(?:\*\*)?(run|read|use|write|put|fill|check|add|never|do not|ask|"
        r"name|move|start|see|open|copy|tell|set|leave)\b", re.I | re.M)
    tables = body.count("\n|")
    print("words                     %d" % len(words))
    print("approx tokens             %d  (words x 1.35)" % int(len(words) * 1.35))
    print("sentences                 %d" % len(sentences))
    print("code blocks               %d" % (len(code_blocks) // 2))
    print("headings                  %d" % len(re.findall(r"^#{1,4} ", body, re.M)))
    print("table rows                %d" % tables)
    print("list items                %d" % len(re.findall(r"^\s*[-*] ", body, re.M)))
    print("imperative openings       %d of %d sentences (%.0f%%)" % (
        len(imperative.findall(body)), len(sentences),
        100.0 * len(imperative.findall(body)) / max(len(sentences), 1)))
    weak = [w for w in ("might", "maybe", "perhaps", "possibly", "try to",
                        "generally", "usually try") if w in body.lower()]
    print("hedging words             %s" % (", ".join(weak) or "none"))

    print()
    print("=" * 66)
    print("REFERENTIAL INTEGRITY AND PROGRESSIVE DISCLOSURE")
    print("=" * 66)
    refs = re.findall(r"`?references/([A-Za-z_.]+\.md)`?", body)
    for target in sorted(set(refs)):
        path = os.path.join(ROOT, "references", target)
        print("  %-26s %s" % (target, "resolves" if os.path.isfile(path)
                              else "BROKEN LINK"))
    told_when = re.search(r"Read `references/[^`]+`\*{0,2} when", body)
    print("tells the agent WHEN to open a reference: %s" % (
        "yes" if told_when else "NO, validators flag this"))
    on_disk = sorted(os.listdir(os.path.join(ROOT, "references")))
    print("files present but never referenced: %s" % (
        [f for f in on_disk if f not in refs] or "none"))
    stray = [f for f in os.listdir(ROOT)
             if f not in ("SKILL.md", "references")]
    print("unexpected files in the skill root: %s" % (stray or "none"))

    print()
    print("=" * 66)
    print("SECURITY HYGIENE")
    print("=" * 66)
    patterns = {
        "API-key-shaped string": r"\b(sk-[A-Za-z0-9]{12,}|AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9]{10,})",
        "assignment to a secret": r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*[\"'][^\"']{8,}",
        "absolute local path": r"[A-Za-z]:\\\\Users\\\\|/home/[a-z]+/",
        "email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    }
    for label, pattern in patterns.items():
        hits = re.findall(pattern, text)
        print("  %-24s %s" % (label, hits or "none"))

    print()
    print("=" * 66)
    print("REFERENCE FILE SIZES, which only load when opened")
    print("=" * 66)
    for name in on_disk:
        raw = read(os.path.join(ROOT, "references", name))
        print("  %-26s %6d words, ~%d tokens"
              % (name, len(raw.split()), int(len(raw.split()) * 1.35)))


if __name__ == "__main__":
    sys.exit(main())
