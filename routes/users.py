import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from auth import require_auth
from dependencies import get_store
from validation import ValidationError

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/preferences/{preference_key}")
async def set_user_preference(
    preference_key: str,
    request: dict,
    user: dict = Depends(require_auth)
):
    """Set a user preference"""
    store = get_store()
    
    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        preference_value = request.get("value")
        if preference_value is None:
            raise HTTPException(status_code=400, detail="Preference value is required")

        # The store serializes the value itself, so bool/int/str round-trip through get_user_preference
        await store.set_user_preference(user_id, preference_key, preference_value)

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
    user: dict = Depends(require_auth)
):
    """Get a user preference"""
    store = get_store()
    
    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        preference_value = await store.get_user_preference(user_id, preference_key)

        return JSONResponse({
            "preference_key": preference_key,
            "preference_value": preference_value,
            "exists": preference_value is not None
        })

    except Exception as e:
        logger.error(f"Error getting user preference: {e}")
        raise HTTPException(status_code=500, detail="Failed to get preference")


@router.get("/preferences")
async def get_all_user_preferences(user: dict = Depends(require_auth)):
    """Get all user preferences"""
    store = get_store()
    
    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        preferences = await store.get_all_user_preferences(user_id)

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
    user: dict = Depends(require_auth)
):
    """Delete a user preference"""
    store = get_store()
    
    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        deleted = await store.delete_user_preference(user_id, preference_key)

        return JSONResponse({
            "success": deleted,
            "message": f"Preference '{preference_key}' {'deleted' if deleted else 'not found'}",
            "preference_key": preference_key
        })

    except Exception as e:
        logger.error(f"Error deleting user preference: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete preference") 
