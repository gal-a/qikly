"""
Render a real `qikly --score` run to docs/images/qikly_score.png, for README.md.

Nothing in the picture is typed by hand: this copies docs/examples/pricing to a
temporary folder (without its answered task files), runs `qikly --score
pricing.py` there with the qikly this Python imports, and draws what it printed
followed by three of the questions from the report it wrote. The one change is
cosmetic: the temporary folder's absolute path is shown as `.`. To show the
published release rather than the source tree, run it from a fresh venv with
that release installed:

    python tools/render_score_screenshot.py

Needs Google Chrome and Pillow.
"""
import glob
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "docs", "examples", "pricing")
OUTPUT = os.path.join(ROOT, "docs", "images", "qikly_score.png")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCALE = 2
BACKGROUND = (13, 17, 23)
QUESTIONS = (1, 3, 8)   # a boundary, the other boundary, letter case: three kinds of gap

CSS = """
body{margin:0;background:#0d1117}
#t{display:inline-block;margin:24px;width:860px;border-radius:10px;overflow:hidden;
  border:1px solid #30363d;font:15px/1.55 Consolas,"Cascadia Mono",monospace;color:#c9d1d9}
.bar{background:#161b22;padding:9px 14px;display:flex;gap:8px;align-items:center}
.dot{width:12px;height:12px;border-radius:50%}
.body{background:#0d1117;padding:16px 20px 20px;white-space:pre-wrap}
.cmd{color:#e6edf3}.p{color:#2b8f95}.dim{color:#8b949e}.miss{color:#f0883e;font-weight:bold}
.q{color:#e6edf3}.h{color:#2b8f95}
"""


def run_score(work):
    env = dict(os.environ, QIKLY_NO_VERSION_CHECK="1", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-m", "qikly", "--score", "pricing.py"], cwd=work, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=900)
    if done.returncode:
        raise SystemExit("qikly --score failed:\n" + done.stdout + done.stderr)
    return done.stdout


def page(printed, work):
    lines = [l.replace(work, ".").replace("\\", "/") if work in l else l
             for l in printed.splitlines()]
    lines = [l for l in lines if l.startswith("[pricing.py]") or l.startswith("Scoring")]
    report = io.open(glob.glob(os.path.join(work, "qikly-suite-score", "*.md"))[0], encoding="utf-8").read()
    asked = dict(re.findall(r"(?m)^(\d+)\. (Your tests pass.*)$", report))
    out = ['<span class="p">$</span> <span class="cmd">qikly --score pricing.py</span>']
    for l in lines:
        text = html.escape(l)
        text = re.sub(r"(\d+ of \d+ planted faults missed \(\d+%\))", r'<span class="miss">\1</span>', text)
        out.append(text if l.startswith("[") else '<span class="dim">%s</span>' % text)
    out += ["", '<span class="h">From the report: questions your tests leave open</span>']
    for n in QUESTIONS:
        out.append('<span class="q">%d. %s</span>' % (n, html.escape(asked[str(n)]).replace("`", "")))
    dots = "".join('<span class="dot" style="background:%s"></span>' % c for c in ("#ff5f56", "#ffbd2e", "#27c93f"))
    return ('<!doctype html><meta charset="utf-8"><style>%s</style><div id="t"><div class="bar">%s</div>'
            '<div class="body">%s</div></div>' % (CSS, dots, "\n".join(out)))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "pricing")
        shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns("task_files", "__pycache__"))
        printed = run_score(work)
        source = os.path.join(tmp, "shot.html")
        raw = os.path.join(tmp, "raw.png")
        io.open(source, "w", encoding="utf-8").write(page(printed, work))
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=%d" % SCALE, "--window-size=960,1400",
                        "--screenshot=" + raw, source],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=True)
        image = Image.open(raw).convert("RGB")
    box = ImageChops.difference(image, Image.new("RGB", image.size, BACKGROUND)).getbbox()
    margin = 12 * SCALE
    image = image.crop((max(0, box[0] - margin), max(0, box[1] - margin),
                        min(image.width, box[2] + margin), min(image.height, box[3] + margin)))
    image.save(OUTPUT, optimize=True)
    print("wrote %s, %dx%d, %.0f KB" % (os.path.relpath(OUTPUT, ROOT), image.width, image.height,
                                         os.path.getsize(OUTPUT) / 1024.0))


if __name__ == "__main__":
    main()
