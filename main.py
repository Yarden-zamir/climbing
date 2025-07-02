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
        tags = details.get("tags", [])
        level_from_skills = len(skills)  # Only count skills, not tags
        level_from_climbs = climbs // 5
        total_level = 1 + level_from_skills + level_from_climbs
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
    content = inject_css_version("static/index.html")
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

@app.get("/crew", response_class=HTMLResponse)
async def read_crew():
    content = inject_css_version("static/crew.html")
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
                
                # Convert to base64 for GitHub API
                image_b64 = base64.b64encode(image_content).decode()
                
                repo.create_file(
                    f"climbers/{person_dir}/face.png",
                    f"Add profile image for {crew_member.name}",
                    image_b64,
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
                    image_b64 = base64.b64encode(image_content).decode()

                    repo.create_file(
                        f"climbers/{new_dir}/face.png",
                        commit_message,
                        image_b64,
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
                    image_b64 = base64.b64encode(image_content).decode()

                    if original_face:
                        # Update existing image
                        repo.update_file(
                            f"climbers/{original_dir}/face.png",
                            commit_message,
                            image_b64,
                            original_face.sha,
                            branch=branch_name
                        )
                    else:
                        # Create new image
                        repo.create_file(
                            f"climbers/{original_dir}/face.png",
                            commit_message,
                            image_b64,
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
async def edit_album_crew(edit_data: AlbumCrewEdit):
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
async def submit_crew_member(submission: CrewSubmission):
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
async def edit_crew_member(edit_data: CrewEdit):
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

@app.post("/api/albums/submit")
async def submit_album(submission: AlbumSubmission):
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
            crew_data = get_crew()
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

    return JSONResponse({"valid": True})
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
