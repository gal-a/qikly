"""
Render the flow diagram in docs/design_1_case_study.md to docs/images/qikly_flow.png.

GitHub draws mermaid blocks and PyPI prints them as source, so README.md shows
this image instead. The mermaid block in design_1 stays the only source.

The PNG carries a fingerprint of the block it was drawn from, and
tests/test_readme_design_agree.py fails when the two no longer match. After
editing the diagram, run this and commit the image:

    python tools/render_flow_diagram.py

Needs Google Chrome and Pillow, and the network once, to load mermaid.js.
"""
import hashlib
import io
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "docs", "design_1_case_study.md")
OUTPUT = os.path.join(ROOT, "docs", "images", "qikly_flow.png")
FINGERPRINT_KEY = "qikly-diagram-sha256"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
SCALE = 2
PAD = 24


def diagram_source(path=SOURCE):
    with io.open(path, encoding="utf-8") as handle:
        blocks = re.findall(r"```mermaid\n(.*?)\n```", handle.read(), re.S)
    if not blocks:
        raise SystemExit("no mermaid block in %s" % path)
    return blocks[0]


def fingerprint(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def main():
    source = diagram_source()
    escaped = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    page = ('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#fff}'
            '#d{display:inline-block;padding:%dpx}</style>'
            '<div id="d"><pre class="mermaid">%s</pre></div>'
            '<script src="%s"></script>'
            '<script>mermaid.initialize({startOnLoad:true,theme:"default",'
            'fontFamily:"Segoe UI, Arial, sans-serif",'
            'flowchart:{htmlLabels:true,useMaxWidth:false}});</script>' % (PAD, escaped, MERMAID))
    with tempfile.TemporaryDirectory() as tmp:
        html = os.path.join(tmp, "diagram.html")
        raw = os.path.join(tmp, "raw.png")
        io.open(html, "w", encoding="utf-8").write(page)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=%d" % SCALE, "--window-size=1400,2200",
                        "--virtual-time-budget=15000", "--screenshot=" + raw, html],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
                       check=True)
        image = Image.open(raw).convert("RGB")
    white = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, white).getbbox()
    if box is None:
        raise SystemExit("the page rendered blank: mermaid.js probably did not load")
    margin = PAD * SCALE
    image = image.crop((max(0, box[0] - margin), max(0, box[1] - margin),
                        min(image.width, box[2] + margin), min(image.height, box[3] + margin)))
    info = PngInfo()
    info.add_text(FINGERPRINT_KEY, fingerprint(source))
    image.save(OUTPUT, pnginfo=info, optimize=True)
    print("wrote %s, %dx%d, %.0f KB" % (os.path.relpath(OUTPUT, ROOT), image.width,
                                         image.height, os.path.getsize(OUTPUT) / 1024.0))


if __name__ == "__main__":
    main()
