import logging
import uuid
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from auth import get_current_user
from dependencies import get_redis_store, get_permissions_manager
from permissions import ResourceType
from validation import ValidationError, validate_image_file

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/memes", tags=["memes"])


@router.get("")
async def get_memes():
    """Get all memes from Redis"""
    redis_store = get_redis_store()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        memes = await redis_store.get_all_memes()

        # Convert to format expected by frontend
        memes_data = []
        for meme in memes:
            memes_data.append({
                "id": meme["id"],
                "creator_id": meme["creator_id"],
                "created_at": meme["created_at"]
            })

        return JSONResponse(memes_data)

    except Exception as e:
        logger.error(f"Error getting memes: {e}")
        return JSONResponse([])


@router.post("/submit")
async def submit_meme(
    image: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """Submit a new meme"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()
    redis_store = get_redis_store()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check if user can create memes
    try:
        can_create = await permissions_manager.can_user_perform_action(user_id, "create_meme")
        if not can_create:
            raise HTTPException(status_code=403, detail="You don't have permission to create memes")

        # Check submission limits
        can_submit = await permissions_manager.check_submission_limits(user_id, ResourceType.MEME)
        if not can_submit:
            raise HTTPException(status_code=403, detail="You have reached your meme submission limit")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Permission check failed")

    try:
        # Validate image
        if not image or not image.filename:
            raise HTTPException(status_code=400, detail="Image is required")

        validate_image_file(image.content_type or "", image.size or 0)

        # Read image data
        image_data = await image.read()

        # Generate unique meme ID
        meme_id = str(uuid.uuid4())

        # Create meme
        await redis_store.add_meme(
            meme_id=meme_id,
            image_data=image_data,
            creator_id=user_id
        )

        # Set resource ownership and increment count
        await permissions_manager.set_resource_owner(ResourceType.MEME, meme_id, user_id)
        await permissions_manager.increment_user_creation_count(user_id, ResourceType.MEME)

        return JSONResponse({
            "success": True,
            "message": "Meme submitted successfully",
            "meme_id": meme_id
        })

    except ValidationError as e:
        logger.error(f"Validation error in meme submission: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting meme: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit meme")


@router.delete("/{meme_id}")
async def delete_meme(meme_id: str, user: dict = Depends(get_current_user)):
    """Delete a meme"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()
    redis_store = get_redis_store()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check if meme exists
    meme = await redis_store.get_meme(meme_id)
    if not meme:
        raise HTTPException(status_code=404, detail="Meme not found")

    # Check permissions
    try:
        await permissions_manager.require_resource_access(user_id, ResourceType.MEME, meme_id, "delete")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="You don't have permission to delete this meme")

    try:
        # Delete meme
        success = await redis_store.delete_meme(meme_id)
        if not success:
            raise HTTPException(status_code=404, detail="Meme not found")

        return JSONResponse({
            "success": True,
            "message": "Meme deleted successfully"
        })

    except Exception as e:
        logger.error(f"Error deleting meme: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete meme")
