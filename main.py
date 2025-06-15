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
    with open("static/index.html") as f:
        return HTMLResponse(content=f.read(), status_code=200)


@app.get("/albums", response_class=HTMLResponse)
async def read_albums():
    with open("static/albums.html") as f:
        return HTMLResponse(content=f.read(), status_code=200)


@app.get("/memes", response_class=HTMLResponse)
async def read_memes():
    with open("static/memes.html") as f:
        return HTMLResponse(content=f.read(), status_code=200)


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
