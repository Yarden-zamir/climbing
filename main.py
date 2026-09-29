import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Path as PathParam
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, FileResponse

from auth import SessionRefreshMiddleware, initialize_jwt_manager
from config import settings
from store import Store
from permissions import PermissionsManager
from utils.logging_setup import setup_logging
from utils.metadata_parser import inject_css_version, fetch_url, parse_meta_tags
from utils.background_tasks import backup_database, refresh_album_metadata
from middleware.app_middleware import CaseInsensitiveMiddleware, NoCacheMiddleware
from middleware.pretty_json_middleware import PrettyJSONMiddleware
from routes.auth import router as auth_router, api_router as auth_api_router
from routes.crew import router as crew_router
from routes.memes import router as memes_router
from routes.management import router as management_router
from routes.admin import router as admin_router
from routes.users import router as users_router
from routes.albums import router as albums_router
from routes.utilities import router as utilities_router
from routes.notifications import router as notifications_router
from scripts.migrate_redis_to_duckdb import migrate_if_empty
import dependencies

# Set up logging
logger = setup_logging()

logger.info("Starting Climbing App...")

store = Store(settings.DB_PATH)
logger.info(f"✅ Store opened: {settings.DB_PATH}")

initialize_jwt_manager(store)
permissions_manager = PermissionsManager(store)

from auth import jwt_manager  # noqa: E402  (set by initialize_jwt_manager)

dependencies.initialize_dependencies(store, permissions_manager, logger, jwt_manager)


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrated = migrate_if_empty(store)
    if migrated:
        logger.info(f"✅ Legacy Redis data imported: {migrated}")
    await asyncio.to_thread(store.shrink_stored_faces)
    logger.info(f"✅ Store healthy: {await store.health_check()}")
    tasks = [
        asyncio.create_task(refresh_album_metadata(store)),
        asyncio.create_task(backup_database(store, settings.BACKUP_DIR)),
    ]
    yield
    for task in tasks:
        task.cancel()
    store.close()


app = FastAPI(
    title="Climbing App",
    description="A climbing album and crew management system",
    lifespan=lifespan,
)

# Register route modules
app.include_router(auth_router)
app.include_router(auth_api_router)
app.include_router(crew_router)
app.include_router(memes_router)
app.include_router(management_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(albums_router)
app.include_router(utilities_router)
app.include_router(notifications_router)


# === API Routes ===


@app.get("/get-meta", tags=["utilities"])
async def get_meta(url: str = Query(..., description="URL to fetch metadata from")):
    """
    Fetch and parse metadata from a URL with Redis caching.

    Args:
        url: The URL to fetch metadata from (e.g., Google Photos album URL)

    Returns:
        JSON object containing:
        - title: Album title
        - description: Album description
        - images: List of image URLs
        - timestamp: When the metadata was last fetched

    Cache:
        - Results are cached for 5 minutes
        - Stale-while-revalidate for up to 24 hours
    """
    # Check cache first
    cached_meta = store.get_cached_metadata(url)
    if cached_meta:
        logger.info(f"Returning cached metadata for: {url}")
        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        }
        return Response(
            content=json.dumps(cached_meta),
            media_type="application/json",
            headers=headers,
        )

    # Fetch new metadata
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        meta_data = parse_meta_tags(response.text, url)

        # Cache for 5 minutes
        store.cache_album_metadata(url, meta_data, ttl=300)

        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        }
        return Response(
            content=json.dumps(meta_data),
            media_type="application/json",
            headers=headers,
        )


# Albums endpoints moved to routes/albums.py


PROXY_IMAGE_TTL = 7 * 24 * 3600


def sized_google_image_url(url: str, size: int) -> str:
    """Google renders the size itself from the `=s<px>` suffix; strip any existing size first."""
    if "googleusercontent.com" not in url:
        return url
    return f"{url.split('=')[0]}=s{size}-rw"  # -rw: WebP when the browser accepts it


@app.get("/get-image", tags=["utilities"])
async def get_image(
    url: str = Query(..., description="Google Photos image URL"),
    w: int = Query(800, ge=64, le=2048, description="Longest side in pixels"),
):
    """Serve a Google Photos image at the requested size, cached in the store for a week.

    A card never downloads the multi-megabyte original again.
    """
    sized_url = sized_google_image_url(url, w)
    cache_key = hashlib.md5(sized_url.encode()).hexdigest()
    headers = {"Cache-Control": "public, max-age=604800, immutable"}

    cached = await store.get_image_with_type("proxy", cache_key)
    if cached:
        return Response(content=cached[0], media_type=cached[1] or "image/jpeg", headers=headers)

    async with httpx.AsyncClient(timeout=20) as client:
        response = await fetch_url(client, sized_url)
    content_type = response.headers.get("content-type", "application/octet-stream")
    if content_type.startswith("image/"):
        await store.store_image("proxy", cache_key, response.content, ttl_seconds=PROXY_IMAGE_TTL, content_type=content_type)
    return Response(content=response.content, media_type=content_type, headers=headers)


# === Redis Image Serving ===


@app.get("/redis-image/{image_type}/{identifier:path}", tags=["utilities"])
async def get_redis_image(
    image_type: str = PathParam(..., description="Type of image (climber, profile, meme)"),
    identifier: str = PathParam(..., description="Image identifier or path"),
):
    """
    Serve images stored in Redis with proper caching and content types.

    Args:
        image_type: Category of image (climber, profile, meme)
        identifier: Unique identifier or path for the image

    Returns:
        - Image data with correct content-type
        - Appropriate cache headers based on image type:
            * Profile images: 5 minutes with validation
            * Other images: 7 days, immutable

    Raises:
        404: Image not found
        500: Server error while serving image
    """
    try:
        found = await store.get_image_with_type(image_type, identifier)
        if not found:
            raise HTTPException(status_code=404, detail="Image not found")
        image_data, stored_type = found

        content_type = stored_type or "image/png"
        if not stored_type and identifier.lower().endswith((".jpg", ".jpeg")):
            content_type = "image/jpeg"
        elif not stored_type and identifier.lower().endswith(".gif"):
            content_type = "image/gif"
        elif not stored_type and identifier.lower().endswith(".webp"):
            content_type = "image/webp"

        # Different caching strategies based on image type
        if image_type == "climber" or image_type == "profile":
            # For profile images that can be updated, use shorter cache with validation
            headers = {
                "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
                "ETag": f'"{hashlib.md5(image_data).hexdigest()}"',
            }
        else:
            # For other images (temp, memes, etc.), use longer cache
            headers = {"Cache-Control": "public, max-age=604800, immutable"}

        return Response(content=image_data, media_type=content_type, headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving Redis image {image_type}/{identifier}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve image")


# === HTML Pages ===


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root():
    """Serve the main crew page."""
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/albums", response_class=HTMLResponse, include_in_schema=False)
async def read_albums():
    """Serve the climbing albums page."""
    content = inject_css_version("static/albums.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/memes", response_class=HTMLResponse, include_in_schema=False)
async def read_memes():
    """Serve the memes gallery page."""
    content = inject_css_version("static/memes.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/locations", response_class=HTMLResponse, include_in_schema=False)
async def read_locations():
    """Serve the locations page."""
    content = inject_css_version("static/locations.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/knowledge", response_class=HTMLResponse, include_in_schema=False)
async def read_knowledge():
    """Serve the knowledge base page."""
    content = inject_css_version("static/index.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/crew", response_class=HTMLResponse, include_in_schema=False)
async def read_crew():
    """Serve the crew management page."""
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def read_privacy():
    """Serve the privacy policy page."""
    content = inject_css_version("static/privacy.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def read_admin():
    """
    Serve the admin panel page.

    This page provides administrative functions like:
    - User management
    - Permission control
    - System statistics
    - Database operations
    """
    content = inject_css_version("static/admin.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# === Health Check ===


# Health endpoint moved to routes/utilities.py


# Profile picture endpoint moved to routes/utilities.py


# Upload face endpoint moved to routes/utilities.py


# Custom OpenAPI schema endpoint
from fastapi.openapi.utils import get_openapi  # noqa: E402


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Climbing App API",
        version="1.0.0",
        summary="API for managing climbing crew, albums, and memes",
        description="""
        The Climbing App API provides endpoints for managing:
        * 🧗‍♂️ Crew members and their profiles
        * 📸 Climbing albums and photos
        * 😄 Memes and fun content
        * 🔐 Authentication and permissions
        
        For more information, check out our [documentation](/docs).
        """,
        routes=app.routes,
    )

    # Add custom tags metadata with consistent naming and ordering
    openapi_schema["tags"] = [
        {
            "name": "authentication",
            "description": "User authentication and session management",
            "x-displayName": "Authentication",
        },
        {
            "name": "crew",
            "description": "Manage climbing crew members, their skills, and achievements",
            "x-displayName": "Crew Management",
        },
        {
            "name": "albums",
            "description": "Manage climbing photo albums and metadata",
            "x-displayName": "Photo Albums",
        },
        {
            "name": "memes",
            "description": "Handle climbing memes and fun content",
            "x-displayName": "Meme Gallery",
        },
        {
            "name": "admin",
            "description": "Administrative functions and system management",
            "x-displayName": "Admin Panel",
        },
        {
            "name": "utilities",
            "description": "Helper endpoints for metadata, images, and system health",
            "x-displayName": "Utilities",
        },
        {
            "name": "management",
            "description": "System configuration and feature management",
            "x-displayName": "Management",
        },
        {
            "name": "user",
            "description": "User preferences and settings",
            "x-displayName": "User Settings",
        },
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Override the default openapi method
app.openapi = custom_openapi

# Mount static files and add middleware
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/static", StaticFiles(directory="static"), name="static")


# Serve favicon
@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    return FileResponse("static/favicon/favicon.ico")


# Serve service worker from root


@app.get("/sw.js")
async def service_worker():
    """Serve service worker from root with proper headers"""
    response = FileResponse("sw.js", media_type="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/static/manifest.json")
async def manifest():
    """Serve manifest with no-cache headers to ensure theme color updates"""
    response = FileResponse("static/manifest.json", media_type="application/json")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.add_middleware(PrettyJSONMiddleware, api_prefix="/api")
app.add_middleware(CaseInsensitiveMiddleware)
app.add_middleware(NoCacheMiddleware)
app.add_middleware(SessionRefreshMiddleware)
# GZip is registered last so it runs outermost and compresses after PrettyJSON has rewritten the body
app.add_middleware(GZipMiddleware, minimum_size=500)
