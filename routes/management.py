import logging
from fastapi import APIRouter, HTTPException, Depends
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
