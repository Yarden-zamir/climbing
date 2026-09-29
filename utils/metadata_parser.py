import re
import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from redis_store import YEAR_PATTERN, parse_album_date


def inject_css_version(html_path):
    """Inject CSS version parameter for cache busting"""
    with open(html_path) as f:
        html = f.read()
    css_path = "static/css/styles.css"
    version = int(Path(css_path).stat().st_mtime)
    # Replace any existing styles.css reference (with or without query) with versioned one
    html = re.sub(
        r'href="/static/css/styles\.css(?:\?[^"}]*)?"',
        f'href="/static/css/styles.css?v={version}"',
        html
    )

    # Also version all local static JS files individually
    def version_js(match: re.Match) -> str:
        filename = match.group(1)
        js_path = Path("static/js") / filename
        try:
            js_version = int(js_path.stat().st_mtime)
        except FileNotFoundError:
            js_version = version  # fall back to css version timestamp
        return f'src="/static/js/{filename}?v={js_version}"'

    html = re.sub(r'src="/static/js/([^"\?]+\.js)(?:\?[^\"]*)?"', version_js, html)
    return html


# Only Google Photos pages and their image CDN may be fetched through the proxy endpoints.
ALLOWED_FETCH_HOSTS = ("photos.app.goo.gl", "photos.google.com", "googleusercontent.com")


def is_allowed_fetch_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_FETCH_HOSTS)


async def fetch_url(client: httpx.AsyncClient, url: str):
    """Fetch a Google Photos URL. Upstream failures become 4xx/502 with a readable detail, never 500."""
    if not is_allowed_fetch_url(url):
        raise HTTPException(status_code=400, detail="Only Google Photos URLs can be fetched")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    try:
        response = await client.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        upstream = exc.response.status_code
        if upstream in (401, 403):
            detail = "Google Photos refused access; the album must be shared with a link"
        elif upstream in (404, 410):
            detail = "Google Photos returned not found; the album or image no longer exists"
        else:
            detail = f"Google Photos responded with HTTP {upstream}"
        raise HTTPException(status_code=upstream if 400 <= upstream < 500 else 502, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Google Photos: {exc.__class__.__name__}")


def normalize_album_date(date_str: str) -> str:
    """
    Normalize album date to always include a year.
    Google Photos omits the year for current-year albums; parse_album_date infers it
    (a yearless date in the future belongs to last year).
    """
    if not date_str:
        return date_str

    date_str = date_str.strip()
    if YEAR_PATTERN.search(date_str):
        return date_str

    parsed = parse_album_date(date_str)
    year = parsed.year if parsed else datetime.now().year
    return f"{date_str}, {year}"


def parse_meta_tags(html: str, url: str):
    """Parses OG meta tags and modifies the image URL for full size."""
    soup = BeautifulSoup(html, "html.parser")

    def get_meta_tag(prop):
        tag = soup.find("meta", property=prop)
        try:
            if tag and hasattr(tag, 'attrs'):
                return tag.attrs.get('content')  # type: ignore
        except (AttributeError, TypeError):
            pass
        return None

    title = (
        get_meta_tag("og:title")
        or (soup.title.string if soup.title else "Untitled")
    )

    # Handle title parsing more safely
    if title and isinstance(title, str) and " · " in title:
        title, date = title.split(" · ", 1)
    else:
        date = ""

    # Normalize date to always include year
    if date:
        date = normalize_album_date(date)

    description = (
        get_meta_tag("og:description") or "No description available."
    )
    image_url = get_meta_tag("og:image") or ""

    if image_url and isinstance(image_url, str):
        image_url = re.sub(r"=w\d+.*$", "=s0", image_url)

    return {
        "title": title,
        "description": description,
        "imageUrl": image_url,
        "url": url,
        "date": date,
    } 
