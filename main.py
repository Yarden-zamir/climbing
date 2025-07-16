import asyncio
import base64
import datetime
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Response, Form, File, UploadFile, Depends, Path
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from PIL.ExifTags import TAGS
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# OAuth imports
from auth import oauth_handler, get_current_user, require_auth
from config import settings

# Redis datastore import
from redis_store import RedisDataStore

# Permissions system import
from permissions import PermissionsManager, ResourceType, UserRole

# Validation utilities
from validation import (
    ValidationError, validate_name, validate_google_photos_url,
    validate_skill_list, validate_location_list, validate_achievements_list,
    validate_image_file, validate_crew_list, validate_json_input,
    validate_and_sanitize_metadata, validate_form_json_field,
    validate_required_string, validate_optional_image_upload,
    validate_user_role, validate_resource_type, validate_skill_name,
    validate_achievement_name, validate_and_raise_http_exception,
    validate_crew_form_data, validate_crew_edit_form_data
)

# Import extracted utilities
from utils.logging_setup import setup_logging
from utils.metadata_parser import inject_css_version, fetch_url, parse_meta_tags
from utils.background_tasks import perform_album_metadata_refresh, refresh_album_metadata
from utils.export_utils import export_redis_database

# Import middleware
from middleware.app_middleware import CaseInsensitiveMiddleware, NoCacheMiddleware

# Import models
from models.api_models import (
    NewPerson, AlbumSubmission, AlbumCrewEdit, AddSkillsRequest, AddAchievementsRequest
)

# Import route modules
from routes.auth import router as auth_router, api_router as auth_api_router
from routes.crew import router as crew_router
from routes.memes import router as memes_router
from routes.management import router as management_router
from routes.admin import router as admin_router
from routes.users import router as users_router
from routes.albums import router as albums_router
from routes.utilities import router as utilities_router

# Import dependencies
import dependencies

# Set up logging
logger = setup_logging()

# Initialize FastAPI app
app = FastAPI(title="Climbing App", description="A climbing album and crew management system")

logger.info("Starting Redis-based Climbing App initialization...")

# Initialize Redis datastore
try:
    redis_store = RedisDataStore(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
        ssl=settings.REDIS_SSL
    )
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

# Initialize dependencies
dependencies.initialize_dependencies(redis_store, permissions_manager, logger)

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

    # Clean up stored level values (run once after switching to dynamic calculation)
    try:
        logger.info("Running level values cleanup...")
        cleanup_result = await redis_store.cleanup_stored_level_values()
        if cleanup_result["total_fields_removed"] > 0:
            logger.info(f"✅ Level cleanup completed: {cleanup_result}")
        else:
            logger.info("✅ Level cleanup completed: No stored level values found to clean")
    except Exception as e:
        logger.error(f"❌ Level cleanup failed: {e}")


@app.on_event("startup")
async def start_background_tasks():
    """Start background tasks on startup"""
    logger.info("🚀 Starting background metadata refresh task...")
    asyncio.create_task(refresh_album_metadata(redis_store))


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


# Albums endpoints moved to routes/albums.py


@app.get("/get-image", tags=["utilities"])
async def get_image(url: str = Query(..., description="URL of the image to fetch")):
    """
    Proxy endpoint to fetch and serve images with proper caching headers.
    
    Args:
        url: Direct URL to the image
        
    Returns:
        - Image data with original content-type
        - Cache headers for 7 days
        
    Note:
        This endpoint helps avoid CORS issues and adds proper caching
    """
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        content_type = response.headers.get("content-type", "application/octet-stream")
        headers = {
            "Cache-Control": "public, max-age=604800, immutable"
        }
        return Response(content=response.content, media_type=content_type, headers=headers)

# === Redis Image Serving ===


@app.get("/redis-image/{image_type}/{identifier:path}", tags=["utilities"])
async def get_redis_image(
    image_type: str = Path(..., description="Type of image (climber, profile, meme)"),
    identifier: str = Path(..., description="Image identifier or path")
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

        # Different caching strategies based on image type
        if image_type == "climber" or image_type == "profile":
            # For profile images that can be updated, use shorter cache with validation
            headers = {
                "Cache-Control": "public, max-age=300, must-revalidate",
                "ETag": f'"{hash(image_data)}"'
            }
        else:
            # For other images (temp, memes, etc.), use longer cache
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root():
    """Serve the main crew page."""
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/albums", response_class=HTMLResponse, include_in_schema=False)
async def read_albums():
    """Serve the climbing albums page."""
    content = inject_css_version("static/albums.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/memes", response_class=HTMLResponse, include_in_schema=False)
async def read_memes():
    """Serve the memes gallery page."""
    content = inject_css_version("static/memes.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/knowledge", response_class=HTMLResponse, include_in_schema=False)
async def read_knowledge():
    """Serve the knowledge base page."""
    content = inject_css_version("static/index.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/crew", response_class=HTMLResponse, include_in_schema=False)
async def read_crew():
    """Serve the crew management page."""
    content = inject_css_version("static/crew.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def read_privacy():
    """Serve the privacy policy page."""
    content = inject_css_version("static/privacy.html")
    response = HTMLResponse(content=content, status_code=200)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
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
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# === Health Check ===


# Health endpoint moved to routes/utilities.py


# Profile picture endpoint moved to routes/utilities.py


# Upload face endpoint moved to routes/utilities.py


# Custom OpenAPI schema endpoint
from fastapi.openapi.utils import get_openapi

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
            "x-displayName": "Authentication"
        },
        {
            "name": "crew",
            "description": "Manage climbing crew members, their skills, and achievements",
            "x-displayName": "Crew Management"
        },
        {
            "name": "albums",
            "description": "Manage climbing photo albums and metadata",
            "x-displayName": "Photo Albums"
        },
        {
            "name": "memes",
            "description": "Handle climbing memes and fun content",
            "x-displayName": "Meme Gallery"
        },
        {
            "name": "admin",
            "description": "Administrative functions and system management",
            "x-displayName": "Admin Panel"
        },
        {
            "name": "utilities",
            "description": "Helper endpoints for metadata, images, and system health",
            "x-displayName": "Utilities"
        },
        {
            "name": "management",
            "description": "System configuration and feature management",
            "x-displayName": "Management"
        },
        {
            "name": "user",
            "description": "User preferences and settings",
            "x-displayName": "User Settings"
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

# Override the default openapi method
app.openapi = custom_openapi

# Mount static files and add middleware
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve favicon
@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    return FileResponse("static/favicon/favicon.ico")

# Add GZip compression middleware (add first for best performance)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(CaseInsensitiveMiddleware)
app.add_middleware(NoCacheMiddleware)
