"""
Render a real `qikly --score` run to docs/images/qikly_score.gif, for README.md.

The moving counterpart of tools/render_score_screenshot.py, and built the same
way: nothing in it is typed by hand. This copies docs/examples/pricing to a
temporary folder (without its answered task files), runs `qikly --score
pricing.py` there with the qikly this Python imports, and replays what it
printed, then three questions from the report it wrote. Two cosmetic changes,
both of the kind a screen recording makes: the wait while faults are planted is
shortened to a couple of seconds, and the temporary folder's absolute path in
the report line is shown as `.`. The banner line with the date is left out.

It exists because the still image went stale: the example changed and nobody
re-ran the tool. Re-run this one whenever docs/examples/pricing changes:

    python tools/render_score_gif.py

To show the published release rather than the source tree, run it from a fresh
venv with that release installed. Needs only Pillow, and a monospace font
(Consolas, Cascadia Mono or DejaVu Sans Mono).
"""
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "docs", "examples", "pricing")
OUTPUT = os.path.join(ROOT, "docs", "images", "qikly_score.gif")
QUESTIONS = (1, 3, 8)   # a boundary, the other boundary, letter case: three kinds of gap
COMMAND = "qikly --score pricing.py"

W, H = 1000, 590
BG, BAR, FG, DIM = (13, 17, 23), (22, 27, 34), (230, 237, 243), (139, 148, 158)
ORANGE, TEAL, PROMPT = (240, 136, 62), (43, 168, 175), (63, 184, 175)

REGULAR = (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\CascadiaMono.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
           "/System/Library/Fonts/Menlo.ttc")
BOLD_FONTS = (r"C:\Windows\Fonts\consolab.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
              "/System/Library/Fonts/Menlo.ttc")


def _font(candidates):
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, 20)
    sys.exit("No monospace font found. Looked for: " + ", ".join(candidates))


FONT, BOLD = _font(REGULAR), _font(BOLD_FONTS)
CW = FONT.getlength("M")
LH, X0, Y0 = 29, 34, 78
COLS = int((W - 2 * X0) / CW)


def run_the_real_thing():
    """Score the bundled example in a temporary folder; return (output lines, report text)."""
    work = tempfile.mkdtemp(prefix="qikly-gif-")
    try:
        shutil.copy(os.path.join(EXAMPLE, "pricing.py"), work)
        shutil.copytree(os.path.join(EXAMPLE, "tests"), os.path.join(work, "tests"))
        # A project marker, so the run behaves as it does in a real project.
        with open(os.path.join(work, "pyproject.toml"), "w", encoding="utf-8") as f:
            f.write('[project]\nname = "pricing-demo"\n')
        env = dict(os.environ, PYTHONIOENCODING="utf-8", QIKLY_NO_VERSION_CHECK="1",
                   PYTHONUNBUFFERED="1", NO_COLOR="1",
                   PYTHONPATH=os.path.join(ROOT, "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
        done = subprocess.run([sys.executable, "-m", "qikly.cli", "--score", "pricing.py"], cwd=work,
                              capture_output=True, text=True, encoding="utf-8", env=env)
        lines = done.stdout.splitlines()
        reports = sorted(glob.glob(os.path.join(work, "qikly-suite-score", "pricing*.md")))
        if len(lines) < 6 or not reports:
            sys.exit("The run did not produce a score:\n" + done.stdout + done.stderr)
        stamp = re.search(r"pricing\.py_(\d{8}_\d{6})", reports[-1]).group(1)
        with io.open(reports[-1], encoding="utf-8") as f:
            return lines, f.read(), stamp
    finally:
        shutil.rmtree(work, ignore_errors=True)


def wrap(s):
    return textwrap.wrap(s, COLS, break_long_words=False, break_on_hyphens=False) or [""]


def rows_of(s, colour=FG, highlight=None):
    rows = []
    for i, piece in enumerate(wrap(s)):
        if highlight and i == 0 and highlight in piece:
            a, b = piece.split(highlight, 1)
            rows.append([(a, colour, False), (highlight, ORANGE, True), (b, colour, False)])
        else:
            rows.append([(piece, colour, False)])
    return rows


def main():
    lines, report, stamp = run_the_real_thing()
    scoring = next(l for l in lines if l.startswith("Scoring against"))
    tagged = [l for l in lines if l.startswith("[pricing.py]")]
    headline, missed, opened, nxt = tagged[0], tagged[1], tagged[2], tagged[3]
    missed = re.sub(r"one line each: .*$", "one line each: ./qikly-suite-score/pricing.py_%s.md" % stamp, missed)
    section = report[report.index("## Questions your tests leave open"):]
    found = {}
    for m in re.finditer(r"(?m)^(\d+)\. (.*)$", section):
        found.setdefault(int(m.group(1)), m.group(2))
    questions = [(n, found[n].replace("`", "")) for n in QUESTIONS]
    hl = re.search(r"\d+ of \d+ planted faults missed \(\d+%\)", headline).group(0)

    b_scoring = rows_of(scoring, DIM)
    b_out = rows_of(headline, FG, hl) + rows_of(missed) + rows_of(opened) + rows_of(nxt)
    b_title = [[("From the report: questions your tests leave open", TEAL, False)]]
    b_q = [rows_of("%d. %s" % (n, q)) for n, q in questions]

    def frame(typed, show_scoring, show_out, show_title, nq, cursor):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((8, 8, W - 9, H - 9), radius=16, outline=(48, 54, 61), width=2, fill=BG)
        d.rounded_rectangle((9, 9, W - 10, 56), radius=15, fill=BAR)
        d.rectangle((9, 40, W - 10, 56), fill=BAR)
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse((30 + i * 30, 24, 46 + i * 30, 40), fill=c)
        y = Y0
        d.text((X0, y), "$ ", font=BOLD, fill=PROMPT)
        d.text((X0 + 2 * CW, y), COMMAND[:typed], font=FONT, fill=FG)
        cx = X0 + (2 + typed) * CW
        rows = []
        if show_scoring:
            rows += b_scoring
        if show_out:
            rows += b_out
        if show_title:
            rows += [[("", FG, False)]] + b_title
        for k in range(nq):
            rows += b_q[k]
        for r in rows:
            y += LH
            x = X0
            for s, col, bold in r:
                d.text((x, y), s, font=BOLD if bold else FONT, fill=col)
                x += CW * len(s)
        if cursor:
            cx, cy = (X0, y + LH) if rows else (cx, Y0)
            d.rectangle((cx, cy + 3, cx + CW * 0.6, cy + 23), fill=DIM)
        return im

    frames, durations = [], []

    def add(im, ms):
        frames.append(im)
        durations.append(ms)

    n = len(COMMAND)
    add(frame(0, 0, 0, 0, 0, True), 500)
    add(frame(0, 0, 0, 0, 0, False), 350)
    for k in range(2, n + 1, 2):
        add(frame(k, 0, 0, 0, 0, True), 70)
    add(frame(n, 0, 0, 0, 0, True), 450)
    add(frame(n, 1, 0, 0, 0, True), 700)
    for i in range(4):                       # the real wait was about five seconds
        add(frame(n, 1, 0, 0, 0, i % 2 == 1), 400)
    add(frame(n, 1, 1, 0, 0, False), 1800)
    add(frame(n, 1, 1, 1, 0, False), 700)
    for k in (1, 2, 3):
        add(frame(n, 1, 1, 1, k, False), 1400 if k < 3 else 3200)

    palette = frames[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    quantised = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    quantised[0].save(OUTPUT, save_all=True, append_images=quantised[1:], duration=durations,
                      loop=0, optimize=True, disposal=1)
    print("wrote %s: %d frames, %.1f s, %d KB" % (OUTPUT, len(frames), sum(durations) / 1000,
                                                  os.path.getsize(OUTPUT) // 1024))
    print(headline)


if __name__ == "__main__":
    main()
