import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import JSONResponse

from auth import get_current_user
from dependencies import get_redis_store, get_permissions_manager, get_jwt_manager
from permissions import ResourceType, UserRole
from utils.export_utils import export_redis_database
from utils.background_tasks import perform_album_metadata_refresh

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def get_admin_stats(user: dict = Depends(get_current_user)):
    """Get system statistics (admin only)"""
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

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get users by role
        admin_users = await permissions_manager.get_users_by_role(UserRole.ADMIN)
        regular_users = await permissions_manager.get_users_by_role(UserRole.USER)
        pending_users = await permissions_manager.get_users_by_role(UserRole.PENDING)

        # Get resource counts
        all_albums = redis_store.redis.smembers("index:albums:all")
        all_crew = redis_store.redis.smembers("index:climbers:all")

        # Get unowned resources
        unowned_albums = await permissions_manager.get_unowned_resources(ResourceType.ALBUM)
        unowned_crew = await permissions_manager.get_unowned_resources(ResourceType.CREW_MEMBER)

        return JSONResponse({
            "users": {
                "total": len(admin_users) + len(regular_users) + len(pending_users),
                "admins": len(admin_users),
                "regular": len(regular_users),
                "pending": len(pending_users)
            },
            "resources": {
                "albums": {
                    "total": len(all_albums),
                    "unowned": len(unowned_albums)
                },
                "crew_members": {
                    "total": len(all_crew),
                    "unowned": len(unowned_crew)
                }
            }
        })

    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get admin stats")


@router.get("/users")
async def get_all_users_admin(user: dict = Depends(get_current_user)):
    """Get all users with their roles and resource counts (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        users = await permissions_manager.get_all_users()

        # Enhance user data with resource counts
        enhanced_users = []
        for user_record in users:
            try:
                # Ensure user record has required fields
                if not user_record or not user_record.get("id"):
                    logger.warning(f"Skipping invalid user record: {user_record}")
                    continue

                user_id = user_record["id"]
                user_albums = await permissions_manager.get_user_resources(user_id, ResourceType.ALBUM)
                user_crew = await permissions_manager.get_user_resources(user_id, ResourceType.CREW_MEMBER)

                # Convert permissions to JSON-serializable format
                permissions = permissions_manager.get_user_permissions(user_record.get("role", "user"))
                permissions_dict = {
                    "can_create_albums": permissions.can_create_albums,
                    "can_create_crew": permissions.can_create_crew,
                    "can_edit_own_resources": permissions.can_edit_own_resources,
                    "can_delete_own_resources": permissions.can_delete_own_resources,
                    "can_edit_all_resources": permissions.can_edit_all_resources,
                    "can_delete_all_resources": permissions.can_delete_all_resources,
                    "can_manage_users": permissions.can_manage_users,
                    "submission_limits": {
                        "max_albums": permissions.submission_limits.max_albums if permissions.submission_limits else None,
                        "max_crew_members": permissions.submission_limits.max_crew_members if permissions.submission_limits else None,
                        "requires_approval": permissions.submission_limits.requires_approval if permissions.submission_limits else None
                    } if permissions.submission_limits else None
                }
            except Exception as e:
                logger.warning(f"Failed to get resource counts for user {user_record.get('id', 'unknown')}: {e}")
                user_albums, user_crew = [], []
                permissions_dict = {}

            enhanced_user = {
                **user_record,
                "owned_albums": len(user_albums),
                "owned_crew_members": len(user_crew),
                "permissions": permissions_dict
            }
            enhanced_users.append(enhanced_user)

        return JSONResponse(enhanced_users)

    except Exception as e:
        logger.error(f"Error getting users for admin: {e}")
        raise HTTPException(status_code=500, detail="Failed to get users")


@router.post("/users/{target_user_id}/role")
async def change_user_role(target_user_id: str, new_role: str = Form(...), user: dict = Depends(get_current_user)):
    """Change a user's role (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate role
    try:
        role_enum = UserRole(new_role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {new_role}")

    try:
        # Get current user data before role change
        target_user = await permissions_manager.get_user(target_user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        old_role = target_user.get("role", "user")

        # Update the role
        success = await permissions_manager.update_user_role(target_user_id, role_enum)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")

        # Blacklist all JWT tokens for this user since their permissions changed
        blacklisted_count = 0
        jwt_manager = get_jwt_manager()
        if jwt_manager:
            blacklisted_count = jwt_manager.blacklist_all_user_tokens(target_user_id)

        logger.info(
            f"Admin {user.get('email')} changed user {target_user.get('email')} role from {old_role} to {new_role}, blacklisted {blacklisted_count} tokens")

        return JSONResponse({
            "success": True,
            "message": f"User role updated to {new_role}",
            "blacklisted_tokens": blacklisted_count,
            "security_note": "All existing API tokens have been invalidated due to permission changes"
        })

    except Exception as e:
        logger.error(f"Error changing user role: {e}")
        raise HTTPException(status_code=500, detail="Failed to change user role")


@router.get("/resources/all")
async def get_all_resources_with_owners(user: dict = Depends(get_current_user)):
    """Get all resources with their owner information (admin only)"""
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

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get all albums and crew members
        all_albums = redis_store.redis.smembers("index:albums:all")
        all_crew = redis_store.redis.smembers("index:climbers:all")

        # Get album details with owners
        album_details = []
        for album_url in all_albums:
            album_data = await redis_store.get_album(album_url)
            if album_data:
                # Get owner information (multiple owners)
                owner_ids = await permissions_manager.get_resource_owners(ResourceType.ALBUM, album_url)
                owners_info = []

                for owner_id in owner_ids:
                    owner_user = await permissions_manager.get_user(owner_id)
                    if owner_user:
                        owners_info.append({
                            "id": owner_id,
                            "name": owner_user.get("name", "Unknown"),
                            "email": owner_user.get("email", ""),
                            "picture": owner_user.get("picture", "")
                        })

                album_details.append({
                    "type": "album",
                    "id": album_url,
                    "title": album_data.get("title", "Unknown Album"),
                    "url": album_url,
                    "created_at": album_data.get("created_at", ""),
                    "owners": owners_info
                })

        # Get crew details with owners
        crew_details = []
        for crew_name in all_crew:
            crew_data = await redis_store.get_climber(crew_name)
            if crew_data:
                # Get owner information (multiple owners)
                owner_ids = await permissions_manager.get_resource_owners(ResourceType.CREW_MEMBER, crew_name)
                owners_info = []

                for owner_id in owner_ids:
                    owner_user = await permissions_manager.get_user(owner_id)
                    if owner_user:
                        owners_info.append({
                            "id": owner_id,
                            "name": owner_user.get("name", "Unknown"),
                            "email": owner_user.get("email", ""),
                            "picture": owner_user.get("picture", "")
                        })

                crew_details.append({
                    "type": "crew_member",
                    "id": crew_name,
                    "name": crew_name,
                    "level": crew_data.get("level", 1),
                    "created_at": crew_data.get("created_at", ""),
                    "owners": owners_info
                })

        # Sort by creation date (newest first)
        all_resources = album_details + crew_details
        all_resources.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return JSONResponse({
            "resources": all_resources,
            "total": len(all_resources),
            "albums": len(album_details),
            "crew_members": len(crew_details)
        })

    except Exception as e:
        logger.error(f"Error getting all resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to get all resources")


@router.get("/resources/unowned")
async def get_unowned_resources(user: dict = Depends(get_current_user)):
    """Get all resources without owners (admin only)"""
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

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        unowned_albums = await permissions_manager.get_unowned_resources(ResourceType.ALBUM)
        unowned_crew = await permissions_manager.get_unowned_resources(ResourceType.CREW_MEMBER)

        # Get details for unowned resources
        album_details = []
        for album_url in unowned_albums:
            album_data = await redis_store.get_album(album_url)
            if album_data:
                album_details.append({
                    "type": "album",
                    "id": album_url,
                    "title": album_data.get("title", "Unknown Album"),
                    "url": album_url,
                    "created_at": album_data.get("created_at", "")
                })

        crew_details = []
        for crew_name in unowned_crew:
            crew_data = await redis_store.get_climber(crew_name)
            if crew_data:
                crew_details.append({
                    "type": "crew_member",
                    "id": crew_name,
                    "name": crew_name,
                    "level": crew_data.get("level", 1),
                    "created_at": crew_data.get("created_at", "")
                })

        return JSONResponse({
            "albums": album_details,
            "crew_members": crew_details,
            "total": len(album_details) + len(crew_details)
        })

    except Exception as e:
        logger.error(f"Error getting unowned resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to get unowned resources")


@router.post("/resources/assign")
async def assign_resource_owner(
    resource_type: str = Form(...),
    resource_id: str = Form(...),
    target_user_id: str = Form(...),
    user: dict = Depends(get_current_user)
):
    """Assign ownership of a resource to a user (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Convert string to ResourceType enum
        if resource_type == "album":
            resource_type_enum = ResourceType.ALBUM
        elif resource_type == "crew_member":
            resource_type_enum = ResourceType.CREW_MEMBER
        else:
            raise HTTPException(status_code=400, detail=f"Invalid resource type: {resource_type}")

        # Check if target user exists
        target_user = await permissions_manager.get_user(target_user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")

        # Set resource ownership
        await permissions_manager.set_resource_owner(resource_type_enum, resource_id, target_user_id)

        return JSONResponse({
            "success": True,
            "message": f"Resource ownership assigned to {target_user.get('name', target_user_id)}"
        })

    except Exception as e:
        logger.error(f"Error assigning resource owner: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign resource owner")


@router.post("/resources/remove-owner")
async def remove_resource_owner(
    resource_type: str = Form(...),
    resource_id: str = Form(...),
    target_user_id: str = Form(...),
    user: dict = Depends(get_current_user)
):
    """Remove ownership of a resource from a user (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Convert string to ResourceType enum
        if resource_type == "album":
            resource_type_enum = ResourceType.ALBUM
        elif resource_type == "crew_member":
            resource_type_enum = ResourceType.CREW_MEMBER
        else:
            raise HTTPException(status_code=400, detail=f"Invalid resource type: {resource_type}")

        # Remove resource ownership
        await permissions_manager.remove_resource_owner(resource_type_enum, resource_id, target_user_id)

        return JSONResponse({
            "success": True,
            "message": "Resource ownership removed successfully"
        })

    except Exception as e:
        logger.error(f"Error removing resource owner: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove resource owner")


@router.post("/migrate-resources")
async def migrate_existing_resources(user: dict = Depends(get_current_user)):
    """Migrate existing resources to system ownership (admin only)"""
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()

    # Check if permissions system is available
    if permissions_manager is None:
        logger.error("Permissions system not available")
        raise HTTPException(status_code=503, detail="Permissions system unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        migrated = await permissions_manager.migrate_existing_resources_to_system_ownership()

        return JSONResponse({
            "success": True,
            "message": "Resources migrated successfully",
            "migrated": migrated
        })

    except Exception as e:
        logger.error(f"Error migrating resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to migrate resources")


@router.post("/refresh-metadata")
async def refresh_album_metadata_admin(user: dict = Depends(get_current_user)):
    """Refresh all album metadata (admin only)"""
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

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Trigger background metadata refresh
        refreshed_count = await perform_album_metadata_refresh(redis_store)

        return JSONResponse({
            "success": True,
            "message": f"Album metadata refresh completed",
            "refreshed_albums": refreshed_count
        })

    except Exception as e:
        logger.error(f"Error refreshing album metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh album metadata")


@router.get("/export")
async def export_redis_database_admin(user: dict = Depends(get_current_user)):
    """Export Redis database (admin only)"""
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

    # Check admin permissions
    try:
        await permissions_manager.require_permission(user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        export_data = await export_redis_database(redis_store)

        return JSONResponse({
            "success": True,
            "message": "Database exported successfully",
            "export": export_data
        })

    except Exception as e:
        logger.error(f"Error exporting database: {e}")
        raise HTTPException(status_code=500, detail="Failed to export database") 
