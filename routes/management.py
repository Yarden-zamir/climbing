import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import get_current_user, require_auth
from dependencies import get_redis_store, get_permissions_manager
from permissions import ResourceType, UserRole
from redis_store import ValidationError
from validation import ValidationError as InputValidationError, validate_skill_name, validate_achievement_name

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api", tags=["management"])


# Request bodies. Field names match what static/js/locations.js and static/js/admin.js send.

class NameRequest(BaseModel):
    name: str


class LocationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    approach: Optional[str] = None
    custom_markers: Optional[list[dict[str, Any]]] = None


class LocationUpdate(BaseModel):
    new_name: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    approach: Optional[str] = None
    custom_markers: Optional[list[dict[str, Any]]] = None


class LocationAttributesRequest(BaseModel):
    attributes: list[str | dict[str, str]]


async def require_approved_account(permissions_manager, user_id: str) -> None:
    """Deny pending accounts the same way permissions.require_resource_access does."""
    account = await permissions_manager.get_user(user_id)
    role = account.get("role", UserRole.PENDING.value) if account else UserRole.PENDING.value
    if not permissions_manager.get_user_permissions(role).can_edit_own_resources:
        raise HTTPException(
            status_code=403,
            detail="Your account is pending approval. You cannot manage locations until an administrator approves you.",
        )


# === SKILLS MANAGEMENT ===

@router.get("/skills")
async def get_skills():
    """Get all unique skills from Redis"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        skills = await redis_store.get_all_skills()
        return JSONResponse(skills)
    except Exception as e:
        logger.error(f"Error getting skills: {e}")
        raise HTTPException(status_code=500, detail="Failed to get skills")


@router.post("/skills")
async def add_skill(body: NameRequest, user: dict = Depends(require_auth)):
    """Add a new skill"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        skill_name = validate_skill_name(body.name)

        # Add the skill to Redis
        redis_store.redis.sadd("index:skills:all", skill_name)

        logger.info(f"Added skill: {skill_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Skill '{skill_name}' added successfully"})

    except HTTPException:
        raise
    except (ValidationError, InputValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding skill: {e}")
        raise HTTPException(status_code=500, detail="Failed to add skill")


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str, user: dict = Depends(require_auth)):
    """Delete a skill"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        # Remove the skill from Redis
        redis_store.redis.srem("index:skills:all", skill_name)

        # Also remove from all climbers who have this skill
        all_climbers = await redis_store.get_all_climbers()
        for climber in all_climbers:
            if skill_name in climber.get("skills", []):
                updated_skills = [s for s in climber["skills"] if s != skill_name]
                await redis_store.update_climber(
                    original_name=climber["name"],
                    skills=updated_skills
                )

        logger.info(f"Deleted skill: {skill_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Skill '{skill_name}' deleted successfully"})

    except HTTPException:
        raise
    except (ValidationError, InputValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting skill: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete skill")


# === LOCATIONS (FIRST-CLASS ENTITY) ===

@router.get("/locations")
async def get_locations(user: Optional[dict] = Depends(get_current_user)):
    """Get all canonical locations including ownership info when available."""
    redis_store = get_redis_store()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        locations = await redis_store.get_all_locations()

        # Attach owners in one round trip (same key format as PermissionsManager.get_resource_owners)
        if get_permissions_manager() is not None:
            named = [loc for loc in locations if loc.get("name")]
            pipe = redis_store.redis.pipeline()
            for loc in named:
                pipe.smembers(f"ownership:{ResourceType.LOCATION.value}:{loc['name']}")
            for loc, owners in zip(named, pipe.execute()):
                loc["owners"] = list(owners)

        return JSONResponse(locations)
    except Exception as e:
        logger.error(f"Error getting locations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get locations")


# === LOCATION ATTRIBUTES MANAGEMENT ===

@router.get("/location-attributes")
async def get_location_attributes():
    """Get all unique location attributes from Redis"""
    redis_store = get_redis_store()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        attributes = await redis_store.get_all_location_attributes()
        return JSONResponse(attributes)
    except Exception as e:
        logger.error(f"Error getting location attributes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get location attributes")


@router.post("/location-attributes")
async def add_location_attribute(body: NameRequest, user: dict = Depends(require_auth)):
    """Add a new location attribute (admin only)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        attribute_name = body.name.strip()
        if not attribute_name:
            raise HTTPException(status_code=400, detail="Attribute name is required")

        # Add to global index
        redis_store.redis.sadd("index:location_attributes:all", attribute_name)
        logger.info(f"Added location attribute: {attribute_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Attribute '{attribute_name}' added successfully"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding location attribute: {e}")
        raise HTTPException(status_code=500, detail="Failed to add location attribute")


@router.delete("/location-attributes/{attribute_name}")
async def delete_location_attribute(attribute_name: str, user: dict = Depends(require_auth)):
    """Delete a location attribute globally (admin only)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        ok = await redis_store.delete_location_attribute_global(attribute_name)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid attribute name")
        return JSONResponse({"success": True, "message": f"Attribute '{attribute_name}' deleted successfully"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting location attribute: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete location attribute")


@router.put("/locations/attributes")
async def set_attributes_for_location(
    body: LocationAttributesRequest,
    name: str = Query(..., description="Location name"),
    user: dict = Depends(require_auth)
):
    """Replace the attributes list for a given location (owner or admin)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        # Verify location exists
        all_locations = await redis_store.get_all_locations()
        target = next((loc for loc in all_locations if loc.get("name") == name), None)
        if not target:
            raise HTTPException(status_code=404, detail="Location not found")

        if permissions_manager is not None:
            await permissions_manager.require_resource_access(user_id, ResourceType.LOCATION, name, "edit")

        attributes = body.attributes
        ok = await redis_store.set_location_attributes(name, attributes)
        if not ok:
            raise HTTPException(status_code=404, detail="Location not found")

        return JSONResponse({"success": True, "name": name, "attributes": attributes})
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting location attributes: {e}")
        raise HTTPException(status_code=500, detail="Failed to set location attributes")

@router.post("/locations")
async def create_location(body: LocationCreate, user: dict = Depends(require_auth)):
    """Create a new canonical location (idempotent by name)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        # Allow all authenticated users to propose locations; can tighten later if needed
        name = body.name.strip()
        description = (body.description or "").strip() or None
        if not name:
            raise HTTPException(status_code=400, detail="Location name is required")

        await redis_store.add_location(
            name, description, body.latitude, body.longitude, body.approach, body.custom_markers
        )

        # Claim ownership for creator
        if permissions_manager is not None:
            try:
                await permissions_manager.add_resource_owner(ResourceType.LOCATION, name, user_id)
            except Exception:
                pass
        return JSONResponse({"success": True, "name": name})
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating location: {e}")
        raise HTTPException(status_code=500, detail="Failed to create location")


@router.put("/locations")
async def update_location(
    body: LocationUpdate,
    name: str = Query(...),
    user: dict = Depends(require_auth)
):
    """Update an existing location's description/coords or rename (owners only, admins allowed)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_resource_access(user_id, ResourceType.LOCATION, name, "edit")

        new_name = (body.new_name or "").strip()
        description = body.description or None
        approach = body.approach or None
        latitude = body.latitude
        longitude = body.longitude
        custom_markers = body.custom_markers

        # If renaming, handle that first (it also preserves and updates fields)
        if new_name and new_name != name:
            renamed = await redis_store.rename_location(name, new_name)
            if not renamed:
                raise HTTPException(status_code=404, detail="Location not found")
            if permissions_manager is not None:
                await permissions_manager.rename_resource(ResourceType.LOCATION, name, new_name)
            # After rename, optionally apply field updates to the new key
            if any(v is not None for v in (description, latitude, longitude, approach, custom_markers)):
                await redis_store.update_location(new_name, description, latitude, longitude, approach, custom_markers)
            return JSONResponse({"success": True, "name": new_name})

        updated = await redis_store.update_location(name, description, latitude, longitude, approach, custom_markers)
        if not updated:
            raise HTTPException(status_code=404, detail="Location not found")
        return JSONResponse({"success": True, "name": name})
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        raise HTTPException(status_code=500, detail="Failed to update location")


@router.post("/locations/claim")
async def claim_location(body: NameRequest, user: dict = Depends(require_auth)):
    """Claim ownership of a location (adds current user as owner)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        # Ensure location exists
        target_name = body.name.strip()
        if not target_name:
            raise HTTPException(status_code=400, detail="Location name is required")
        names = [loc.get("name") for loc in await redis_store.get_all_locations()]
        if target_name not in names:
            raise HTTPException(status_code=404, detail="Location not found")

        if permissions_manager is not None:
            await require_approved_account(permissions_manager, user_id)
            await permissions_manager.add_resource_owner(ResourceType.LOCATION, target_name, user_id)

        return JSONResponse({"success": True, "name": target_name})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming location: {e}")
        raise HTTPException(status_code=500, detail="Failed to claim location")


@router.delete("/locations")
async def delete_location(
    name: str = Query(..., description="Canonical location name to delete"),
    force_clear: bool = Query(False, description="When true, clear location ties from dependent albums"),
    reassign_to: str | None = Query(None, description="If provided, reassign dependent albums to this target location"),
    user: dict = Depends(require_auth)
):
    """Delete a canonical location and handle dependent albums.

    Rules:
    - Only owners of the location or admins can delete.
    - If there are albums tied to the location, the request must either set `force_clear=true` to remove
      the location from those albums, or provide `reassign_to=<name>` to move them to another location.
    - If neither is provided and dependencies exist, return 409 with a helpful message and counts.
    """
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user["id"]

        # Verify location exists
        all_locations = await redis_store.get_all_locations()
        target_exists = any((loc.get("name") == name) for loc in all_locations)
        if not target_exists:
            raise HTTPException(status_code=404, detail="Location not found")

        if permissions_manager is not None:
            await permissions_manager.require_resource_access(user_id, ResourceType.LOCATION, name, "delete")

        # Execute deletion with provided strategy
        result = await redis_store.delete_location(name, force_clear=force_clear, reassign_to=reassign_to)

        if not result.get("deleted"):
            blocked = result.get("blocked_by_albums", 0)
            if blocked:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Location has dependent albums. Choose force_clear or reassign_to.",
                        "blocked_by_albums": blocked,
                    }
                )
            raise HTTPException(status_code=500, detail="Failed to delete location")

        if permissions_manager is not None:
            await permissions_manager.release_resource(ResourceType.LOCATION, name)

        return JSONResponse({
            "success": True,
            "message": "Location deleted successfully",
            "name": name,
            "affected_albums": result.get("affected_albums", 0),
            "reassigned_to": result.get("reassigned_to")
        })
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting location: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete location")

# === ACHIEVEMENTS MANAGEMENT ===

@router.get("/achievements")
async def get_achievements():
    """Get all unique achievements from Redis"""
    redis_store = get_redis_store()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        achievements = await redis_store.get_all_achievements()
        return JSONResponse(achievements)
    except Exception as e:
        logger.error(f"Error getting achievements: {e}")
        raise HTTPException(status_code=500, detail="Failed to get achievements")


@router.post("/achievements")
async def add_achievement(body: NameRequest, user: dict = Depends(require_auth)):
    """Add a new achievement"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        achievement_name = validate_achievement_name(body.name)

        # Add the achievement to Redis
        redis_store.redis.sadd("index:achievements:all", achievement_name)

        logger.info(f"Added achievement: {achievement_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Achievement '{achievement_name}' added successfully"})

    except HTTPException:
        raise
    except (ValidationError, InputValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to add achievement")


@router.delete("/achievements/{achievement_name}")
async def delete_achievement(achievement_name: str, user: dict = Depends(require_auth)):
    """Delete an achievement"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user["id"]

        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "manage_users")

        # Remove the achievement from Redis
        redis_store.redis.srem("index:achievements:all", achievement_name)

        # Also remove from all climbers who have this achievement
        all_climbers = await redis_store.get_all_climbers()
        for climber in all_climbers:
            if achievement_name in climber.get("achievements", []):
                updated_achievements = [a for a in climber["achievements"] if a != achievement_name]
                await redis_store.update_climber(
                    original_name=climber["name"],
                    achievements=updated_achievements
                )

        logger.info(f"Deleted achievement: {achievement_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Achievement '{achievement_name}' deleted successfully"})

    except HTTPException:
        raise
    except (ValidationError, InputValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete achievement") 
