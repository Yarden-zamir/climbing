import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse

from auth import get_current_user
from dependencies import get_redis_store, get_permissions_manager

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api", tags=["management"])


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
async def add_skill(request: dict, user: dict = Depends(get_current_user)):
    """Add a new skill"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "manage_users")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

        skill_name = request.get("name", "").strip()
        if not skill_name:
            raise HTTPException(status_code=400, detail="Skill name is required")

        # Add the skill to Redis
        redis_store.redis.sadd("index:skills:all", skill_name)

        logger.info(f"Added skill: {skill_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Skill '{skill_name}' added successfully"})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding skill: {e}")
        raise HTTPException(status_code=500, detail="Failed to add skill")


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str, user: dict = Depends(get_current_user)):
    """Delete a skill"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "manage_users")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

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
    except Exception as e:
        logger.error(f"Error deleting skill: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete skill")


# === LOCATIONS (FIRST-CLASS ENTITY) ===

@router.get("/locations")
async def get_locations(user: dict = Depends(get_current_user)):
    """Get all canonical locations including ownership info when available."""
    redis_store = get_redis_store()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        locations = await redis_store.get_all_locations()

        # Attach owners if permissions manager is available
        permissions_manager = get_permissions_manager()
        if permissions_manager is not None:
            from permissions import ResourceType
            for loc in locations:
                name = loc.get("name")
                if name:
                    try:
                        owners = await permissions_manager.get_resource_owners(ResourceType.LOCATION, name)
                        loc["owners"] = owners
                    except Exception:
                        loc["owners"] = []

        return JSONResponse(locations)
    except Exception as e:
        logger.error(f"Error getting locations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get locations")


@router.post("/locations")
async def create_location(request: dict, user: dict = Depends(get_current_user)):
    """Create a new canonical location (idempotent by name)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Allow all authenticated users to propose locations; can tighten later if needed
        name = (request.get("name") or "").strip()
        description = (request.get("description") or "").strip() or None
        latitude = request.get("latitude")
        longitude = request.get("longitude")
        approach = request.get("approach")
        if not name:
            raise HTTPException(status_code=400, detail="Location name is required")

        # Validate lat/lng if provided
        try:
            if latitude is not None:
                latitude = float(latitude)
            if longitude is not None:
                longitude = float(longitude)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid latitude/longitude")

        await redis_store.add_location(name, description, latitude, longitude, approach)

        # Claim ownership for creator
        if permissions_manager is not None:
            try:
                from permissions import ResourceType
                await permissions_manager.add_resource_owner(ResourceType.LOCATION, name, user_id)
            except Exception:
                pass
        return JSONResponse({"success": True, "name": name})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating location: {e}")
        raise HTTPException(status_code=500, detail="Failed to create location")


@router.put("/locations")
async def update_location(
    name: str = Query(...),
    request: dict = None,
    user: dict = Depends(get_current_user)
):
    """Update an existing location's description/coords or rename (owners only, admins allowed)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        from permissions import ResourceType
        # Enforce ownership or admin rights
        if permissions_manager is not None:
            try:
                # Either admin (can_edit_all_resources) or owner
                is_owner = await permissions_manager.is_resource_owner(ResourceType.LOCATION, name, user_id)
                if not is_owner:
                    # Check admin capabilities
                    user_perms = permissions_manager.get_user_permissions(user.get("role", "user"))
                    if not user_perms.can_edit_all_resources:
                        raise HTTPException(status_code=403, detail="You don't have permission to edit this location.")
            except HTTPException:
                raise
            except Exception:
                # If permission system fails, default deny
                raise HTTPException(status_code=403, detail="You don't have permission to edit this location.")

        new_name = (request.get("new_name") or "").strip() if request else ""
        description = (request.get("description") or None) if request else None
        approach = (request.get("approach") or None) if request else None
        latitude = request.get("latitude") if request else None
        longitude = request.get("longitude") if request else None
        try:
            if latitude is not None:
                latitude = float(latitude)
            if longitude is not None:
                longitude = float(longitude)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid latitude/longitude")

        # If renaming, handle that first (it also preserves and updates fields)
        if new_name and new_name != name:
            try:
                renamed = await redis_store.rename_location(name, new_name)
                if not renamed:
                    raise HTTPException(status_code=404, detail="Location not found")
                # After rename, optionally apply field updates to the new key
                if any(v is not None for v in (description, latitude, longitude, approach)):
                    await redis_store.update_location(new_name, description, latitude, longitude, approach)
                return JSONResponse({"success": True, "name": new_name})
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise
                # Validation error or other failure
                raise HTTPException(status_code=400, detail=str(e))
        else:
            updated = await redis_store.update_location(name, description, latitude, longitude, approach)
            if not updated:
                raise HTTPException(status_code=404, detail="Location not found")
            return JSONResponse({"success": True, "name": name})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        raise HTTPException(status_code=500, detail="Failed to update location")


@router.post("/locations/claim")
async def claim_location(request: dict, user: dict = Depends(get_current_user)):
    """Claim ownership of a location (adds current user as owner)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Ensure location exists
        target_name = (request.get("name") or "").strip()
        if not target_name:
            raise HTTPException(status_code=400, detail="Location name is required")
        names = [l.get("name") for l in await redis_store.get_all_locations()]
        if target_name not in names:
            raise HTTPException(status_code=404, detail="Location not found")

        if permissions_manager is not None:
            from permissions import ResourceType
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
    user: dict = Depends(get_current_user)
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
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Verify location exists
        all_locations = await redis_store.get_all_locations()
        target_exists = any((loc.get("name") == name) for loc in all_locations)
        if not target_exists:
            raise HTTPException(status_code=404, detail="Location not found")

        # Permission check: owner or admin
        if permissions_manager is not None:
            from permissions import ResourceType
            try:
                is_owner = await permissions_manager.is_resource_owner(ResourceType.LOCATION, name, user_id)
                if not is_owner:
                    user_perms = permissions_manager.get_user_permissions(user.get("role", "user"))
                    if not user_perms.can_delete_all_resources:
                        raise HTTPException(
                            status_code=403, detail="You don't have permission to delete this location.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="You don't have permission to delete this location.")

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

        return JSONResponse({
            "success": True,
            "message": "Location deleted successfully",
            "name": name,
            "affected_albums": result.get("affected_albums", 0),
            "reassigned_to": result.get("reassigned_to")
        })
    except HTTPException:
        raise
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
async def add_achievement(request: dict, user: dict = Depends(get_current_user)):
    """Add a new achievement"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "manage_users")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

        achievement_name = request.get("name", "").strip()
        if not achievement_name:
            raise HTTPException(status_code=400, detail="Achievement name is required")

        # Add the achievement to Redis
        redis_store.redis.sadd("index:achievements:all", achievement_name)

        logger.info(f"Added achievement: {achievement_name} by user: {user_id}")
        return JSONResponse({"success": True, "message": f"Achievement '{achievement_name}' added successfully"})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to add achievement")


@router.delete("/achievements/{achievement_name}")
async def delete_achievement(achievement_name: str, user: dict = Depends(get_current_user)):
    """Delete an achievement"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()
    
    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user has admin permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "manage_users")
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(status_code=403, detail="Admin permissions required")

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
    except Exception as e:
        logger.error(f"Error deleting achievement: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete achievement") 
