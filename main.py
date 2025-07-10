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
from fastapi.staticfiles import StaticFiles  # Import StaticFiles
from bs4 import BeautifulSoup
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import git
from github import Github
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys

# OAuth imports
from config import settings
from auth import oauth_handler, get_current_user, require_auth
from fastapi import Depends

# Configure logging


def setup_logging():
    """Set up comprehensive logging with both file and console handlers"""
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # File handler with rotation
    file_handler = RotatingFileHandler(
        logs_dir / "climbing_app.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)

    # Create app-specific logger
    app_logger = logging.getLogger("climbing_app")
    app_logger.setLevel(logging.DEBUG)

    return app_logger


# Set up logging
logger = setup_logging()

# Initialize FastAPI app
app = FastAPI(title="Climbing App", description="A climbing album and crew management system")

logger.info("Starting Climbing App initialization...")

# Global cache for album metadata and new climber tracking
album_metadata_cache = {}
new_climbers_cache = set()
cache_initialized = False


async def initialize_cache():
    """Initialize the cache with album metadata and calculate new climbers on startup"""
    global album_metadata_cache, new_climbers_cache, cache_initialized

    if cache_initialized:
        logger.info("Cache already initialized, skipping...")
        return

    logger.info("=== Starting cache initialization ===")

    # Load albums.json
    albums_path = Path("static/albums.json")
    if not albums_path.exists():
        logger.warning("No albums.json found, skipping cache initialization")
        cache_initialized = True
        return

    with open(albums_path) as f:
        albums_data = json.load(f)

    logger.info(f"Loaded {len(albums_data)} albums from albums.json")

    # Fetch metadata for all albums in parallel
    async with httpx.AsyncClient(timeout=30.0) as client:

        async def fetch_album_metadata(album_url: str):
            """Fetch metadata for a single album"""
            try:
                logger.debug(f"Fetching metadata for: {album_url}")
                response = await fetch_url(client, album_url)
                meta_data = parse_meta_tags(response.text, album_url)

                # Add crew info from albums.json
                if albums_data[album_url].get("crew"):
                    meta_data["crew"] = albums_data[album_url]["crew"]

                logger.info(f"✓ Cached metadata for: {meta_data.get('title', 'Unknown')}")
                return album_url, meta_data

            except Exception as e:
                logger.error(f"✗ Failed to cache metadata for {album_url}: {e}")
                return album_url, None

        # Create tasks for all albums and execute them in parallel
        logger.info(f"Creating {len(albums_data)} parallel tasks for metadata fetching...")
        tasks = [fetch_album_metadata(album_url) for album_url in albums_data.keys()]

        start_time = datetime.datetime.now()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = datetime.datetime.now()

        logger.info(f"Parallel fetch completed in {(end_time - start_time).total_seconds():.2f} seconds")

        # Process results
        successful_caches = 0
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Task failed with exception: {result}")
                continue

            if result is None:
                continue

            album_url, meta_data = result
            if meta_data:
                album_metadata_cache[album_url] = meta_data
                successful_caches += 1

        logger.info(f"Successfully cached {successful_caches}/{len(albums_data)} albums")

    # Calculate new climbers (first participation in last 14 days)
    logger.info("Calculating new climbers...")
    new_climbers_cache = calculate_new_climbers()
    logger.info(f"Found {len(new_climbers_cache)} new climbers: {list(new_climbers_cache)}")

    cache_initialized = True
    logger.info("=== Cache initialization complete! ===")


def normalize_climber_name(name):
    """Normalize climber names for consistent matching"""
    return re.sub(r'[^a-zA-Z\s]', '', name.strip().lower().replace(' ', ''))


def calculate_new_climbers():
    """Calculate which climbers are new (first participation in last 14 days)"""
    logger.debug("Starting new climbers calculation...")
    climber_first_participation = {}
    current_year = datetime.datetime.now().year

    # Create a list of albums with their dates for sorting
    albums_with_dates = []

    for album_url, metadata in album_metadata_cache.items():
        if not metadata.get("crew") or not metadata.get("date"):
            logger.debug(f"Skipping album {album_url} - missing crew or date")
            continue

            # Parse album date
        try:
            date_str = metadata["date"]
            # Handle various date formats:
            # "Jul 1 – 2 📸", "Saturday, Jun 28 📸", "Friday, Jun 27 📸", "May 15", etc.

            # Extract month and day using regex - look for month name followed by day number
            match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d+)', date_str)
            if not match:
                logger.warning(f"Could not parse date format: {date_str}")
                continue

            month_name, day = match.groups()
            month_map = {
                'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
            }

            album_date = datetime.date(current_year, month_map[month_name], int(day))

            # If the date is in the future, assume it's from last year
            if album_date > datetime.date.today():
                album_date = datetime.date(current_year - 1, month_map[month_name], int(day))

            albums_with_dates.append((album_url, metadata, album_date))
            logger.debug(f"Parsed date: {date_str} -> {album_date}")

        except Exception as e:
            logger.error(f"Failed to parse date '{date_str}' for album {album_url}: {e}")
            continue

    # Sort albums by date (oldest first)
    albums_with_dates.sort(key=lambda x: x[2])
    logger.debug(f"Sorted {len(albums_with_dates)} albums by date")

    # Track first participation for each climber (using normalized names)
    for album_url, metadata, album_date in albums_with_dates:
        for climber in metadata["crew"]:
            climber_normalized = normalize_climber_name(climber)
            if climber_normalized not in climber_first_participation:
                climber_first_participation[climber_normalized] = {
                    'date': album_date,
                    'original_name': climber.strip()
                }

    # Find climbers whose first participation was in the last 14 days
    cutoff_date = datetime.date.today() - datetime.timedelta(days=14)
    new_climbers = set()

    # Also create a mapping from directory names to check against
    climbers_dir = Path("climbers")
    directory_to_normalized = {}
    if climbers_dir.exists():
        for climber_dir in climbers_dir.iterdir():
            if climber_dir.is_dir():
                dir_name = climber_dir.name.replace("-", " ").title()
                normalized = normalize_climber_name(dir_name)
                directory_to_normalized[normalized] = dir_name

    for climber_normalized, participation_info in climber_first_participation.items():
        first_date = participation_info['date']
        if first_date >= cutoff_date:
            # Find the corresponding directory name
            if climber_normalized in directory_to_normalized:
                new_climbers.add(directory_to_normalized[climber_normalized])
            else:
                # Fallback to original name
                new_climbers.add(participation_info['original_name'])

        # Store the climber dates for later access (attach to function)
    calculate_new_climbers._climber_dates = climber_first_participation

    # Debug logging
    logger.debug("First participation dates:")
    for climber_normalized, participation_info in climber_first_participation.items():
        original_name = participation_info['original_name']
        first_date = participation_info['date']
        is_new = first_date >= cutoff_date
        logger.debug(f"  {original_name} (normalized: {climber_normalized}): {first_date} {'[NEW]' if is_new else ''}")

    return new_climbers


@app.on_event("startup")
async def startup_event():
    """Initialize cache on startup"""
    logger.info("FastAPI startup event triggered")
    await initialize_cache()

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


def get_crew_data():
    """Helper function that returns raw crew data (not JSONResponse)"""
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
        tags = details.get("tags", [])
        level_from_skills = len(skills)  # Only count skills, not tags
        level_from_climbs = climbs // 5
        total_level = 1 + level_from_skills + level_from_climbs

        # Check if climber is new (first participation in last 14 days)
        # Try multiple variations of the name to match
        name_variations = [
            name,  # Display name from directory
            climber_dir.name,  # Directory name
            climber_dir.name.replace("-", " ").title()  # Directory name formatted
        ]
        is_new = any(name_variation in new_climbers_cache for name_variation in name_variations)

        # Get first climb date for new climbers
        first_climb_date = None
        if is_new and hasattr(calculate_new_climbers, '_climber_dates'):
            # Check if we have the climber's first date stored
            for norm_name, date_info in calculate_new_climbers._climber_dates.items():
                if any(normalize_climber_name(var) == norm_name for var in name_variations):
                    first_climb_date = date_info['date'].strftime("%b %d")
                    break

        crew.append({
            "name": name,
            "face": f"/climbers/{climber_dir.name}/face.png",
            "location": details.get("Location", []),
            "skills": skills,
            "tags": tags,
            "climbs": climbs,
            "level_from_climbs": level_from_climbs,
            "level_from_skills": level_from_skills,
            "level": total_level,
            "is_new": is_new,
            "first_climb_date": first_climb_date,
        })
    return crew


@app.get("/api/crew")
def get_crew():
    crew = get_crew_data()
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


@app.get("/api/albums/enriched")
async def get_enriched_albums():
    """API endpoint that returns all albums with pre-loaded metadata from cache."""
    # Ensure cache is initialized
    if not cache_initialized:
        await initialize_cache()

    # Return the cached metadata, enriching it with new climber status
    enriched_albums = []
    for album_url, metadata in album_metadata_cache.items():
        enriched_meta = metadata.copy()
        if "crew" in enriched_meta:
            # Create a list of crew members with their 'is_new' status
            crew_with_status = []
            for climber_name in enriched_meta["crew"]:
                # Normalize both the climber's name and the names in the cache for comparison
                normalized_climber = normalize_climber_name(climber_name)

                # Check against directory names and original names in the cache
                is_new = any(
                    normalize_climber_name(cached_name) == normalized_climber
                    for cached_name in new_climbers_cache
                )

                crew_with_status.append({
                    "name": climber_name,
                    "is_new": is_new
                })
            enriched_meta["crew"] = crew_with_status

        enriched_albums.append({
            "url": album_url,
            "metadata": enriched_meta
        })

    headers = {
        "Cache-Control": "public, max-age=300, stale-while-revalidate=86400"
    }
    return Response(content=json.dumps(enriched_albums), media_type="application/json", headers=headers)


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

# Add knowledge page route
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


@app.get("/climbers/{climber_name}/{file_path:path}")
async def get_climber_file(climber_name: str, file_path: str):
    """Case-insensitive climber file access"""
    from urllib.parse import unquote

    # Decode URL-encoded climber name
    climber_name = unquote(climber_name)

    # Find the correct case directory
    climbers_dir = Path("climbers")
    correct_dir = None

    for existing_dir in climbers_dir.iterdir():
        if existing_dir.is_dir() and existing_dir.name.lower() == climber_name.lower():
            correct_dir = existing_dir
            break

    if not correct_dir:
        raise HTTPException(status_code=404, detail="Climber not found")

    # Construct the file path
    file_full_path = correct_dir / file_path

    if not file_full_path.exists() or not file_full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_full_path)
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

@app.get("/api/skills")
def get_skills():
    """Get all unique skills from existing crew members."""
    climbers_dir = Path("climbers")
    all_skills = set()
    
    for climber_dir in climbers_dir.iterdir():
        if not climber_dir.is_dir():
            continue
        details_path = climber_dir / "details.json"
        if not details_path.exists():
            continue
            
        with open(details_path) as f:
            details = json.load(f)
            skills = details.get("skills", [])
            all_skills.update(skills)
    
    return JSONResponse(sorted(list(all_skills)))

@app.post("/api/upload-face")
async def upload_face(file: UploadFile = File(...), person_name: str = Form(...)):
    """Upload a face image for a new person (temporary storage)."""
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    # Create temp directory if it doesn't exist
    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    
    # Save with person name
    safe_name = person_name.lower().replace(" ", "-")
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'png'
    temp_path = temp_dir / f"{safe_name}.{file_extension}"
    
    # Save the uploaded file
    with open(temp_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    return JSONResponse({
        "success": True,
        "temp_path": str(temp_path),
        "person_name": person_name
    })

# Pydantic models for album submission
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

def validate_google_photos_url(url: str) -> bool:
    """Validate that the URL is a Google Photos album link."""
    return bool(re.match(r"https://photos\.app\.goo\.gl/[a-zA-Z0-9]+", url))

def create_github_pr(album_url: str, crew: List[str], new_people: List[NewPerson] = None):
    """Create a GitHub branch and pull request for the new album."""
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise HTTPException(status_code=500, detail="GitHub token not configured")
    
    repo_url = os.getenv("GITHUB_REPO_URL", "https://github.com/yarden-zamir/climbing.git")
    repo_name = repo_url.split("/")[-2:] 
    repo_name = f"{repo_name[0]}/{repo_name[1].replace('.git', '')}"
    
    try:
        # Initialize GitHub client
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        
        # Create a unique branch name
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"add-album-{timestamp}"
        
        # Get the latest commit SHA from main
        main_branch = repo.get_branch("main")
        
        # Create new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)
        
        # Read current albums.json
        albums_json = repo.get_contents("static/albums.json", ref="main")
        
        # Update albums.json - add new album
        albums_data = json.loads(albums_json.decoded_content.decode())
        albums_data[album_url] = {"crew": crew}
        new_albums_json = json.dumps(albums_data, indent=4)
        
        commit_message = f"Add new album with crew: {', '.join(crew)}"
        
        # Update albums.json in the new branch
        repo.update_file(
            "static/albums.json", 
            commit_message,
            new_albums_json,
            albums_json.sha,
            branch=branch_name
        )
        
        # Handle new people if any
        if new_people:
            for person in new_people:
                person_name = person.name
                person_dir = person_name.lower().replace(" ", "-")
                person_skills = person.skills or []
                person_location = person.location or []
                temp_image_path = person.temp_image_path
                
                # Create climber directory and files
                details_content = json.dumps({
                    "Location": person_location,
                    "skills": person_skills
                }, indent=4)
                
                # Create details.json
                repo.create_file(
                    f"climbers/{person_dir}/details.json",
                    f"Add new climber: {person_name}",
                    details_content,
                    branch=branch_name
                )
                
                # Handle face image if provided
                if temp_image_path and Path(temp_image_path).exists():
                    try:
                        with open(temp_image_path, "rb") as img_file:
                            image_content = img_file.read()
                        
                                                    # For binary content, pass the raw bytes directly instead of base64 string
                        repo.create_file(
                            f"climbers/{person_dir}/face.png",
                            f"Add profile image for {person_name}",
                            image_content,  # Use raw bytes instead of base64 string
                            branch=branch_name
                        )

                        # Clean up temp file
                        Path(temp_image_path).unlink()
                        
                    except Exception as e:
                        print(f"Failed to upload image for {person_name}: {e}")
                        # Continue without the image
        
        # Create pull request
        pr_title = f"Add new climbing album"
        pr_body = f"""
## New Album Added

**Album URL:** {album_url}
**Crew:** {', '.join(crew)}

This pull request automatically adds a new climbing album to the collection.

{'**New People Added:** ' + ', '.join([p.name for p in new_people]) if new_people else ''}

### Changes Made:
- ✅ Added album URL and crew information to `static/albums.json`
{'- ✅ Created new climber profiles' if new_people else ''}

Please review and merge when ready!
        """
        
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base="main"
        )
        
        return {
            "success": True,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "branch_name": branch_name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create PR: {str(e)}")

def create_crew_github_pr(crew_member: CrewSubmission):
    """Create a GitHub branch and pull request for a new crew member."""
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise HTTPException(status_code=500, detail="GitHub token not configured")
    
    repo_url = os.getenv("GITHUB_REPO_URL", "https://github.com/yarden-zamir/climbing.git")
    repo_name = repo_url.split("/")[-2:] 
    repo_name = f"{repo_name[0]}/{repo_name[1].replace('.git', '')}"
    
    try:
        # Initialize GitHub client
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        
        # Create a unique branch name
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        crew_slug = crew_member.name.lower().replace(" ", "-").replace(".", "")
        branch_name = f"add-crew-{crew_slug}-{timestamp}"
        
        # Get the latest commit SHA from main
        main_branch = repo.get_branch("main")
        
        # Create new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)
        
        # Create climber directory name (keeping spaces to match existing pattern)
        person_dir = crew_member.name
        
        # Create details.json content
        details_content = json.dumps({
            "Location": crew_member.location,
            "skills": crew_member.skills
        }, indent=4)
        
        commit_message = f"Add new crew member: {crew_member.name}"
        
        # Create details.json
        repo.create_file(
            f"climbers/{person_dir}/details.json",
            commit_message,
            details_content,
            branch=branch_name
        )
        
        # Handle face image if provided
        if crew_member.temp_image_path and Path(crew_member.temp_image_path).exists():
            try:
                with open(crew_member.temp_image_path, "rb") as img_file:
                    image_content = img_file.read()
                
                                # For binary content, pass raw bytes directly
                repo.create_file(
                    f"climbers/{person_dir}/face.png",
                    f"Add profile image for {crew_member.name}",
                    image_content,  # Use raw bytes instead of base64 string
                    branch=branch_name
                )

                # Clean up temp file
                Path(crew_member.temp_image_path).unlink()
                
            except Exception as e:
                print(f"Failed to upload image for {crew_member.name}: {e}")
                # Continue without the image
        
        # Create pull request
        pr_title = f"Add new crew member: {crew_member.name}"
        pr_body = f"""
## New Crew Member Added

**Name:** {crew_member.name}
**Location:** {', '.join(crew_member.location) if crew_member.location else 'Not specified'}
**Skills:** {', '.join(crew_member.skills) if crew_member.skills else 'None specified'}

This pull request automatically adds a new crew member to the climbing team.

### Changes Made:
- ✅ Created crew member profile at `climbers/{person_dir}/details.json`
{'- ✅ Added profile image' if crew_member.temp_image_path else ''}

Please review and merge when ready!
        """
        
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base="main"
        )
        
        return {
            "success": True,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "branch_name": branch_name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create crew PR: {str(e)}")


def create_crew_edit_pr(crew_edit: CrewEdit):
    """Create a GitHub branch and pull request for editing an existing crew member."""
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise HTTPException(status_code=500, detail="GitHub token not configured")

    repo_url = os.getenv("GITHUB_REPO_URL", "https://github.com/yarden-zamir/climbing.git")
    repo_name = repo_url.split("/")[-2:]
    repo_name = f"{repo_name[0]}/{repo_name[1].replace('.git', '')}"

    try:
        # Initialize GitHub client
        g = Github(github_token)
        repo = g.get_repo(repo_name)

        # Create a unique branch name
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        crew_slug = crew_edit.name.lower().replace(" ", "-").replace(".", "")
        branch_name = f"edit-crew-{crew_slug}-{timestamp}"

        # Get the latest commit SHA from main
        main_branch = repo.get_branch("main")

        # Create new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)

        original_dir = crew_edit.original_name
        new_dir = crew_edit.name
        name_changed = original_dir != new_dir

        # Get existing files
        try:
            original_details = repo.get_contents(f"climbers/{original_dir}/details.json", ref="main")
            original_face = None
            try:
                original_face = repo.get_contents(f"climbers/{original_dir}/face.png", ref="main")
            except:
                pass  # Face image might not exist
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Crew member '{crew_edit.original_name}' not found")

        # Create new details.json content
        new_details_content = json.dumps({
            "Location": crew_edit.location,
            "skills": crew_edit.skills
        }, indent=4)

        commit_message = f"Edit crew member: {crew_edit.original_name}"
        if name_changed:
            commit_message = f"Edit and rename crew member: {crew_edit.original_name} → {crew_edit.name}"

        if name_changed:
            # Create new directory with updated details
            repo.create_file(
                f"climbers/{new_dir}/details.json",
                commit_message,
                new_details_content,
                branch=branch_name
            )

            # Copy/update face image
            if crew_edit.temp_image_path and Path(crew_edit.temp_image_path).exists():
                # Use new image
                try:
                    with open(crew_edit.temp_image_path, "rb") as img_file:
                        image_content = img_file.read()
                                        # For binary content, pass raw bytes directly
                    repo.create_file(
                        f"climbers/{new_dir}/face.png",
                        commit_message,
                        image_content,  # Use raw bytes instead of base64 string
                        branch=branch_name
                    )

                    # Clean up temp file
                    Path(crew_edit.temp_image_path).unlink()
                except Exception as e:
                    print(f"Failed to upload new image: {e}")
            elif original_face:
                # Copy existing image to new location
                repo.create_file(
                    f"climbers/{new_dir}/face.png",
                    commit_message,
                    original_face.content,
                    branch=branch_name
                )

            # Delete old directory files
            repo.delete_file(
                f"climbers/{original_dir}/details.json",
                commit_message,
                original_details.sha,
                branch=branch_name
            )

            if original_face:
                repo.delete_file(
                    f"climbers/{original_dir}/face.png",
                    commit_message,
                    original_face.sha,
                    branch=branch_name
                )
        else:
            # Just update existing files
            repo.update_file(
                f"climbers/{original_dir}/details.json",
                commit_message,
                new_details_content,
                original_details.sha,
                branch=branch_name
            )

            # Update face image if new one provided
            if crew_edit.temp_image_path and Path(crew_edit.temp_image_path).exists():
                try:
                    with open(crew_edit.temp_image_path, "rb") as img_file:
                        image_content = img_file.read()
                    
                    if original_face:
                        # Update existing image
                        repo.update_file(
                            f"climbers/{original_dir}/face.png",
                            commit_message,
                            image_content,  # Use raw bytes instead of base64 string
                            original_face.sha,
                            branch=branch_name
                        )
                    else:
                        # Create new image
                        repo.create_file(
                            f"climbers/{original_dir}/face.png",
                            commit_message,
                            image_content,  # Use raw bytes instead of base64 string
                            branch=branch_name
                        )

                    # Clean up temp file
                    Path(crew_edit.temp_image_path).unlink()
                except Exception as e:
                    print(f"Failed to upload image: {e}")

        # Update albums.json if name changed
        if name_changed:
            try:
                albums_json = repo.get_contents("static/albums.json", ref="main")
                albums_data = json.loads(albums_json.decoded_content.decode())

                # Update crew member name in all albums
                for album_url, album_data in albums_data.items():
                    if "crew" in album_data and crew_edit.original_name in album_data["crew"]:
                        crew_list = album_data["crew"]
                        crew_list = [crew_edit.name if member ==
                                     crew_edit.original_name else member for member in crew_list]
                        albums_data[album_url]["crew"] = crew_list

                new_albums_json = json.dumps(albums_data, indent=4)
                repo.update_file(
                    "static/albums.json",
                    commit_message,
                    new_albums_json,
                    albums_json.sha,
                    branch=branch_name
                )
            except Exception as e:
                print(f"Failed to update albums.json: {e}")
                # Continue without updating albums.json

        # Create pull request
        pr_title = f"Edit crew member: {crew_edit.name}"
        if name_changed:
            pr_title = f"Edit and rename crew member: {crew_edit.original_name} → {crew_edit.name}"

        changes_list = []
        if name_changed:
            changes_list.append(f"- ✅ Renamed from '{crew_edit.original_name}' to '{crew_edit.name}'")
            changes_list.append("- ✅ Updated crew member references in albums")
        changes_list.append("- ✅ Updated location and skills")
        if crew_edit.temp_image_path:
            changes_list.append("- ✅ Updated profile image")

        pr_body = f"""
## Crew Member Updated

**Original Name:** {crew_edit.original_name}
**New Name:** {crew_edit.name}
**Location:** {', '.join(crew_edit.location) if crew_edit.location else 'Not specified'}
**Skills:** {', '.join(crew_edit.skills) if crew_edit.skills else 'None'}

This pull request updates the details for an existing crew member.

### Changes Made:
{chr(10).join(changes_list)}

Please review and merge when ready!
        """

        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base="main"
        )

        return {
            "success": True,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "branch_name": branch_name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create crew edit PR: {str(e)}")


def create_album_crew_edit_pr(album_url: str, new_crew: List[str], new_people: List[NewPerson] = None):
    """Create a GitHub branch and pull request for editing album crew, and add new climbers if provided."""
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise HTTPException(status_code=500, detail="GitHub token not configured")

    repo_url = os.getenv("GITHUB_REPO_URL", "https://github.com/yarden-zamir/climbing.git")
    repo_name = repo_url.split("/")[-2:]
    repo_name = f"{repo_name[0]}/{repo_name[1].replace('.git', '')}"

    try:
        # Initialize GitHub client
        g = Github(github_token)
        repo = g.get_repo(repo_name)

        # Create a unique branch name
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"edit-album-crew-{timestamp}"

        # Get the latest commit SHA from main
        main_branch = repo.get_branch("main")

        # Create new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)

        # Read current albums.json
        albums_json = repo.get_contents("static/albums.json", ref="main")
        albums_data = json.loads(albums_json.decoded_content.decode())

        # Get original crew for comparison
        original_crew = albums_data.get(album_url, {}).get("crew", [])

        # Update the crew for this album
        if album_url not in albums_data:
            albums_data[album_url] = {}
        albums_data[album_url]["crew"] = new_crew

        # Create updated JSON content
        new_albums_json = json.dumps(albums_data, indent=4)

        commit_message = f"Update crew for album: {', '.join(new_crew)}"

        # Update albums.json in the new branch
        repo.update_file(
            "static/albums.json",
            commit_message,
            new_albums_json,
            albums_json.sha,
            branch=branch_name
        )

        # Handle new people if any
        if new_people:
            for person in new_people:
                person_name = person.name
                person_dir = person_name.lower().replace(" ", "-")
                person_skills = person.skills or []
                person_location = person.location or []
                temp_image_path = person.temp_image_path

                # Create climber directory and files
                details_content = json.dumps({
                    "Location": person_location,
                    "skills": person_skills
                }, indent=4)

                # Create details.json
                repo.create_file(
                    f"climbers/{person_dir}/details.json",
                    f"Add new climber: {person_name}",
                    details_content,
                    branch=branch_name
                )

                # Handle face image if provided
                if temp_image_path and Path(temp_image_path).exists():
                    try:
                        with open(temp_image_path, "rb") as img_file:
                            image_content = img_file.read()
                                                # For binary content, pass raw bytes directly
                        repo.create_file(
                            f"climbers/{person_dir}/face.png",
                            f"Add profile image for {person_name}",
                            image_content,  # Use raw bytes instead of base64 string
                            branch=branch_name
                        )
                        # Clean up temp file
                        Path(temp_image_path).unlink()
                    except Exception as e:
                        print(f"Failed to upload image for {person_name}: {e}")
                        # Continue without the image

        # Create pull request
        pr_title = f"Update album crew members"
        pr_body = f"""
## Album Crew Updated

**Album URL:** {album_url}
**Original Crew:** {', '.join(original_crew) if original_crew else 'None'}
**New Crew:** {', '.join(new_crew) if new_crew else 'None'}

This pull request updates the crew members for an existing climbing album.

{'**New People Added:** ' + ', '.join([p.name for p in new_people]) if new_people else ''}

### Changes Made:
- ✅ Updated crew information in `static/albums.json`
{'- ✅ Created new climber profiles' if new_people else ''}

Please review and merge when ready!
        """

        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base="main"
        )

        return {
            "success": True,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "branch_name": branch_name
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create album crew edit PR: {str(e)}")


@app.post("/api/albums/edit-crew")
async def edit_album_crew(edit_data: AlbumCrewEdit, user: dict = Depends(get_current_user)):
    """Edit crew members for an existing album and create a PR."""

    # Validate album URL format
    if not validate_google_photos_url(edit_data.album_url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    # Check if album exists in albums.json
    albums_path = Path("static/albums.json")
    if albums_path.exists():
        with open(albums_path) as f:
            albums_data = json.load(f)
            if edit_data.album_url not in albums_data:
                raise HTTPException(status_code=404, detail="Album not found")
    else:
        raise HTTPException(status_code=404, detail="Albums file not found")

    # Get album metadata for title
    try:
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, edit_data.album_url)
            meta_data = parse_meta_tags(response.text, edit_data.album_url)
            album_title = meta_data.get("title", "Unknown Album")
    except:
        album_title = "Unknown Album"

    # Create GitHub PR
    pr_result = create_album_crew_edit_pr(edit_data.album_url, edit_data.crew, getattr(edit_data, 'new_people', []))

    return JSONResponse({
        "success": True,
        "message": "Album crew updated successfully! A pull request has been created for review.",
        "album_title": album_title,
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"]
    })

@app.post("/api/crew/submit")
async def submit_crew_member(submission: CrewSubmission, user: dict = Depends(get_current_user)):
    """Submit a new crew member for review and automatic PR creation."""
    
    # Validate name is provided
    if not submission.name or not submission.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    
    # Check if crew member already exists
    try:
        crew_data = get_crew()
        existing_names = [member.get("name", "").lower() for member in crew_data]
        if submission.name.lower() in existing_names:
            raise HTTPException(status_code=400, detail="Crew member already exists")
    except:
        # If we can't load crew data, continue anyway
        pass
    
    # Create GitHub PR
    pr_result = create_crew_github_pr(submission)
    
    return JSONResponse({
        "success": True,
        "message": "Crew member submitted successfully! A pull request has been created for review.",
        "crew_name": submission.name,
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"]
    })


@app.post("/api/crew/edit")
async def edit_crew_member(edit_data: CrewEdit, user: dict = Depends(get_current_user)):
    """Edit an existing crew member and create a PR for the changes."""

    # Validate names are provided
    if not edit_data.original_name or not edit_data.original_name.strip():
        raise HTTPException(status_code=400, detail="Original name is required")
    if not edit_data.name or not edit_data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    # Check if original crew member exists
    try:
        crew_data = get_crew()
        existing_names = [member.get("name", "") for member in crew_data]
        if edit_data.original_name not in existing_names:
            raise HTTPException(status_code=404, detail="Original crew member not found")

        # If name is changing, check if new name already exists
        if edit_data.original_name != edit_data.name:
            existing_names_lower = [name.lower() for name in existing_names]
            if edit_data.name.lower() in existing_names_lower:
                raise HTTPException(status_code=400, detail="A crew member with that name already exists")
    except HTTPException:
        raise
    except:
        # If we can't load crew data, continue anyway
        pass

    # Create GitHub PR
    pr_result = create_crew_edit_pr(edit_data)

    return JSONResponse({
        "success": True,
        "message": "Crew member updated successfully! A pull request has been created for review.",
        "crew_name": edit_data.name,
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"]
    })


class AddSkillsRequest(BaseModel):
    crew_name: str
    skills: List[str]


@app.post("/api/crew/add-skills")
async def add_skills_to_crew_member(request: AddSkillsRequest):
    """Add skills to an existing crew member and create a PR for the changes."""

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.skills:
        raise HTTPException(status_code=400, detail="At least one skill is required")

    # Check if crew member exists and get their current data
    try:
        crew_data = get_crew_data()
        existing_member = None
        for member in crew_data:
            if member.get("name", "") == request.crew_name:
                existing_member = member
                break

        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Get current skills and add new ones
        current_skills = existing_member.get("skills", [])
        updated_skills = current_skills + [skill for skill in request.skills if skill not in current_skills]

        # Create edit data with updated skills
        edit_data = CrewEdit(
            original_name=request.crew_name,
            name=request.crew_name,
            skills=updated_skills,
            location=existing_member.get("location", []),
            temp_image_path=None
        )

        # Create GitHub PR
        pr_result = create_crew_edit_pr(edit_data)

        return JSONResponse({
            "success": True,
            "message": f"Skills added to {request.crew_name} successfully! A pull request has been created for review.",
            "crew_name": request.crew_name,
            "added_skills": [skill for skill in request.skills if skill not in current_skills],
            "pr_url": pr_result["pr_url"],
            "pr_number": pr_result["pr_number"]
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding skills to crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/albums/submit")
async def submit_album(submission: AlbumSubmission, user: dict = Depends(get_current_user)):
    """Submit a new album for review and automatic PR creation."""
    
    # Validate album URL format
    if not validate_google_photos_url(submission.url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")

    # Check if album already exists
    albums_path = Path("static/albums.json")
    if albums_path.exists():
        with open(albums_path) as f:
            albums_data = json.load(f)
            if submission.url in albums_data:
                raise HTTPException(status_code=400, detail="Album already exists")
    
    # Validate crew members exist (if not creating new people)
    existing_crew = []
    for crew_name in submission.crew:
        # Check if this person is in new_people
        if not any(p.name == crew_name for p in submission.new_people):
            existing_crew.append(crew_name)

    if existing_crew:
        try:
            crew_data = get_crew_data()
            existing_names = [member.get("name", "") for member in crew_data]
            for crew_name in existing_crew:
                if crew_name not in existing_names:
                    raise HTTPException(status_code=400, detail=f"Crew member '{crew_name}' does not exist")
        except:
            # If we can't load crew data, continue anyway
            pass

    # Create GitHub PR
    pr_result = create_github_pr(submission.url, submission.crew, submission.new_people)
    
    return JSONResponse({
        "success": True,
        "message": "Album submitted successfully! A pull request has been created for review.",
        "album_url": submission.url,
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"]
    })

@app.get("/api/albums/validate-url")
async def validate_album_url(url: str = Query(...)):
    """Validate if an album URL is valid and doesn't already exist."""
    
    # Validate URL format
    if not validate_google_photos_url(url):
        return JSONResponse({
            "valid": False,
            "error": "Invalid Google Photos URL format"
        })

    # Check if album already exists
    albums_path = Path("static/albums.json")
    if albums_path.exists():
        with open(albums_path) as f:
            albums_data = json.load(f)
            if url in albums_data:
                return JSONResponse({
                    "valid": False,
                    "error": "Album already exists"
                })
    async with httpx.AsyncClient() as client:
        response = await fetch_url(client, url)
        meta_data = parse_meta_tags(response.text, url)
        headers = {
            "Cache-Control": "public, max-age=5,stale-while-revalidate=86400, immutable"
        } 
        meta_data["valid"] = True
        return JSONResponse(meta_data, headers=headers)


    return JSONResponse({"valid": True})


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

# app.mount("/", StaticFiles(directory="static", html=True), name="static")
app.mount("/static", StaticFiles(directory="static"), name="static")
# Climbers directory is handled by custom route for case-insensitive access


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


app.add_middleware(CaseInsensitiveMiddleware)
app.add_middleware(NoCacheMiddleware)
