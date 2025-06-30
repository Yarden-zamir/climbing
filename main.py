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
        level_from_climbs = climbs // 5
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
        
        # Read current files
        albums_txt = repo.get_contents("static/albums.txt", ref="main")
        albums_json = repo.get_contents("static/albums.json", ref="main")
        
        # Update albums.txt - add to top of list
        current_albums = albums_txt.decoded_content.decode().strip()
        new_albums_txt = f"{album_url}\n{current_albums}\n" if current_albums else f"{album_url}\n"
        
        # Update albums.json
        albums_data = json.loads(albums_json.decoded_content.decode())
        albums_data[album_url] = {"crew": crew}
        new_albums_json = json.dumps(albums_data, indent=4)
        
        commit_message = f"Add new album with crew: {', '.join(crew)}"
        
        # Create/update files in the new branch
        repo.update_file(
            "static/albums.txt",
            commit_message,
            new_albums_txt,
            albums_txt.sha,
            branch=branch_name
        )
        
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
                        
                        # Convert to base64 for GitHub API
                        image_b64 = base64.b64encode(image_content).decode()
                        
                        repo.create_file(
                            f"climbers/{person_dir}/face.png",
                            f"Add profile image for {person_name}",
                            image_b64,
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
- ✅ Added album URL to `static/albums.txt`
- ✅ Added crew information to `static/albums.json`
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

@app.post("/api/albums/submit")
async def submit_album(submission: AlbumSubmission):
    """Submit a new album for review and automatic PR creation."""
    
    # Validate Google Photos URL
    if not validate_google_photos_url(submission.url):
        raise HTTPException(status_code=400, detail="Invalid Google Photos URL format")
    
    # Verify URL is accessible and get metadata
    try:
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, submission.url)
            meta_data = parse_meta_tags(response.text, submission.url)
            if not meta_data.get("title"):
                raise HTTPException(status_code=400, detail="Unable to fetch album metadata")
    except:
        raise HTTPException(status_code=400, detail="Album URL is not accessible")
    
    # Check if album already exists
    albums_path = Path("static/albums.txt")
    if albums_path.exists():
        with open(albums_path) as f:
            existing_urls = f.read().strip().split("\n")
            if submission.url in existing_urls:
                raise HTTPException(status_code=400, detail="Album already exists")
    
    # Create GitHub PR
    pr_result = create_github_pr(submission.url, submission.crew, submission.new_people)
    
    return JSONResponse({
        "success": True,
        "message": "Album submitted successfully! A pull request has been created for review.",
        "album_title": meta_data.get("title", "Unknown"),
        "pr_url": pr_result["pr_url"],
        "pr_number": pr_result["pr_number"]
    })

@app.get("/api/albums/validate-url")
async def validate_album_url(url: str = Query(...)):
    """Validate and fetch metadata for a Google Photos URL."""
    
    # Validate format
    if not validate_google_photos_url(url):
        return JSONResponse({"valid": False, "error": "Invalid Google Photos URL format"})
    
    # Try to fetch metadata
    try:
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, url)
            meta_data = parse_meta_tags(response.text, url)
            
            # Check if album already exists
            albums_path = Path("static/albums.txt")
            exists = False
            if albums_path.exists():
                with open(albums_path) as f:
                    existing_urls = f.read().strip().split("\n")
                    exists = url in existing_urls
            
            return JSONResponse({
                "valid": True,
                "exists": exists,
                "metadata": meta_data
            })
    except:
        return JSONResponse({"valid": False, "error": "Unable to access album or fetch metadata"})
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
