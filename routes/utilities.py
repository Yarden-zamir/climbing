import logging
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import JSONResponse, RedirectResponse, Response

from auth import get_current_user
from dependencies import get_store, get_permissions_manager
from validation import ValidationError, validate_name, validate_image_file

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api", tags=["utilities"])


def _git_revision() -> str:
    """Commit the running code was built from; deploy checks compare it to the pushed sha.

    Reads .git metadata directly so the container needs no git binary.
    """
    if os.getenv("GIT_REVISION"):
        return os.environ["GIT_REVISION"]
    git_dir = Path(__file__).resolve().parent.parent / ".git"
    head = git_dir / "HEAD"
    if not head.is_file():
        return ""
    ref = head.read_text().strip()
    if not ref.startswith("ref: "):
        return ref
    ref_name = ref.removeprefix("ref: ")
    ref_file = git_dir / ref_name
    if ref_file.is_file():
        return ref_file.read_text().strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref_name:
                return parts[0]
    return ""


REVISION = _git_revision()


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    store = get_store()

    if not store:
        return JSONResponse(
            {"status": "unhealthy", "error": "Store not available"},
            status_code=500,
        )

    try:
        health = await store.health_check()
        health["revision"] = REVISION
        return JSONResponse(health)
    except Exception as e:
        return JSONResponse({"status": "unhealthy", "error": str(e)}, status_code=500)


@router.get("/level-calculator")
async def get_level_calculator():
    """Get level calculation information"""
    # This endpoint returns the level calculation logic for the frontend
    return JSONResponse(
        {
            "formula": {
                "skills": "skills",
                "climbs": "floor(climbs / 5)",
                "achievements": "achievements",
                "locations": "locations",
                "total": "skills_level + climbs_level + achievements_level + locations_level + 1",
            },
            "description": "Level calculation based on skills, climbs, achievements, and locations",
            "min_level": 1,
            "skill_divisor": 1,
            "climb_divisor": 5,
            "achievement_multiplier": 1,
            "location_multiplier": 1,
        }
    )


@router.get("/profile-picture/{user_id}")
async def get_profile_picture(user_id: str):
    """Serve cached profile picture with fallback to Google URL"""
    store = get_store()
    permissions_manager = get_permissions_manager()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Try to get the cached image from the store
        image_data = await store.get_image("profile", f"{user_id}/picture")

        if image_data:
            headers = {"Cache-Control": "public, max-age=604800, immutable"}
            return Response(
                content=image_data,
                media_type="image/jpeg",  # Most Google profile pics are JPEG
                headers=headers,
            )

        # If not in cache, get user info and redirect to Google URL
        if permissions_manager:
            user = await permissions_manager.get_user(user_id)
            if user and user.get("picture"):
                return RedirectResponse(url=user["picture"])

        # If all else fails, return 404
        raise HTTPException(status_code=404, detail="Profile picture not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving profile picture for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve profile picture")


@router.post("/upload-face")
async def upload_face_image(
    file: UploadFile = File(...),
    person_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Upload a temporary face image for a person."""
    store = get_store()

    # Validate user authentication
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate person name
    if not person_name or not person_name.strip():
        raise HTTPException(status_code=400, detail="Person name is required")

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        validated_name = validate_name(person_name.strip())
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload a valid image file")

    try:
        # Validate image file type and size
        image_data = await file.read()
        validate_image_file(file.content_type, len(image_data))

        # Store as temporary image (expires after 1 hour)
        temp_path = await store.store_image("temp", validated_name, image_data)

        return JSONResponse(
            {
                "success": True,
                "message": "Image uploaded successfully",
                "temp_path": temp_path,
                "person_name": validated_name,
            }
        )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error uploading face image for {validated_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")
