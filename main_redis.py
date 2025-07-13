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

# Permissions system import
from permissions import PermissionsManager, ResourceType, UserRole

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

# Initialize Permissions Manager
try:
    permissions_manager = PermissionsManager(redis_store)
    logger.info("✅ Permissions manager initialized successfully")

    # Test basic functionality
    test_permissions = permissions_manager.get_user_permissions("user")
    logger.info(f"✅ Permissions manager test successful: {test_permissions}")
except Exception as e:
    logger.error(f"❌ Failed to initialize Permissions Manager: {e}", exc_info=True)
    # Create a fallback permissions manager that won't break the app
    permissions_manager = None


@app.on_event("startup")
async def startup_event():
    """Initialize Redis health check and run migrations on startup"""
    logger.info("FastAPI startup event triggered")
    try:
        health = await redis_store.health_check()
        if health["status"] == "healthy":
            logger.info(f"✅ Redis healthy: {health}")
        else:
            logger.error(f"❌ Redis unhealthy: {health}")
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    # Run ownership format migration if permissions manager is available
    if permissions_manager is not None:
        try:
            logger.info("Running ownership format migration...")
            migrated = await permissions_manager.migrate_ownership_to_sets()
            logger.info(f"✅ Ownership migration completed: {migrated}")
        except Exception as e:
            logger.error(f"❌ Ownership migration failed: {e}")


async def perform_album_metadata_refresh():
    """Perform album metadata refresh - can be called manually or automatically"""
    logger.info("🔄 Starting album metadata refresh...")

    # Get all albums from Redis
    albums = await redis_store.get_all_albums()

    if not albums:
        logger.info("No albums found to refresh")
        return {"updated": 0, "errors": 0, "message": "No albums found to refresh"}

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
    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Refresh completed: {updated_count} updated, {error_count} errors"
    }


async def refresh_album_metadata():
    """Background task to refresh album metadata from Google Photos once per day"""
    while True:
        try:
            # Wait 24 hours between refreshes (once per day)
            await asyncio.sleep(60*60*24)

            await perform_album_metadata_refresh()

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
        raise HTTPException(status_code=500, detail="Unable to retrieve crew member data. Please try again later.")


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
        raise HTTPException(status_code=500, detail="Unable to retrieve album data. Please try again later.")


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


@app.get("/admin", response_class=HTMLResponse)
async def read_admin():
    """Serve the admin panel page"""
    content = inject_css_version("static/admin.html")
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


@app.get("/api/achievements")
async def get_achievements():
    """Get all unique achievements from Redis"""
    try:
        achievements = await redis_store.get_all_achievements()
        return JSONResponse(achievements)
    except Exception as e:
        logger.error(f"Error getting achievements: {e}")
        raise HTTPException(status_code=500, detail="Failed to get achievements")


@app.post("/api/achievements")
async def add_achievement(request: dict, user: dict = Depends(get_current_user)):
    """Add a new achievement"""
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "admin")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

        achievement_name = request.get("name", "").strip()
        if not achievement_name:
            raise HTTPException(status_code=400, detail="Achievement name is required")

        # Add the achievement to Redis
        redis_store.redis.sadd("index:achievements:all", achievement_name)
        
        logger.info(f"Added achievement: {achievement_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Achievement '{achievement_name}' added successfully"})
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to add achievement")


@app.delete("/api/achievements/{achievement_name}")
async def delete_achievement(achievement_name: str, user: dict = Depends(get_current_user)):
    """Delete an achievement"""
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "admin")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

        # Remove the achievement from Redis
        redis_store.redis.srem("index:achievements:all", achievement_name)
        
        # Also remove from all climbers who have this achievement
        all_climbers = await redis_store.get_all_climbers()
        for climber in all_climbers:
            if achievement_name in climber.get("achievements", []):
                updated_achievements = [a for a in climber["achievements"] if a != achievement_name]
                await redis_store.update_climber(
                    original_name=climber["name"],
                    achievements=updated_achievements
                )
        
        logger.info(f"Deleted achievement: {achievement_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Achievement '{achievement_name}' deleted successfully"})
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete achievement")


@app.post("/api/upload-face")
async def upload_face(file: UploadFile = File(...), person_name: str = Form(...)):
    """Upload a face image for a new person (Redis storage)."""
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="Please upload a valid image file (JPG, PNG, GIF, or WebP).")

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
    achievements: List[str] = []
    temp_image_path: Optional[str] = None


class AlbumSubmission(BaseModel):
    url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class CrewSubmission(BaseModel):
    name: str
    skills: List[str] = []
    location: List[str] = []
    achievements: List[str] = []
    temp_image_path: Optional[str] = None


class CrewEdit(BaseModel):
    original_name: str
    name: str
    skills: List[str] = []
    location: List[str] = []
    achievements: List[str] = []
    temp_image_path: Optional[str] = None


class AlbumCrewEdit(BaseModel):
    album_url: str
    crew: List[str]
    new_people: Optional[List[NewPerson]] = []


class AddSkillsRequest(BaseModel):
    crew_name: str
    skills: List[str]


class AddAchievementsRequest(BaseModel):
    crew_name: str
    achievements: List[str]


def validate_google_photos_url(url: str) -> bool:
    """Validate that the URL is a Google Photos album link."""
    return bool(re.match(r"https://photos\.app\.goo\.gl/[a-zA-Z0-9]+", url))

# === CRUD Operations (replacing GitHub PR creation) ===


@app.post("/api/albums/submit")
async def submit_album(submission: AlbumSubmission, user: dict = Depends(get_current_user)):
    """Submit a new album directly to Redis (no GitHub)."""

    # Validate album URL format
    if not validate_google_photos_url(submission.url):
        raise HTTPException(status_code=400, detail="Please provide a valid Google Photos album URL (e.g., https://photos.app.goo.gl/...)")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check permissions and submission limits if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "create_album")

                can_create = await permissions_manager.check_submission_limits(user_id, ResourceType.ALBUM)
                if not can_create:
                    raise HTTPException(
                        status_code=403,
                        detail="You have reached your album creation limit. Contact an admin for approval."
                    )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="You don't have permission to create albums. Please contact an administrator.")

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
                        skills=new_person.skills,
                        achievements=new_person.achievements
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

        # Set resource ownership (if permissions manager is available)
        if permissions_manager:
            try:
                await permissions_manager.set_resource_owner(ResourceType.ALBUM, submission.url, user_id)
                await permissions_manager.increment_user_creation_count(user_id, ResourceType.ALBUM)
            except Exception as perm_error:
                logger.error(f"Failed to set resource ownership: {perm_error}")

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
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check permissions and submission limits if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "create_crew")

                can_create = await permissions_manager.check_submission_limits(user_id, ResourceType.CREW_MEMBER)
                if not can_create:
                    raise HTTPException(
                        status_code=403,
                        detail="You have reached your crew member creation limit. Contact an admin for approval."
                    )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="You don't have permission to create crew members. Please contact an administrator.")

        # Add climber to Redis
        await redis_store.add_climber(
            name=submission.name,
            location=submission.location,
            skills=submission.skills,
            achievements=submission.achievements
        )

        # Handle image if provided
        if submission.temp_image_path:
            # Extract temp image from Redis and store as climber image
            temp_image = await redis_store.get_image("temp", submission.name)
            if temp_image:
                await redis_store.store_image("climber", f"{submission.name}/face", temp_image)
                await redis_store.delete_image("temp", submission.name)

        # Set resource ownership and increment count if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.set_resource_owner(ResourceType.CREW_MEMBER, submission.name, user_id)
                await permissions_manager.increment_user_creation_count(user_id, ResourceType.CREW_MEMBER)
            except Exception as e:
                logger.warning(f"Failed to set ownership/increment count: {e}")

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
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, edit_data.original_name, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail=f"You don't have permission to edit crew member '{edit_data.original_name}'. You can only edit crew members you created.")
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
            skills=edit_data.skills,
            achievements=edit_data.achievements
        )

        # Update ownership if name changed and permissions system is available
        if edit_data.original_name != edit_data.name and permissions_manager is not None:
            try:
                await permissions_manager.transfer_resource_ownership(
                    ResourceType.CREW_MEMBER, edit_data.original_name, user_id, user_id
                )
            except Exception as e:
                logger.warning(f"Failed to transfer resource ownership: {e}")

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
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if album exists
        existing_album = await redis_store.get_album(edit_data.album_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.ALBUM, edit_data.album_url, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="You don't have permission to edit this album. You can only edit albums you created.")

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
async def add_skills_to_crew_member(request: AddSkillsRequest, user: dict = Depends(get_current_user)):
    """Add skills to an existing crew member in Redis (no GitHub)."""

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.skills:
        raise HTTPException(status_code=400, detail="At least one skill is required")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get current climber data
        existing_member = await redis_store.get_climber(request.crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, request.crew_name, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail=f"You don't have permission to modify crew member '{request.crew_name}'. You can only edit crew members you created.")

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


@app.post("/api/crew/add-achievements")
async def add_achievements_to_crew_member(request: AddAchievementsRequest, user: dict = Depends(get_current_user)):
    """Add achievements to an existing crew member in Redis (no GitHub)."""

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.achievements:
        raise HTTPException(status_code=400, detail="At least one achievement is required")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get current climber data
        existing_member = await redis_store.get_climber(request.crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, request.crew_name, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail=f"You don't have permission to modify crew member '{request.crew_name}'. You can only edit crew members you created.")

        # Get current achievements and add new ones
        current_achievements = existing_member.get("achievements", [])
        updated_achievements = current_achievements + [achievement for achievement in request.achievements if achievement not in current_achievements]

        # Update climber with new achievements
        await redis_store.update_climber(
            original_name=request.crew_name,
            name=request.crew_name,
            location=existing_member.get("location", []),
            skills=existing_member.get("skills", []),
            tags=existing_member.get("tags", []),
            achievements=updated_achievements
        )

        return JSONResponse({
            "success": True,
            "message": f"Achievements added to {request.crew_name} successfully!",
            "crew_name": request.crew_name,
            "added_achievements": [achievement for achievement in request.achievements if achievement not in current_achievements]
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding achievements to crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/albums/delete")
async def delete_album(album_url: str = Query(...), user: dict = Depends(get_current_user)):
    """Delete an album from Redis."""

    # Validate album URL format
    if not validate_google_photos_url(album_url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if album exists
        existing_album = await redis_store.get_album(album_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Check resource access permissions
        await permissions_manager.require_resource_access(
            user_id, ResourceType.ALBUM, album_url, "delete"
        )

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
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if crew member exists
        existing_member = await redis_store.get_climber(crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions
        await permissions_manager.require_resource_access(
            user_id, ResourceType.CREW_MEMBER, crew_name, "delete"
        )

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

        # Prepare user session data (basic version for now)
        user_session_data = {
            "id": user_info.get("id"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            "verified_email": user_info.get("verified_email", False),
            "authenticated": True,
            "login_time": datetime.datetime.now().isoformat()
        }

        # Enable permissions integration
        if permissions_manager is not None:
            try:
                # Create or update user in permissions system
                user_record = await permissions_manager.create_or_update_user(user_info)
                user_session_data["role"] = user_record.get("role", "user")
                
                # Get permissions for session
                permissions = permissions_manager.get_user_permissions(user_record.get("role", "user"))
                user_session_data["permissions"] = {
                    "can_create_albums": permissions.can_create_albums,
                    "can_create_crew": permissions.can_create_crew,
                    "can_edit_own_resources": permissions.can_edit_own_resources,
                    "can_delete_own_resources": permissions.can_delete_own_resources,
                    "can_edit_all_resources": permissions.can_edit_all_resources,
                    "can_delete_all_resources": permissions.can_delete_all_resources,
                    "can_manage_users": permissions.can_manage_users
                }
                
                logger.info(f"User {user_info.get('email')} logged in with role: {user_record.get('role', 'user')}")
            except Exception as e:
                logger.error(f"Error integrating with permissions system: {e}")
                # Fall back to basic session data
                user_session_data["role"] = "user"
                user_session_data["permissions"] = {}
        else:
            logger.warning("Permissions system not available, using basic session data")
            user_session_data["role"] = "user"
            user_session_data["permissions"] = {}

        # Create session and redirect (SessionManager handles both token creation and cookie setting)
        response = RedirectResponse(url="/")
        oauth_handler.session_manager.set_session_cookie(response, user_session_data)

        logger.info(f"🎉 User logged in successfully: {user_info.get('email')}")
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
                "verified_email": user.get("verified_email", False),
                "role": user.get("role", "user"),
                "permissions": user.get("permissions", {})
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

# ============= Admin Panel API Routes =============


@app.get("/api/admin/users")
async def get_all_users_admin(user: dict = Depends(get_current_user)):
    """Get all users with their roles and resource counts (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        users = await permissions_manager.get_all_users()

        # Enhance user data with resource counts
        enhanced_users = []
        for user_record in users:
            try:
                # Ensure user record has required fields
                if not user_record or not user_record.get("id"):
                    logger.warning(f"Skipping invalid user record: {user_record}")
                    continue
                    
                user_id = user_record["id"]
                user_albums = await permissions_manager.get_user_resources(user_id, ResourceType.ALBUM)
                user_crew = await permissions_manager.get_user_resources(user_id, ResourceType.CREW_MEMBER)

                # Convert permissions to JSON-serializable format
                permissions = permissions_manager.get_user_permissions(user_record.get("role", "user"))
                permissions_dict = {
                    "can_create_albums": permissions.can_create_albums,
                    "can_create_crew": permissions.can_create_crew,
                    "can_edit_own_resources": permissions.can_edit_own_resources,
                    "can_delete_own_resources": permissions.can_delete_own_resources,
                    "can_edit_all_resources": permissions.can_edit_all_resources,
                    "can_delete_all_resources": permissions.can_delete_all_resources,
                    "can_manage_users": permissions.can_manage_users,
                    "submission_limits": {
                        "max_albums": permissions.submission_limits.max_albums if permissions.submission_limits else None,
                        "max_crew_members": permissions.submission_limits.max_crew_members if permissions.submission_limits else None,
                        "requires_approval": permissions.submission_limits.requires_approval if permissions.submission_limits else None
                    } if permissions.submission_limits else None
                }
            except Exception as e:
                logger.warning(f"Failed to get resource counts for user {user_record.get('id', 'unknown')}: {e}")
                user_albums, user_crew = [], []
                permissions_dict = {}

            enhanced_user = {
                **user_record,
                "owned_albums": len(user_albums),
                "owned_crew_members": len(user_crew),
                "permissions": permissions_dict
            }
            enhanced_users.append(enhanced_user)

        return JSONResponse(enhanced_users)

    except Exception as e:
        logger.error(f"Error getting users for admin: {e}")
        raise HTTPException(status_code=500, detail="Failed to get users")


@app.post("/api/admin/users/{target_user_id}/role")
async def update_user_role_admin(target_user_id: str, new_role: str, user: dict = Depends(get_current_user)):
    """Update a user's role (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Validate role
        role_enum = UserRole(new_role)

        # Update user role
        success = await permissions_manager.update_user_role(target_user_id, role_enum)

        if not success:
            raise HTTPException(status_code=404, detail="User not found")

        return JSONResponse({
            "success": True,
            "message": f"User role updated to {new_role}",
            "user_id": target_user_id,
            "new_role": new_role
        })

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")
    except Exception as e:
        logger.error(f"Error updating user role: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user role")


@app.post("/api/admin/resources/assign")
async def assign_resource_to_user(
    resource_type: str = Form(...),
    resource_id: str = Form(...),
    target_user_id: str = Form(...),
    user: dict = Depends(get_current_user)
):
    """Assign a resource to a user (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Validate resource type
        resource_type_enum = ResourceType(resource_type)

        # Check if resource exists
        if resource_type_enum == ResourceType.ALBUM:
            resource = await redis_store.get_album(resource_id)
        elif resource_type_enum == ResourceType.CREW_MEMBER:
            resource = await redis_store.get_climber(resource_id)

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Check if target user exists
        target_user = await permissions_manager.get_user(target_user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")

        # Check if user is already an owner
        is_already_owner = await permissions_manager.is_resource_owner(resource_type_enum, resource_id, target_user_id)

        if is_already_owner:
            message = f"{target_user['name']} is already an owner of this resource"
        else:
            # Add new owner (supports multiple owners)
            await permissions_manager.add_resource_owner(resource_type_enum, resource_id, target_user_id)
            current_owners = await permissions_manager.get_resource_owners(resource_type_enum, resource_id)
            owner_count = len(current_owners)
            if owner_count == 1:
                message = f"Added {target_user['name']} as the owner of this resource"
            else:
                message = f"Added {target_user['name']} as an owner of this resource (now {owner_count} owners total)"

        return JSONResponse({
            "success": True,
            "message": message,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "new_owner": target_user_id
        })

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")
    except Exception as e:
        logger.error(f"Error adding owner: {e}")
        raise HTTPException(status_code=500, detail="Failed to add owner")


@app.post("/api/admin/resources/remove-owner")
async def remove_resource_owner(
    resource_type: str = Form(...),
    resource_id: str = Form(...),
    owner_id: str = Form(...),
    user: dict = Depends(get_current_user)
):
    """Remove an owner from a resource (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Validate resource type
        resource_type_enum = ResourceType(resource_type)

        # Check if resource exists
        if resource_type_enum == ResourceType.ALBUM:
            resource = await redis_store.get_album(resource_id)
        elif resource_type_enum == ResourceType.CREW_MEMBER:
            resource = await redis_store.get_climber(resource_id)

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Check if owner user exists
        owner_user = await permissions_manager.get_user(owner_id)
        if not owner_user:
            raise HTTPException(status_code=404, detail="Owner user not found")

        # Check if user is actually an owner
        is_owner = await permissions_manager.is_resource_owner(resource_type_enum, resource_id, owner_id)
        if not is_owner:
            raise HTTPException(status_code=400, detail=f"{owner_user['name']} is not an owner of this resource")

        # Get current owners count before removal
        current_owners = await permissions_manager.get_resource_owners(resource_type_enum, resource_id)

        # Prevent removing the last owner
        if len(current_owners) <= 1:
            raise HTTPException(
                status_code=400, detail="Cannot remove the last owner. Resource must have at least one owner.")

        # Remove the owner
        await permissions_manager.remove_resource_owner(resource_type_enum, resource_id, owner_id)

        # Get updated count
        remaining_owners = await permissions_manager.get_resource_owners(resource_type_enum, resource_id)
        remaining_count = len(remaining_owners)

        if remaining_count == 1:
            message = f"Removed {owner_user['name']} as owner. Resource now has 1 owner remaining."
        else:
            message = f"Removed {owner_user['name']} as owner. Resource now has {remaining_count} owners remaining."

        return JSONResponse({
            "success": True,
            "message": message,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "removed_owner": owner_id,
            "remaining_owners": remaining_count
        })

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resource type")
    except Exception as e:
        logger.error(f"Error removing owner: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove owner")


@app.get("/api/admin/resources/unowned")
async def get_unowned_resources(user: dict = Depends(get_current_user)):
    """Get all resources without owners (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        unowned_albums = await permissions_manager.get_unowned_resources(ResourceType.ALBUM)
        unowned_crew = await permissions_manager.get_unowned_resources(ResourceType.CREW_MEMBER)

        # Get details for unowned resources
        album_details = []
        for album_url in unowned_albums:
            album_data = await redis_store.get_album(album_url)
            if album_data:
                album_details.append({
                    "type": "album",
                    "id": album_url,
                    "title": album_data.get("title", "Unknown Album"),
                    "url": album_url,
                    "created_at": album_data.get("created_at", "")
                })

        crew_details = []
        for crew_name in unowned_crew:
            crew_data = await redis_store.get_climber(crew_name)
            if crew_data:
                crew_details.append({
                    "type": "crew_member",
                    "id": crew_name,
                    "name": crew_name,
                    "level": crew_data.get("level", 1),
                    "created_at": crew_data.get("created_at", "")
                })

        return JSONResponse({
            "albums": album_details,
            "crew_members": crew_details,
            "total": len(album_details) + len(crew_details)
        })

    except Exception as e:
        logger.error(f"Error getting unowned resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to get unowned resources")


@app.get("/api/admin/resources/all")
async def get_all_resources_with_owners(user: dict = Depends(get_current_user)):
    """Get all resources with their owner information (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get all albums
        all_albums = redis_store.redis.smembers("index:albums:all")
        album_details = []

        for album_url in all_albums:
            album_data = await redis_store.get_album(album_url)
            if album_data:
                # Get owner information (multiple owners)
                owner_ids = await permissions_manager.get_resource_owners(ResourceType.ALBUM, album_url)
                owners_info = []

                for owner_id in owner_ids:
                    owner_user = await permissions_manager.get_user(owner_id)
                    if owner_user:
                        owners_info.append({
                            "id": owner_id,
                            "name": owner_user.get("name", "Unknown"),
                            "email": owner_user.get("email", ""),
                            "picture": owner_user.get("picture", "")
                        })

                album_details.append({
                    "type": "album",
                    "id": album_url,
                    "title": album_data.get("title", "Unknown Album"),
                    "url": album_url,
                    "created_at": album_data.get("created_at", ""),
                    "owners": owners_info
                })

        # Get all crew members
        all_crew = redis_store.redis.smembers("index:climbers:all")
        crew_details = []

        for crew_name in all_crew:
            crew_data = await redis_store.get_climber(crew_name)
            if crew_data:
                # Get owner information (multiple owners)
                owner_ids = await permissions_manager.get_resource_owners(ResourceType.CREW_MEMBER, crew_name)
                owners_info = []

                for owner_id in owner_ids:
                    owner_user = await permissions_manager.get_user(owner_id)
                    if owner_user:
                        owners_info.append({
                            "id": owner_id,
                            "name": owner_user.get("name", "Unknown"),
                            "email": owner_user.get("email", ""),
                            "picture": owner_user.get("picture", "")
                        })

                crew_details.append({
                    "type": "crew_member",
                    "id": crew_name,
                    "name": crew_name,
                    "level": crew_data.get("level", 1),
                    "created_at": crew_data.get("created_at", ""),
                    "owners": owners_info
                })

        # Sort by creation date (newest first)
        all_resources = album_details + crew_details
        all_resources.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return JSONResponse({
            "resources": all_resources,
            "total": len(all_resources),
            "albums": len(album_details),
            "crew_members": len(crew_details)
        })

    except Exception as e:
        logger.error(f"Error getting all resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to get all resources")


@app.post("/api/admin/migrate-resources")
async def migrate_existing_resources(user: dict = Depends(get_current_user)):
    """Migrate existing resources to system ownership (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        migrated = await permissions_manager.migrate_existing_resources_to_system_ownership()

        return JSONResponse({
            "success": True,
            "message": "Resources migrated successfully",
            "migrated": migrated
        })

    except Exception as e:
        logger.error(f"Error migrating resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to migrate resources")


@app.post("/api/admin/migrate-ownership")
async def migrate_ownership_format(user: dict = Depends(get_current_user)):
    """Migrate ownership format from strings to sets (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        migrated = await permissions_manager.migrate_ownership_to_sets()

        return JSONResponse({
            "success": True,
            "message": "Ownership format migrated successfully",
            "migrated": migrated
        })

    except Exception as e:
        logger.error(f"Error migrating ownership format: {e}")
        raise HTTPException(status_code=500, detail="Failed to migrate ownership format")


@app.post("/api/admin/refresh-metadata")
async def manual_refresh_metadata(user: dict = Depends(get_current_user)):
    """Manually trigger album metadata refresh (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        logger.info(f"Manual metadata refresh triggered by admin user {user.get('email')}")
        result = await perform_album_metadata_refresh()

        return JSONResponse({
            "success": True,
            "message": result["message"],
            "updated": result["updated"],
            "errors": result["errors"]
        })

    except Exception as e:
        logger.error(f"Error during manual metadata refresh: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh metadata")


@app.get("/api/admin/stats")
async def get_admin_stats(user: dict = Depends(get_current_user)):
    """Get system statistics (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get users by role
        admin_users = await permissions_manager.get_users_by_role(UserRole.ADMIN)
        regular_users = await permissions_manager.get_users_by_role(UserRole.USER)
        pending_users = await permissions_manager.get_users_by_role(UserRole.PENDING)

        # Get resource counts
        all_albums = redis_store.redis.smembers("index:albums:all")
        all_crew = redis_store.redis.smembers("index:climbers:all")

        # Get unowned resources
        unowned_albums = await permissions_manager.get_unowned_resources(ResourceType.ALBUM)
        unowned_crew = await permissions_manager.get_unowned_resources(ResourceType.CREW_MEMBER)

        return JSONResponse({
            "users": {
                "total": len(admin_users) + len(regular_users) + len(pending_users),
                "admins": len(admin_users),
                "regular": len(regular_users),
                "pending": len(pending_users)
            },
            "resources": {
                "albums": {
                    "total": len(all_albums),
                    "unowned": len(unowned_albums)
                },
                "crew_members": {
                    "total": len(all_crew),
                    "unowned": len(unowned_crew)
                }
            }
        })

    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get admin stats")


# ============= End Admin Panel Routes =============

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
