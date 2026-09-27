#!/usr/bin/env bash
# Install qikly and the agent CLIs worth trying the Skill in.
#
# Every install is allowed to fail on its own. These are third-party tools in
# active development, and one of them being briefly unpublishable must not
# cost you the whole bench: you can still test the others, and the script that
# follows reports which are present.
set -u

say() { printf '\n=== %s ===\n' "$1"; }

say "qikly, from this checkout"
pip install --quiet -e . || pip install --quiet qikly || echo "qikly did not install"

say "Gemini CLI"
npm install -g @google/gemini-cli >/dev/null 2>&1 \
  && echo "installed" || echo "not installed, skip the gemini row"

say "Codex CLI"
npm install -g @openai/codex >/dev/null 2>&1 \
  && echo "installed" || echo "not installed, skip the codex row"

say "What is here"
python -c "import qikly, sys; print('qikly', qikly.__version__)" 2>/dev/null \
  || echo "qikly not importable"
command -v gemini >/dev/null && echo "gemini present" || echo "gemini absent"
command -v codex  >/dev/null && echo "codex present"  || echo "codex absent"

cat <<'NEXT'

Next:

    python tools/skill_bench.py

Cursor has no web version, so it cannot be tested from here. Everything this
bench can check is free: no provider key is needed for any of it.
NEXT
