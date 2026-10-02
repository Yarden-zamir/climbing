"""Render the Excalidraw knowledge diagram to images for the Knowledge page.

Writes static/knowledge-full.webp (lossless, high resolution) and
static/knowledge-preview.webp (small, lossy, shown while the full one loads).
Exits 0 in all cases; prints "changed" when the full image differs from the committed one.

    uv run python scripts/snapshot_knowledge.py

Needs Playwright's Chromium: uv run playwright install chromium
"""

import io
import sys
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

DIAGRAM_URL = "https://link.excalidraw.com/readonly/AtAowLIPvMThzN3XHsEf"
STATIC = Path(__file__).resolve().parent.parent / "static"
FULL = STATIC / "knowledge-full.webp"
PREVIEW = STATIC / "knowledge-preview.webp"
HIDE_UI = ".layer-ui__wrapper, .App-menu, .App-toolbar, header, .welcome-screen-center, .excalidraw .ToolIcon { display: none !important }"


def capture() -> Image.Image:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 2600, "height": 1600}, device_scale_factor=2).new_page()
        page.goto(DIAGRAM_URL, wait_until="load")
        page.wait_for_selector("canvas", timeout=120000)
        page.wait_for_timeout(8000)  # Excalidraw loads assets after the canvas appears
        page.mouse.click(1300, 800)
        page.keyboard.press("Shift+1")  # zoom to fit everything
        page.wait_for_timeout(5000)
        page.add_style_tag(content=HIDE_UI)
        page.wait_for_timeout(500)
        png = page.screenshot()
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGB")


def dense_span(ink_per_line: list[int], smooth: int = 60, gap: int = 150, floor: float = 0.12) -> tuple[int, int]:
    """Start and end of the main content along one axis.

    A line counts as content when its smoothed ink is above `floor` times the busy level
    (90th percentile). Stray notes far from the boards are sparse and fall below the floor;
    runs separated by less than `gap` pixels are joined.
    """
    n = len(ink_per_line)
    smoothed = [sum(ink_per_line[max(0, i - smooth):i + smooth]) / (2 * smooth) for i in range(n)]
    busy = sorted(smoothed)[int(n * 0.9)]
    threshold = busy * floor
    runs: list[list[int]] = []
    for i, value in enumerate(smoothed):
        if value < threshold:
            continue
        if runs and i - runs[-1][1] <= gap:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    if not runs:
        raise SystemExit("captured an empty page; Excalidraw did not render")
    start, end = max(runs, key=lambda r: sum(ink_per_line[r[0]:r[1] + 1]))
    return start, end


def crop_to_content(image: Image.Image, pad: int = 50) -> Image.Image:
    """Crop to the main boards, leaving out sparse notes drifting far from them."""
    grey = image.convert("L")
    width, height = grey.size
    pixels = grey.load()
    rows = [sum(1 for x in range(0, width, 2) if pixels[x, y] < 235) for y in range(height)]
    top, bottom = dense_span(rows)
    cols = [sum(1 for y in range(top, bottom, 2) if pixels[x, y] < 235) for x in range(width)]
    left, right = dense_span(cols)
    return image.crop((max(0, left - pad), max(0, top - pad), min(width, right + pad), min(height, bottom + pad)))


def differs(new: Image.Image, path: Path) -> bool:
    """True when the diagram changed. Anti-aliasing noise between renders stays below the threshold."""
    if not path.exists():
        return True
    old = Image.open(path).convert("RGB")
    if old.size != new.size:
        return True
    histogram = ImageChops.difference(old, new).convert("L").histogram()
    changed_pixels = sum(histogram[24:])
    return changed_pixels / (new.width * new.height) > 0.002


def main() -> None:
    image = crop_to_content(capture())
    changed = differs(image, FULL)
    image.save(FULL, "WEBP", lossless=True, quality=100, method=6)
    preview = image.copy()
    preview.thumbnail((1800, 1800))
    preview.save(PREVIEW, "WEBP", quality=78, method=6)
    print(f"full {image.size} {FULL.stat().st_size // 1024} KiB, preview {preview.size} {PREVIEW.stat().st_size // 1024} KiB")
    print("changed" if changed else "unchanged")


if __name__ == "__main__":
    sys.exit(main())
