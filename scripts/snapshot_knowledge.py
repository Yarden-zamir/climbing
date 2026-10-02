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


def crop_to_content(image: Image.Image, pad: int = 60) -> Image.Image:
    background = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, background).getbbox()
    if not box:
        raise SystemExit("captured an empty page; Excalidraw did not render")
    left, top, right, bottom = box
    return image.crop((max(0, left - pad), max(0, top - pad), min(image.width, right + pad), min(image.height, bottom + pad)))


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
