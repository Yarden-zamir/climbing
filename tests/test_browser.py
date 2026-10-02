"""Browser tests: a real Chromium against a live server over a seeded temporary database.

They cover what the HTTP tests cannot: pages render without script errors, signed-out
write buttons prompt for sign-in, the learned-items picker, nav stability, the locations
overview map and offline rendering. Skipped when Playwright's browser is not installed.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ALBUM = "https://photos.app.goo.gl/BrowserTest0001"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Seed a database through the store, then serve it with a real uvicorn process."""
    tmp = Path(tempfile.mkdtemp(prefix="climbing-browser-"))
    env = {
        **os.environ,
        "CLIMBING_DB_PATH": str(tmp / "browser.duckdb"),
        "CLIMBING_BACKUP_DIR": str(tmp / "backups"),
        "KEYS_DIR": str(tmp / "keys"),
        "SECRET_KEY": "browser-test-secret",
        "ENVIRONMENT": "test",
        "GOOGLE_CLIENT_ID": "test",
        "GOOGLE_CLIENT_SECRET": "test",
    }
    env.pop("REDIS_HOST", None)
    seed = f"""
import asyncio, sys
sys.path.insert(0, {str(ROOT)!r})
from store import Store
from auth import SessionManager
s = Store({str(tmp / "browser.duckdb")!r})
async def main():
    await s.upsert_user("admin1", "admin@test.local", "Admin", "")
    await s.set_user_role("admin1", "admin")
    await s.add_climber("Ann Climber", ["Haifa"], ["climber", "belayer"], [], ["first lead"])
    await s.add_climber("Ben Climber", [], ["climber"])
    await s.add_location("Gita", description="Crag", latitude=32.967, longitude=35.245, custom_markers=[{{"emoji": "🅿️", "label": "Parking", "lat": 32.967, "lng": 35.245, "primary": True}}])
    await s.add_location("Shilat", description="Crag", latitude=31.92, longitude=35.01)
    await s.add_album({ALBUM!r}, ["Ann Climber", "Ben Climber"], {{"title": "Browser Album", "date": "Sep 27, 2025", "imageUrl": "https://lh3.googleusercontent.com/pw/BrowserTest=s0"}}, location="Gita")
    await s.record_learned_items("Ann Climber", {ALBUM!r}, ["rope coiler"], [])
asyncio.run(main())
s.close()
print(SessionManager().create_session_token({{"id": "admin1", "email": "admin@test.local", "name": "Admin", "role": "admin", "authenticated": True, "permissions": {{"can_create_albums": True}}}}))
"""
    cookie = subprocess.run([sys.executable, "-c", seed], env=env, capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip().splitlines()[-1]
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    import urllib.request

    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start:\n" + (proc.stdout.read() if proc.stdout else ""))
    yield {"base": base, "cookie": cookie}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser binary missing: `uv run playwright install chromium`
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


def new_page(browser, server, logged_in=False, **context_kwargs):
    ctx = browser.new_context(viewport={"width": 1200, "height": 900}, **context_kwargs)
    if logged_in:
        ctx.add_cookies([{"name": "session", "value": server["cookie"], "domain": "127.0.0.1", "path": "/"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" and "ViewTransition" not in m.text else None)
    page._errors = errors
    return page


def real_errors(page):
    # 404s for missing test images and the unconfigured OAuth login are expected in this setup
    return [e for e in page._errors if not any(code in e for code in ("400", "404", "500", "502")) and "/auth/login" not in e]


@pytest.mark.parametrize("path", ["/", "/albums", "/crew", "/locations", "/memes", "/knowledge", "/privacy"])
def test_pages_load_without_script_errors(browser, server, path):
    page = new_page(browser, server)
    page.goto(server["base"] + path, wait_until="load")
    page.wait_for_timeout(1500)
    assert page.locator("nav > a").count() >= 4
    if path != "/privacy":
        assert page.locator(".site-footer a").count() == 1
    assert real_errors(page) == []
    page.context.close()


def test_signed_out_add_album_prompts_sign_in(browser, server):
    page = new_page(browser, server)
    page.goto(server["base"] + "/albums", wait_until="load")
    page.wait_for_selector(".album-card:not(.loading)")
    page.click("#add-album-fab")
    page.wait_for_timeout(500)
    assert "Sign in" in page.locator("#toast-container").inner_text()
    assert not page.locator("#add-album-modal-overlay").evaluate("el => el.classList.contains('active')")
    page.context.close()


def test_learned_picker_marks_items_on_selected_chip(browser, server):
    page = new_page(browser, server, logged_in=True)
    page.goto(server["base"] + "/albums", wait_until="load")
    page.wait_for_selector(".album-card:not(.loading)")
    page.click("#add-album-fab")
    page.wait_for_selector("#add-album-modal.active")
    chip = page.locator("#crew-selector .crew-option", has_text="Ben Climber")
    assert not chip.locator(".learned-btn").is_visible()
    chip.click()
    chip.locator(".learned-btn").click()
    page.wait_for_selector("#learned-modal-overlay.active")
    page.locator("#learned-skills-container .skill-badge-toggleable:not(.owned)").first.click()
    page.click("#learned-done-btn")
    assert chip.locator(".learned-btn").inner_text().strip() == "⚡1"
    assert real_errors(page) == []
    page.context.close()


def test_learned_badge_links_to_album_and_spotlights_it(browser, server):
    page = new_page(browser, server)
    page.goto(server["base"] + "/crew", wait_until="load")
    page.wait_for_selector(".learned-badge")
    badge = page.locator(".learned-badge").first
    assert "Browser Album" in badge.get_attribute("title")
    badge.click()
    page.wait_for_selector(".album-card.spotlight", timeout=15000)
    assert page.locator(".album-card.spotlight").get_attribute("data-album-url") == ALBUM
    page.context.close()


def test_nav_does_not_move_after_first_paint(browser, server):
    page = new_page(browser, server, logged_in=True)
    page.goto(server["base"] + "/albums", wait_until="load")
    page.wait_for_timeout(1500)
    page.evaluate("localStorage.setItem('auth_user_cache_v1', JSON.stringify({authenticated: true, user: {id: 'admin1', email: 'admin@test.local', name: 'Admin', picture: '', role: 'admin', permissions: {}}, ts: Date.now()}))")
    page.add_init_script("""
        window.__samples = [];
        const tick = () => { const a = [...document.querySelectorAll('nav > a')]; if (a.length) window.__samples.push(a.map(x => Math.round(x.getBoundingClientRect().left)).join(',')); if (performance.now() < 3000) setTimeout(tick, 40); };
        tick();
    """)
    page.goto(server["base"] + "/crew", wait_until="load")
    page.wait_for_timeout(3200)
    samples = page.evaluate("window.__samples")
    # Allow one early sample before the stylesheet applies; after that the tabs must hold still
    settled = samples[2:]
    assert len(set(settled)) == 1, settled
    assert page.locator(".auth-slot .user-profile-dropdown").count() == 1
    page.context.close()


def test_locations_overview_map_filters(browser, server):
    page = new_page(browser, server, geolocation={"latitude": 32.08, "longitude": 34.78}, permissions=["geolocation"])
    page.goto(server["base"] + "/locations", wait_until="load")
    page.wait_for_selector("#overview-map .overview-pin")
    assert page.locator("#overview-map .overview-pin").count() == 2
    page.click("#overview-map .leaflet-marker-icon[title='Gita']")
    page.wait_for_timeout(300)
    visible = page.evaluate("[...document.querySelectorAll('[data-location-section]')].filter(s => s.style.display !== 'none').map(s => s.dataset.name)")
    assert visible == ["Gita"]
    page.click("#overview-clear")
    page.click("#overview-locate")
    page.wait_for_timeout(2500)
    first = page.locator("[data-location-section]").first
    assert first.get_attribute("data-name") == "Shilat"  # nearer to Tel Aviv than Gita
    assert "km" in first.locator("[data-role=distance]").inner_text()
    page.context.close()


def test_lists_render_offline_after_one_visit(browser, server):
    page = new_page(browser, server)
    for _ in range(2):
        for path in ("/albums", "/crew", "/locations"):
            page.goto(server["base"] + path, wait_until="load")
            page.wait_for_timeout(1500)
    page.context.set_offline(True)
    page.goto(server["base"] + "/albums", wait_until="domcontentloaded")
    page.wait_for_selector(".album-card:not(.loading)", timeout=10000)
    page.goto(server["base"] + "/crew", wait_until="domcontentloaded")
    page.wait_for_selector(".crew-face", timeout=10000)
    page.context.set_offline(False)
    page.context.close()
