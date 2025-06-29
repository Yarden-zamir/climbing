import math
from starlette.middleware.base import BaseHTTPMiddleware
from PIL.ExifTags import TAGS
from PIL import Image
from pathlib import Path
from fastapi.responses import JSONResponse
import datetime
from fastapi.responses import HTMLResponse, JSONResponse
import json
import httpx
import re
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles  # Import StaticFiles
from bs4 import BeautifulSoup
from fastapi.responses import FileResponse
# Initialize FastAPI app
app = FastAPI()
def inject_css_version(html_path):
    with open(html_path) as f:
        html = f.read()
    # Use file mtime as version
    css_path = "static/css/styles.css"
    version = int(Path(css_path).stat().st_mtime)
    html = html.replace(
        'href="/static/css/styles.css"',
        f'href="/static/css/styles.css?v={version}"'
    )
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
        return tag["content"] if tag else None

    title = (
        get_meta_tag("og:title")
        or (soup.title.string if soup.title else "Untitled")
    )
    title, date = title.split(" · ")
    description = (
        get_meta_tag("og:description") or "No description available."
    )
    image_url = get_meta_tag("og:image") or ""

    if image_url:
        image_url = re.sub(r"=w\d+.*$", "=s0", image_url)

    return {
        "title": title,
        "description": description,
        "imageUrl": image_url,
        "url": url,
        "date": date,
    }



@app.get("/api/crew")
def get_crew():
    climbers_dir = Path("climbers")
    albums_path = Path("static/albums.json")
    # Load albums.json
    if albums_path.exists():
        with open(albums_path) as f:
            albums = json.load(f)
    else:
        albums = {}

    # Count climbs per climber (normalize names for matching)
    climb_counts = {}
    for album in albums.values():
        for name in album.get("crew", []):
            norm = name.strip().lower()
            climb_counts[norm] = climb_counts.get(norm, 0) + 1

    crew = []
    for climber_dir in climbers_dir.iterdir():
        if not climber_dir.is_dir():
            continue
        details_path = climber_dir / "details.json"
        face_path = climber_dir / "face.png"
        if not details_path.exists() or not face_path.exists():
            continue
        with open(details_path) as f:
            details = json.load(f)
        name = climber_dir.name.replace("-", " ").title()
        norm = name.strip().lower()
        climbs = climb_counts.get(norm, 0)
        skills = details.get("skills", [])
        level_from_skills = len(skills)
        level_from_climbs = climbs / 5
        total_level = 1 + level_from_skills + level_from_climbs
        crew.append({
            "name": name,
            "face": f"/climbers/{climber_dir.name}/face.png",
            "location": details.get("Location", []),
            "skills": skills,
            "climbs": climbs,
            "level_from_climbs": level_from_climbs,
            "level_from_skills": level_from_skills,
            "level": total_level,
        })
    return JSONResponse(crew)

# --- API Routes ---
@app.get("/get-meta")
async def get_meta(url: str = Query(...)):
    """API endpoint to fetch and parse metadata from a URL."""
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        meta_data = parse_meta_tags(response.text, url)
        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        } 
        return Response(content=json.dumps(meta_data), media_type="application/json", headers=headers)


@app.get("/get-image")
async def get_image(url: str = Query(...)):
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        content_type = response.headers.get("content-type", "application/octet-stream")
        headers = {
            "Cache-Control": "public, max-age=604800, immutable"
        }
        return Response(content=response.content, media_type=content_type, headers=headers)


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTMLResponse(content=inject_css_version("static/index.html"), status_code=200)

@app.get("/albums", response_class=HTMLResponse)
async def read_albums():
    return HTMLResponse(content=inject_css_version("static/albums.html"), status_code=200)

@app.get("/memes", response_class=HTMLResponse)
async def read_memes():
    return HTMLResponse(content=inject_css_version("static/memes.html"), status_code=200)

@app.get("/crew", response_class=HTMLResponse)
async def read_crew():
    return HTMLResponse(content=inject_css_version("static/crew.html"), status_code=200)
@app.get("/api/memes")
def get_memes():
    photos_dir = Path("static/photos")
    images = []
    for img_path in sorted(photos_dir.glob("*")):
        if img_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp"]:
            continue
        date_str = ""
        try:
            with Image.open(img_path) as img:
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        tag_name = TAGS.get(tag, tag)
                        if tag_name in ("DateTimeOriginal", "DateTime"):
                            # Format: "YYYY:MM:DD HH:MM:SS"
                            date_str = value.split(" ")[0].replace(":", "-")
                            break
        except Exception:
            pass
        if not date_str:
            # fallback: file modified date
            date_str = datetime.datetime.fromtimestamp(img_path.stat().st_mtime).strftime("%Y-%m-%d")
        images.append({
            "url": f"/static/photos/{img_path.name}",
            "date": date_str,
            "name": img_path.name
        })
    return JSONResponse(images)
# app.mount("/", StaticFiles(directory="static", html=True), name="static")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/climbers", StaticFiles(directory="climbers"), name="climbers")


class NoCacheCSSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.endswith(".css"):
            response.headers["Cache-Control"] = "no-cache, max-age=0"
        return response


app.add_middleware(NoCacheCSSMiddleware)
