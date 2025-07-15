import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from auth import get_current_user
from dependencies import get_redis_store
from validation import ValidationError

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/preferences/{preference_key}")
async def set_user_preference(
    preference_key: str,
    request: dict,
    user: dict = Depends(get_current_user)
):
    """Set a user preference"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        preference_value = request.get("value")
        if preference_value is None:
            raise HTTPException(status_code=400, detail="Preference value is required")

        await redis_store.set_user_preference(user_id, preference_key, preference_value)

        return JSONResponse({
            "success": True,
            "message": f"Preference '{preference_key}' saved successfully",
            "preference_key": preference_key,
            "preference_value": preference_value
        })

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting user preference: {e}")
        raise HTTPException(status_code=500, detail="Failed to save preference")


@router.get("/preferences/{preference_key}")
async def get_user_preference(
    preference_key: str,
    user: dict = Depends(get_current_user)
):
    """Get a user preference"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        preference_value = await redis_store.get_user_preference(user_id, preference_key)

        return JSONResponse({
            "preference_key": preference_key,
            "preference_value": preference_value,
            "exists": preference_value is not None
        })

    except Exception as e:
        logger.error(f"Error getting user preference: {e}")
        raise HTTPException(status_code=500, detail="Failed to get preference")


@router.get("/preferences")
async def get_all_user_preferences(user: dict = Depends(get_current_user)):
    """Get all user preferences"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        preferences = await redis_store.get_all_user_preferences(user_id)

        return JSONResponse({
            "preferences": preferences,
            "user_id": user_id
        })

    except Exception as e:
        logger.error(f"Error getting user preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to get preferences")


@router.delete("/preferences/{preference_key}")
async def delete_user_preference(
    preference_key: str,
    user: dict = Depends(get_current_user)
):
    """Delete a user preference"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        deleted = await redis_store.delete_user_preference(user_id, preference_key)

        return JSONResponse({
            "success": deleted,
            "message": f"Preference '{preference_key}' {'deleted' if deleted else 'not found'}",
            "preference_key": preference_key
        })

    except Exception as e:
        logger.error(f"Error deleting user preference: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete preference") 
