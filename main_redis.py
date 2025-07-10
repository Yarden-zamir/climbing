import math
from starlette.middleware.base import BaseHTTPMiddleware
from PIL.ExifTags import TAGS
from PIL import Image
from pathlib import Path
from fastapi.responses import JSONResponse
import datetime
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import json
import httpx
import re
import os
import tempfile
import shutil
import base64
from fastapi import FastAPI, HTTPException, Query, Response, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys

# OAuth imports
from config import settings
from auth import oauth_handler, get_current_user, require_auth
from fastapi import Depends

# Redis datastore import
from redis_store import RedisDataStore

# Configure logging


def setup_logging():
    """Set up comprehensive logging with both file and console handlers"""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        logs_dir / "climbing_app.log",
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)

    app_logger = logging.getLogger("climbing_app")
    app_logger.setLevel(logging.DEBUG)

    return app_logger


# Set up logging
logger = setup_logging()

# Initialize FastAPI app
app = FastAPI(title="Climbing App", description="A climbing album and crew management system")

logger.info("Starting Redis-based Climbing App initialization...")

# Initialize Redis datastore
try:
    redis_store = RedisDataStore(host='localhost', port=6379)
    logger.info("✅ Redis datastore initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize Redis: {e}")
    raise


@app.on_event("startup")
async def startup_event():
    """Initialize Redis health check on startup"""
    logger.info("FastAPI startup event triggered")
    try:
        health = await redis_store.health_check()
        if health["status"] == "healthy":
            logger.info(f"✅ Redis healthy: {health}")
        else:
            logger.error(f"❌ Redis unhealthy: {health}")
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")


async def refresh_album_metadata():
    """Background task to refresh album metadata from Google Photos every 2 minutes"""
    while True:
        try:
            # Wait 4 minutes between refreshes
            await asyncio.sleep(60*4)

            logger.info("🔄 Starting album metadata refresh...")

            # Get all albums from Redis
            albums = await redis_store.get_all_albums()

            if not albums:
                logger.info("No albums found to refresh")
                continue

            updated_count = 0
            error_count = 0

            # Refresh metadata for each album
            async with httpx.AsyncClient(timeout=30.0) as client:
                for album in albums:
                    try:
                        url = album["url"]

                        # Fetch fresh metadata from Google Photos
                        response = await fetch_url(client, url)
                        fresh_metadata = parse_meta_tags(response.text, url)

                        # Update Redis with fresh metadata
                        await redis_store.update_album_metadata(url, fresh_metadata)
                        updated_count += 1

                        # Small delay to avoid overwhelming Google Photos
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        error_count += 1
                        logger.warning(f"Failed to refresh metadata for {album.get('url', 'unknown')}: {e}")
                        continue

            logger.info(f"✅ Album metadata refresh completed: {updated_count} updated, {error_count} errors")

        except Exception as e:
            logger.error(f"❌ Album metadata refresh task failed: {e}")
            # Continue the loop even if there's an error
            continue


@app.on_event("startup")
async def start_background_tasks():
    """Start background tasks on startup"""
    logger.info("🚀 Starting background metadata refresh task...")
    asyncio.create_task(refresh_album_metadata())


def inject_css_version(html_path):
    with open(html_path) as f:
        html = f.read()
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

# === API Routes ===


@app.get("/api/crew")
async def get_crew():
    """Get all crew members from Redis"""
    try:
        crew = await redis_store.get_all_climbers()
        return JSONResponse(crew)
    except Exception as e:
        logger.error(f"Error getting crew: {e}")
        raise HTTPException(status_code=500, detail="Failed to get crew data")


@app.get("/get-meta")
async def get_meta(url: str = Query(...)):
    """API endpoint to fetch and parse metadata from a URL with Redis caching."""
    # Check cache first
    cached_meta = await redis_store.get_cached_metadata(url)
    if cached_meta:
        logger.info(f"Returning cached metadata for: {url}")
        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        }
        return Response(content=json.dumps(cached_meta), media_type="application/json", headers=headers)

    # Fetch new metadata
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        meta_data = parse_meta_tags(response.text, url)

        # Cache for 5 minutes
        await redis_store.cache_album_metadata(url, meta_data, ttl=300)

        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        }
        return Response(content=json.dumps(meta_data), media_type="application/json", headers=headers)


@app.get("/api/albums/enriched")
async def get_enriched_albums():
    """API endpoint that returns all albums with metadata from Redis."""
    try:
        albums = await redis_store.get_all_albums()
        enriched_albums = []

        for album in albums:
            # Create enriched metadata with crew status
            crew_with_status = []
            for crew_member in album.get("crew", []):
                climber_data = await redis_store.get_climber(crew_member)
                is_new = climber_data.get("is_new", False) if climber_data else False

                crew_with_status.append({
                    "name": crew_member,
                    "is_new": is_new,
                    "image_url": f"/redis-image/climber/{crew_member}/face"
                })

            enriched_albums.append({
                "url": album["url"],
                "metadata": {
                    "title": album.get("title", ""),
                    "description": album.get("description", ""),
                    "date": album.get("date", ""),
                    "imageUrl": album.get("image_url", ""),
                    "url": album["url"],
                    "crew": crew_with_status
                }
            })

        headers = {
            "Cache-Control": "public, max-age=300, stale-while-revalidate=86400"
        }
        return Response(content=json.dumps(enriched_albums), media_type="application/json", headers=headers)

    except Exception as e:
        logger.error(f"Error getting enriched albums: {e}")
        raise HTTPException(status_code=500, detail="Failed to get albums")


@app.get("/get-image")
async def get_image(url: str = Query(...)):
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        content_type = response.headers.get("content-type", "application/octet-stream")
        headers = {
            "Cache-Control": "public, max-age=604800, immutable"
        }
        return Response(content=response.content, media_type=content_type, headers=headers)

# === Redis Image Serving ===


@app.get("/redis-image/{image_type}/{identifier:path}")
async def get_redis_image(image_type: str, identifier: str):
    """Serve images stored in Redis"""
    try:
        image_data = await redis_store.get_image(image_type, identifier)
        if not image_data:
            raise HTTPException(status_code=404, detail="Image not found")

        # Determine content type
        content_type = "image/png"  # Default
        if identifier.lower().endswith(('.jpg', '.jpeg')):
            content_type = "image/jpeg"
        elif identifier.lower().endswith('.gif'):
            content_type = "image/gif"
        elif identifier.lower().endswith('.webp'):
            content_type = "image/webp"

        headers = {
            "Cache-Control": "public, max-age=604800, immutable"
        }

        return Response(
            content=image_data,
            media_type=content_type,
            headers=headers
        )

    except Exception as e:
        logger.error(f"Error serving Redis image {image_type}/{identifier}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve image")

# === HTML Pages ===


@app.get("/", response_class=HTMLResponse)
async def read_root():
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/albums", response_class=HTMLResponse)
async def read_albums():
    content = inject_css_version("static/albums.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/memes", response_class=HTMLResponse)
async def read_memes():
    content = inject_css_version("static/memes.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/knowledge", response_class=HTMLResponse)
async def read_knowledge():
    content = inject_css_version("static/index.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/crew", response_class=HTMLResponse)
async def read_crew():
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/privacy", response_class=HTMLResponse)
async def read_privacy():
    content = inject_css_version("static/privacy.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# === API Routes for Data ===


@app.get("/api/memes")
async def get_memes():
    """Get all meme images from Redis"""
    try:
        # In Redis, we'll need to store meme metadata too
        # For now, let's implement a simple approach
        all_images = []

        # This is a simplified approach - in practice, you'd want to store meme metadata in Redis
        # For now, we'll return empty list and let frontend handle it
        return JSONResponse([])

    except Exception as e:
        logger.error(f"Error getting memes: {e}")
        return JSONResponse([])


@app.get("/api/skills")
async def get_skills():
    """Get all unique skills from Redis"""
    try:
        skills = await redis_store.get_all_skills()
        return JSONResponse(skills)
    except Exception as e:
        logger.error(f"Error getting skills: {e}")
        raise HTTPException(status_code=500, detail="Failed to get skills")


@app.post("/api/upload-face")
async def upload_face(file: UploadFile = File(...), person_name: str = Form(...)):
    """Upload a face image for a new person (Redis storage)."""
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        # Read image data
        image_data = await file.read()

        # Store in Redis as temp image
        image_path = await redis_store.store_image("temp", person_name, image_data)

        return JSONResponse({
            "success": True,
            "temp_path": image_path,
            "person_name": person_name
        })

    except Exception as e:
        logger.error(f"Error uploading face: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")

# === Pydantic Models ===


class NewPerson(BaseModel):
    name: str
    skills: List[str] = []
    location: List[str] = []
    temp_image_path: Optional[str] = None


class AlbumSubmission(BaseModel):
    url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class CrewSubmission(BaseModel):
    name: str
    skills: List[str] = []
    location: List[str] = []
    temp_image_path: Optional[str] = None


class CrewEdit(BaseModel):
    original_name: str
    name: str
    skills: List[str] = []
    location: List[str] = []
    temp_image_path: Optional[str] = None


class AlbumCrewEdit(BaseModel):
    album_url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class AddSkillsRequest(BaseModel):
    crew_name: str
    skills: List[str]


def validate_google_photos_url(url: str) -> bool:
    """Validate that the URL is a Google Photos album link."""
    return bool(re.match(r"https://photos\.app\.goo\.gl/[a-zA-Z0-9]+", url))

# === CRUD Operations (replacing GitHub PR creation) ===


@app.post("/api/albums/submit")
async def submit_album(submission: AlbumSubmission, user: dict = Depends(get_current_user)):
    """Submit a new album directly to Redis (no GitHub)."""

    # Validate album URL format
    if not validate_google_photos_url(submission.url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    try:
        # Check if album already exists
        existing_album = await redis_store.get_album(submission.url)
        if existing_album:
            raise HTTPException(status_code=400, detail="Album already exists")

        # Validate crew members exist or create new ones
        for crew_name in submission.crew:
            # Check if this person is in new_people
            new_person = next((p for p in submission.new_people if p.name == crew_name), None)
            if new_person:
                # Create new climber
                try:
                    await redis_store.add_climber(
                        name=new_person.name,
                        location=new_person.location,
                        skills=new_person.skills
                    )

                    # Handle image if provided
                    if new_person.temp_image_path:
                        # Extract temp image from Redis and store as climber image
                        temp_image = await redis_store.get_image("temp", new_person.name)
                        if temp_image:
                            await redis_store.store_image("climber", f"{new_person.name}/face", temp_image)
                            await redis_store.delete_image("temp", new_person.name)

                except ValueError as e:
                    if "already exists" in str(e):
                        pass  # Climber already exists, continue
                    else:
                        raise
            else:
                # Check if existing crew member exists
                existing_climber = await redis_store.get_climber(crew_name)
                if not existing_climber:
                    raise HTTPException(status_code=400, detail=f"Crew member '{crew_name}' does not exist")

        # Fetch album metadata
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, submission.url)
            metadata = parse_meta_tags(response.text, submission.url)

        # Add album to Redis
        await redis_store.add_album(submission.url, submission.crew, metadata)

        return JSONResponse({
            "success": True,
            "message": "Album added successfully!",
            "album_url": submission.url
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting album: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit album")


@app.post("/api/crew/submit")
async def submit_crew_member(submission: CrewSubmission, user: dict = Depends(get_current_user)):
    """Submit a new crew member directly to Redis (no GitHub)."""

    # Validate name is provided
    if not submission.name or not submission.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    try:
        # Add climber to Redis
        await redis_store.add_climber(
            name=submission.name,
            location=submission.location,
            skills=submission.skills
        )

        # Handle image if provided
        if submission.temp_image_path:
            # Extract temp image from Redis and store as climber image
            temp_image = await redis_store.get_image("temp", submission.name)
            if temp_image:
                await redis_store.store_image("climber", f"{submission.name}/face", temp_image)
                await redis_store.delete_image("temp", submission.name)

        return JSONResponse({
            "success": True,
            "message": "Crew member added successfully!",
            "crew_name": submission.name
        })

    except ValueError as e:
        if "already exists" in str(e):
            raise HTTPException(status_code=400, detail="Crew member already exists")
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting crew member: {e}")
        raise HTTPException(status_code=500, detail="Failed to add crew member")


@app.post("/api/crew/edit")
async def edit_crew_member(edit_data: CrewEdit, user: dict = Depends(get_current_user)):
    """Edit an existing crew member in Redis (no GitHub)."""

    # Validate names are provided
    if not edit_data.original_name or not edit_data.original_name.strip():
        raise HTTPException(status_code=400, detail="Original name is required")
    if not edit_data.name or not edit_data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    try:
        # Handle image if provided
        if edit_data.temp_image_path:
            # Extract temp image from Redis and store as climber image
            temp_image = await redis_store.get_image("temp", edit_data.original_name)
            if temp_image:
                await redis_store.store_image("climber", f"{edit_data.name}/face", temp_image)
                await redis_store.delete_image("temp", edit_data.original_name)

        # Update climber in Redis
        await redis_store.update_climber(
            original_name=edit_data.original_name,
            name=edit_data.name,
            location=edit_data.location,
            skills=edit_data.skills
        )

        return JSONResponse({
            "success": True,
            "message": "Crew member updated successfully!",
            "crew_name": edit_data.name
        })

    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        elif "already exists" in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        else:
            raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error editing crew member: {e}")
        raise HTTPException(status_code=500, detail="Failed to edit crew member")


@app.post("/api/albums/edit-crew")
async def edit_album_crew(edit_data: AlbumCrewEdit, user: dict = Depends(get_current_user)):
    """Edit crew members for an existing album in Redis (no GitHub)."""

    # Validate album URL format
    if not validate_google_photos_url(edit_data.album_url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    try:
        # Check if album exists
        existing_album = await redis_store.get_album(edit_data.album_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Handle new people if any
        if edit_data.new_people:
            for person in edit_data.new_people:
                try:
                    await redis_store.add_climber(
                        name=person.name,
                        location=person.location,
                        skills=person.skills
                    )

                    # Handle image if provided
                    if person.temp_image_path:
                        temp_image = await redis_store.get_image("temp", person.name)
                        if temp_image:
                            await redis_store.store_image("climber", f"{person.name}/face", temp_image)
                            await redis_store.delete_image("temp", person.name)

                except ValueError as e:
                    if "already exists" in str(e):
                        pass  # Climber already exists, continue
                    else:
                        raise

        # Update album crew
        await redis_store.update_album_crew(edit_data.album_url, edit_data.crew)

        return JSONResponse({
            "success": True,
            "message": "Album crew updated successfully!",
            "album_title": existing_album.get("title", "Unknown Album")
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing album crew: {e}")
        raise HTTPException(status_code=500, detail="Failed to edit album crew")


@app.post("/api/crew/add-skills")
async def add_skills_to_crew_member(request: AddSkillsRequest):
    """Add skills to an existing crew member in Redis (no GitHub)."""

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.skills:
        raise HTTPException(status_code=400, detail="At least one skill is required")

    try:
        # Get current climber data
        existing_member = await redis_store.get_climber(request.crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Get current skills and add new ones
        current_skills = existing_member.get("skills", [])
        updated_skills = current_skills + [skill for skill in request.skills if skill not in current_skills]

        # Update climber with new skills
        await redis_store.update_climber(
            original_name=request.crew_name,
            name=request.crew_name,
            location=existing_member.get("location", []),
            skills=updated_skills
        )

        return JSONResponse({
            "success": True,
            "message": f"Skills added to {request.crew_name} successfully!",
            "crew_name": request.crew_name,
            "added_skills": [skill for skill in request.skills if skill not in current_skills]
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding skills to crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/albums/delete")
async def delete_album(album_url: str = Query(...), user: dict = Depends(get_current_user)):
    """Delete an album from Redis."""

    # Validate album URL format
    if not validate_google_photos_url(album_url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    try:
        # Check if album exists
        existing_album = await redis_store.get_album(album_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Store album title for response
        album_title = existing_album.get("title", "Unknown Album")

        # Delete the album
        deleted = await redis_store.delete_album(album_url)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete album")

        return JSONResponse({
            "success": True,
            "message": f"Album '{album_title}' deleted successfully!",
            "album_url": album_url
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting album: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete album")


@app.delete("/api/crew/delete")
async def delete_crew_member(crew_name: str = Query(...), user: dict = Depends(get_current_user)):
    """Delete a crew member from Redis."""

    # Validate crew name is provided
    if not crew_name or not crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")

    try:
        # Check if crew member exists
        existing_member = await redis_store.get_climber(crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Delete the crew member
        deleted = await redis_store.delete_climber(crew_name)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete crew member")

        return JSONResponse({
            "success": True,
            "message": f"Crew member '{crew_name}' deleted successfully!",
            "crew_name": crew_name
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete crew member")


@app.get("/api/albums/validate-url")
async def validate_album_url(url: str = Query(...)):
    """Validate if an album URL is valid and doesn't already exist in Redis."""

    # Validate URL format
    if not validate_google_photos_url(url):
        return JSONResponse({
            "valid": False,
            "error": "Invalid Google Photos URL format"
        })

    try:
        # Check if album already exists in Redis
        existing_album = await redis_store.get_album(url)
        if existing_album:
            return JSONResponse({
                "valid": False,
                "error": "Album already exists"
            })

        # Fetch metadata to validate URL
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, url)
            meta_data = parse_meta_tags(response.text, url)
            headers = {
                "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
            }
            meta_data["valid"] = True
            return JSONResponse(meta_data, headers=headers)

    except Exception as e:
        return JSONResponse({
            "valid": False,
            "error": "Failed to fetch album metadata"
        })

# === Health Check ===


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    try:
        health = await redis_store.health_check()
        return JSONResponse(health)
    except Exception as e:
        return JSONResponse({
            "status": "unhealthy",
            "error": str(e)
        }, status_code=500)

# ============= OAuth Authentication Routes =============


@app.get("/auth/login")
async def login():
    """Initiate Google OAuth login"""
    if not settings.validate_oauth_config():
        raise HTTPException(
            status_code=500,
            detail="OAuth not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    auth_url = oauth_handler.generate_auth_url()
    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def auth_callback(code: str = None, state: str = None, error: str = None):
    """Handle OAuth callback from Google"""

    if error:
        logger.error(f"OAuth error: {error}")
        return RedirectResponse(url="/?error=oauth_error")

    if not code:
        logger.error("No authorization code received")
        return RedirectResponse(url="/?error=no_code")

    try:
        # Exchange code for token
        token_data = await oauth_handler.exchange_code_for_token(code)
        access_token = token_data.get("access_token")

        if not access_token:
            logger.error("No access token received")
            return RedirectResponse(url="/?error=no_token")

        # Get user info
        user_info = await oauth_handler.get_user_info(access_token)

        # Prepare user session data
        user_session_data = {
            "id": user_info.get("id"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            "verified_email": user_info.get("verified_email", False),
            "authenticated": True,
            "login_time": datetime.datetime.now().isoformat()
        }

        # Store session in Redis
        session_id = oauth_handler.session_manager.generate_session_id()
        await redis_store.store_session(session_id, user_session_data)

        # Create session and redirect
        response = RedirectResponse(url="/")
        oauth_handler.session_manager.set_session_cookie(response, user_session_data)

        logger.info(f"User logged in: {user_info.get('email')}")
        return response

    except Exception as e:
        logger.error(f"OAuth callback error: {e}", exc_info=True)
        return RedirectResponse(url="/?error=auth_failed")


@app.get("/auth/logout")
async def logout():
    """Logout user and clear session"""
    response = RedirectResponse(url="/")
    oauth_handler.session_manager.clear_session_cookie(response)
    return response


@app.get("/api/auth/user")
async def get_auth_user(user: dict = Depends(get_current_user)):
    """Get current authenticated user info"""
    if user:
        return {
            "authenticated": True,
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "picture": user.get("picture"),
                "verified_email": user.get("verified_email", False)
            }
        }
    else:
        return {"authenticated": False, "user": None}


@app.get("/api/auth/status")
async def auth_status(user: dict = Depends(get_current_user)):
    """Get authentication status"""
    return {
        "authenticated": user is not None,
        "user_email": user.get("email") if user else None
    }

# ============= End OAuth Routes =============

# Middleware setup


class CaseInsensitiveMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Only make API routes case insensitive, not static file routes
        if request.url.path.startswith("/api/"):
            scope = request.scope.copy()
            scope["path"] = request.url.path.lower()
            scope["raw_path"] = request.url.path.lower().encode()
            from starlette.requests import Request
            request = Request(scope, request.receive)

        response = await call_next(request)
        return response


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Apply no-cache headers to static assets and HTML pages
        path = request.url.path

        # Cache-bust CSS, JS, and HTML files
        if (path.endswith((".css", ".js", ".html")) or
            path in ["/", "/albums", "/memes", "/crew"] or
                path.startswith("/static/")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


# Mount static files and add middleware
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(CaseInsensitiveMiddleware)
app.add_middleware(NoCacheMiddleware)
