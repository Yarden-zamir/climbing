import re
import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from pathlib import Path


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


async def fetch_url(client: httpx.AsyncClient, url: str):
    """Generic helper to fetch a URL and handle errors."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        response = await client.get(
            url, headers=headers, follow_redirects=True
        )
        response.raise_for_status()
        return response
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400, detail=f"Error fetching URL: {exc}"
        )


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
