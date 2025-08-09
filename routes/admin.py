import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
from datetime import datetime
import hashlib
from PIL import Image
import io

from auth import get_current_user
from dependencies import get_redis_store, get_permissions_manager, get_jwt_manager
from permissions import ResourceType, UserRole
from utils.export_utils import export_redis_database
from utils.background_tasks import perform_album_metadata_refresh
from routes.notifications import send_push_notification_to_subscriptions
from config import settings
from validation import validate_image_file

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/admin", tags=["admin"])

# Notification images are now stored in Redis with optimization


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
        all_locations = redis_store.redis.smembers("index:locations:all")

        # Get unowned resources
        unowned_albums = await permissions_manager.get_unowned_resources(ResourceType.ALBUM)
        unowned_crew = await permissions_manager.get_unowned_resources(ResourceType.CREW_MEMBER)
        unowned_locations = await permissions_manager.get_unowned_resources(ResourceType.LOCATION)

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
                },
                "locations": {
                    "total": len(all_locations),
                    "unowned": len(unowned_locations)
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
        # Get all albums, crew members, and locations
        all_albums = redis_store.redis.smembers("index:albums:all")
        all_crew = redis_store.redis.smembers("index:climbers:all")
        all_locations = redis_store.redis.smembers("index:locations:all")

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

        # Get locations with owners
        location_details = []
        for loc_name in all_locations:
            loc_data = redis_store.redis.hgetall(f"location:{loc_name}") or {}
            # Get owner information (multiple owners)
            owner_ids = await permissions_manager.get_resource_owners(ResourceType.LOCATION, loc_name)
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
            location_details.append({
                "type": "location",
                "id": loc_name,
                "name": loc_name,
                "created_at": loc_data.get("created_at", ""),
                "owners": owners_info
            })

        # Sort by creation date (newest first)
        all_resources = album_details + crew_details + location_details
        all_resources.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return JSONResponse({
            "resources": all_resources,
            "total": len(all_resources),
            "albums": len(album_details),
            "crew_members": len(crew_details),
            "locations": len(location_details)
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
        unowned_locations = await permissions_manager.get_unowned_resources(ResourceType.LOCATION)

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

        # Unowned locations list
        location_details = []
        for loc_name in unowned_locations:
            loc_data = redis_store.redis.hgetall(f"location:{loc_name}") or {}
            location_details.append({
                "type": "location",
                "id": loc_name,
                "name": loc_name,
                "created_at": loc_data.get("created_at", "")
            })

        return JSONResponse({
            "albums": album_details,
            "crew_members": crew_details,
            "locations": location_details,
            "total": len(album_details) + len(crew_details) + len(location_details)
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
        elif resource_type == "location":
            resource_type_enum = ResourceType.LOCATION
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
        elif resource_type == "location":
            resource_type_enum = ResourceType.LOCATION
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
            "message": "Album metadata refresh completed",
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
            "import_command": "cat climbing_db_export.txt | base64 -d | redis-cli --pipe",
            "export": export_data,
        })

    except Exception as e:
        logger.error(f"Error exporting database: {e}")
        raise HTTPException(status_code=500, detail="Failed to export database")

# Add these new models and endpoints before the existing endpoints


class NotificationAction(BaseModel):
    """Notification action button"""
    action: str
    title: str
    icon: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class SystemNotificationRequest(BaseModel):
    """Request to send system notification with full Web Notifications API support"""
    title: str
    body: str
    target_users: Optional[List[str]] = None  # If None, send to all users

    # Visual content
    icon: Optional[str] = None
    image: Optional[str] = None
    badge: Optional[str] = None

    # Behavior
    tag: Optional[str] = None
    url: Optional[str] = None
    require_interaction: Optional[bool] = False
    silent: Optional[bool] = False
    renotify: Optional[bool] = False

    # Internationalization
    lang: Optional[str] = None
    dir: Optional[str] = None

    # Timing
    timestamp: Optional[int] = None

    # Mobile features
    vibrate: Optional[List[int]] = None

    # Action buttons
    actions: Optional[List[NotificationAction]] = None


class UserNotificationPreferences(BaseModel):
    """User notification preferences update"""
    album_created: bool = True
    crew_member_added: bool = True
    meme_uploaded: bool = True
    system_announcements: bool = True


@router.get("/users/{user_id}/notifications")
async def get_user_notifications(user_id: str, user: dict = Depends(get_current_user)):
    """Get notification settings for a specific user (admin only)"""
    current_user_id = user.get("id")
    if not current_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()
    redis_store = get_redis_store()

    if permissions_manager is None:
        raise HTTPException(status_code=503, detail="Permissions system unavailable")
    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(current_user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get target user info
        target_user = await permissions_manager.get_user(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user's notification devices
        device_subscriptions = await redis_store.get_user_device_subscriptions(user_id)

        # Format device data for admin view
        devices = []
        for sub in device_subscriptions:
            preferences_json = sub.get("notification_preferences", "{}")
            try:
                preferences = json.loads(preferences_json) if preferences_json else {}
            except json.JSONDecodeError:
                preferences = {
                    "album_created": True,
                    "crew_member_added": True,
                    "meme_uploaded": True,
                    "system_announcements": True
                }

            device = {
                "device_id": sub.get("device_id"),
                "browser_name": sub.get("browser_name", "unknown"),
                "platform": sub.get("platform", "unknown"),
                "created_at": sub.get("created_at"),
                "last_used": sub.get("last_used"),
                "notification_preferences": preferences
            }
            devices.append(device)

        return JSONResponse({
            "user": {
                "id": target_user["id"],
                "name": target_user["name"],
                "email": target_user["email"]
            },
            "devices": devices
        })

    except Exception as e:
        logger.error(f"Error getting user notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user notifications")


@router.put("/users/{user_id}/notifications/{device_id}")
async def update_user_device_notifications(
    user_id: str,
    device_id: str,
    preferences: UserNotificationPreferences,
    user: dict = Depends(get_current_user)
):
    """Update notification preferences for a user's device (admin only)"""
    current_user_id = user.get("id")
    if not current_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions_manager = get_permissions_manager()
    redis_store = get_redis_store()

    if permissions_manager is None:
        raise HTTPException(status_code=503, detail="Permissions system unavailable")
    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check admin permissions
    try:
        await permissions_manager.require_permission(current_user_id, "manage_users")
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Verify the device belongs to the target user
        subscription = await redis_store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Device does not belong to target user")

        # Update preferences
        preferences_dict = preferences.dict()
        success = await redis_store.update_device_notification_preferences(device_id, preferences_dict)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update preferences")

        logger.info(
            f"Admin {user.get('email')} updated notification preferences for user {user_id} device {device_id[:15]}...")

        return JSONResponse({
            "success": True,
            "message": "Notification preferences updated successfully",
            "preferences": preferences_dict
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user device notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user device notifications")


@router.post("/notifications/upload-image")
async def upload_notification_image(
    image: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """Upload an optimized image for use in notifications (stored in Redis)"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Validate user is admin
    if not user.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate image file
    if not image.content_type or not image.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Check file size (5MB limit for upload)
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
    content = await image.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Image must be less than 5MB")

    # Validate image file
    validate_image_file(image.content_type, len(content))

    try:
        # Optimize image for notifications (resize and compress)
        optimized_data = optimize_notification_image(content)

        # Generate unique identifier
        image_hash = hashlib.md5(content + str(datetime.now().timestamp()).encode()).hexdigest()
        identifier = f"notification_{image_hash}"

        # Store in Redis with TTL (30 days for notification images)
        image_path = await redis_store.store_image("notification", identifier, optimized_data)

        # Set TTL for notification images (30 days)
        redis_store.binary_redis.expire(f"image:notification:{identifier}", 30 * 24 * 3600)

        logger.info(
            f"Admin {user.get('email')} uploaded notification image: {identifier} (original: {len(content)} bytes, optimized: {len(optimized_data)} bytes)")

        return JSONResponse({
            "success": True,
            "image_url": image_path,
            "identifier": identifier,
            "original_size": len(content),
            "optimized_size": len(optimized_data)
        })

    except Exception as e:
        logger.error(f"Error uploading notification image: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")


def optimize_notification_image(image_data: bytes, max_size: int = 50 * 1024) -> bytes:
    """
    Optimize image for notifications by resizing and compressing
    Target: < 50KB for better notification performance
    """
    try:
        # Open image
        img = Image.open(io.BytesIO(image_data))

        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ('RGBA', 'LA', 'P'):
            # For transparent images, use a white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Start with reasonable size for notifications (max 512x512)
        max_dimension = 512
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        # Try different quality settings to get under target size
        quality_levels = [85, 75, 65, 55, 45, 35]

        for quality in quality_levels:
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            output_size = output.tell()

            if output_size <= max_size:
                output.seek(0)
                return output.read()

        # If still too large, try reducing dimensions further
        max_dimension = 256
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        for quality in [65, 55, 45, 35, 25]:
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            output_size = output.tell()

            if output_size <= max_size:
                output.seek(0)
                return output.read()

        # Last resort: very small image
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=20, optimize=True)
        output.seek(0)
        return output.read()

    except Exception as e:
        logger.error(f"Error optimizing notification image: {e}")
        # If optimization fails, return original data truncated
        return image_data[:max_size]


@router.get("/notifications/images")
async def list_notification_images(user: dict = Depends(get_current_user)):
    """List available notification images from Redis"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Validate user is admin
    if not user.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        # Get all notification image keys from Redis
        keys = redis_store.binary_redis.keys("image:notification:*")
        images = []

        for key in keys:
            if isinstance(key, bytes):
                key = key.decode('utf-8')

            # Extract identifier from key (image:notification:identifier)
            identifier = key.split(":", 2)[-1]
            image_url = f"/redis-image/notification/{identifier}"

            # Get TTL
            ttl = redis_store.binary_redis.ttl(key)
            ttl_days = ttl // (24 * 3600) if ttl > 0 else None

            images.append({
                "identifier": identifier,
                "image_url": image_url,
                "ttl_days": ttl_days
            })

        return JSONResponse({
            "success": True,
            "images": images,
            "count": len(images)
        })

    except Exception as e:
        logger.error(f"Error listing notification images: {e}")
        raise HTTPException(status_code=500, detail="Failed to list notification images")


# Notification images are now served via /redis-image/notification/{identifier}


@router.post("/notifications/system")
async def send_system_notification(
    notification: SystemNotificationRequest,
    user: dict = Depends(get_current_user)
):
    """Send system notification to users with FCM-compatible payload handling"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Validate user is admin
    if not user.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate VAPID configuration
    if not settings.validate_vapid_config():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    try:
        # Get all device subscriptions
        all_subscriptions = await redis_store.get_all_device_push_subscriptions()

        if not all_subscriptions:
            raise HTTPException(status_code=400, detail="No devices are subscribed to notifications")

        # Filter subscriptions based on target
        filtered_subscriptions = []
        target_description = "all users"

        if notification.target_users is None:
            # Send to all subscribed devices
            for subscription in all_subscriptions:
                # Check notification preferences
                preferences_json = subscription.get("notification_preferences", "{}")
                try:
                    preferences = json.loads(preferences_json)
                    if preferences.get("system_announcements", True):
                        filtered_subscriptions.append(subscription)
                except json.JSONDecodeError:
                    # If preferences can't be parsed, send notification (fail-safe)
                    filtered_subscriptions.append(subscription)
        else:
            # Send to specific users
            target_description = f"{len(notification.target_users)} specific user(s)"
            for subscription in all_subscriptions:
                user_id = subscription.get("user_id")
                if user_id in notification.target_users:
                    # Check notification preferences
                    preferences_json = subscription.get("notification_preferences", "{}")
                    try:
                        preferences = json.loads(preferences_json)
                        if preferences.get("system_announcements", True):
                            filtered_subscriptions.append(subscription)
                    except json.JSONDecodeError:
                        # If preferences can't be parsed, send notification (fail-safe)
                        filtered_subscriptions.append(subscription)

        if not filtered_subscriptions:
            raise HTTPException(
                status_code=400,
                detail="No devices found for the target users or all users have disabled system notifications")

        # Create FCM-compatible notification payload (KEEP IT SMALL!)
        notification_payload = {
            "title": notification.title,
            "body": notification.body,
            "icon": "/static/favicon/android-chrome-192x192.png",  # Always use server URL
            "badge": "/static/favicon/favicon-32x32.png",  # Always use server URL
            "tag": notification.tag or f"system_announcement_{int(datetime.now().timestamp())}",
            "requireInteraction": notification.require_interaction or False,
            "silent": notification.silent or False,
            "renotify": notification.renotify or False,
            "data": {
                "url": notification.url or "/",
                "type": "system_announcement",
                "timestamp": notification.timestamp or int(datetime.now().timestamp() * 1000)
            }
        }

        # Handle custom icon - Redis image paths or static URLs
        if notification.icon:
            notification_payload["icon"] = notification.icon

        # Handle custom image - Redis image paths or static URLs
        if notification.image:
            notification_payload["image"] = notification.image

        # Handle custom badge - Redis image paths or static URLs
        if notification.badge:
            notification_payload["badge"] = notification.badge

        # Store advanced Web Notifications API features in data section for service worker
        advanced_features = {}

        # Internationalization
        if notification.lang:
            advanced_features["lang"] = notification.lang
        if notification.dir:
            advanced_features["dir"] = notification.dir

        # Custom timestamp
        if notification.timestamp:
            advanced_features["timestamp"] = notification.timestamp

        # Vibration pattern for mobile devices
        if notification.vibrate and len(notification.vibrate) > 0:
            advanced_features["vibrate"] = notification.vibrate

        # Action buttons
        if notification.actions and len(notification.actions) > 0:
            actions = []
            original_actions = []

            for action in notification.actions[:2]:  # Limit to 2 actions per Web API spec
                # Create action for service worker
                action_data = {
                    "action": action.action,
                    "title": action.title
                }

                if action.icon:
                    action_data["icon"] = action.icon

                actions.append(action_data)

                # Store complete action data for service worker access
                original_action = {
                    "action": action.action,
                    "title": action.title,
                    "icon": action.icon,
                    "data": action.data
                }
                original_actions.append(original_action)

            advanced_features["actions"] = actions
            advanced_features["originalActions"] = original_actions

        # Add all advanced features to data section (keeping payload small)
        if advanced_features:
            notification_payload["data"]["webNotificationFeatures"] = advanced_features

        # Send notifications (this will run in the background)
        await send_push_notification_to_subscriptions(
            filtered_subscriptions,
            notification_payload,
            redis_store
        )

        logger.info(
            f"Admin {user.get('email')} sent system notification '{notification.title}' to {len(filtered_subscriptions)} devices ({target_description})")

        return JSONResponse({
            "success": True,
            "message": f"System notification sent to {len(filtered_subscriptions)} device(s)",
            "devices_notified": len(filtered_subscriptions),
            "total_devices": len(all_subscriptions),
            "filtered_by_preferences": len(all_subscriptions) - len(filtered_subscriptions)
        })

    except Exception as e:
        logger.error(f"Error sending system notification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")
