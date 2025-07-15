import logging
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import JSONResponse, RedirectResponse, Response, FileResponse

from auth import get_current_user
from dependencies import get_redis_store, get_permissions_manager
from validation import ValidationError, validate_name, validate_image_file

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api", tags=["utilities"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    redis_store = get_redis_store()
    
    if not redis_store:
        return JSONResponse({
            "status": "unhealthy",
            "error": "Redis store not available"
        }, status_code=500)
    
    try:
        health = await redis_store.health_check()
        return JSONResponse(health)
    except Exception as e:
        return JSONResponse({
            "status": "unhealthy",
            "error": str(e)
        }, status_code=500)


@router.get("/level-calculator")
async def get_level_calculator():
    """Get level calculation information"""
    # This endpoint returns the level calculation logic for the frontend
    return JSONResponse({
        "formula": {
            "skills": "floor(skills / 3)",
            "climbs": "floor(climbs / 2)",
            "achievements": "achievements * 2",
            "total": "skills_level + climbs_level + achievements_level + 1"
        },
        "description": "Level calculation based on skills, climbs, and achievements",
        "min_level": 1,
        "skill_divisor": 3,
        "climb_divisor": 2,
        "achievement_multiplier": 2
    })


@router.get("/profile-picture/{user_id}")
async def get_profile_picture(user_id: str):
    """Serve cached profile picture with fallback to Google URL"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Try to get cached image from Redis
        image_data = await redis_store.get_image("profile", f"{user_id}/picture")

        if image_data:
            headers = {
                "Cache-Control": "public, max-age=604800, immutable"
            }
            return Response(
                content=image_data,
                media_type="image/jpeg",  # Most Google profile pics are JPEG
                headers=headers
            )

        # If not in cache, get user info and redirect to Google URL
        if permissions_manager:
            user = await permissions_manager.get_user(user_id)
            if user and user.get("picture"):
                return RedirectResponse(url=user["picture"])

        # If all else fails, return 404
        raise HTTPException(status_code=404, detail="Profile picture not found")

    except Exception as e:
        logger.error(f"Error serving profile picture for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve profile picture")


@router.post("/upload-face")
async def upload_face_image(
    file: UploadFile = File(...),
    person_name: str = Form(...),
    user: dict = Depends(get_current_user)
):
    """Upload a temporary face image for a person."""
    redis_store = get_redis_store()

    # Validate user authentication
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate person name
    if not person_name or not person_name.strip():
        raise HTTPException(status_code=400, detail="Person name is required")

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        validated_name = validate_name(person_name.strip())
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="Please upload a valid image file")

    try:
        # Validate image file type and size
        image_data = await file.read()
        validate_image_file(file.content_type, len(image_data))

        # Store as temporary image in Redis (expires after 1 hour)
        temp_path = await redis_store.store_image("temp", validated_name, image_data)

        return JSONResponse({
            "success": True,
            "message": "Image uploaded successfully",
            "temp_path": temp_path,
            "person_name": validated_name
        })

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error uploading face image for {validated_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image") 
