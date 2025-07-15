import datetime
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse

from auth import oauth_handler, get_current_user
from config import settings
from dependencies import get_redis_store, get_permissions_manager

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login")
async def login():
    """Initiate Google OAuth login"""
    if not settings.validate_oauth_config():
        raise HTTPException(
            status_code=500,
            detail="OAuth not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    auth_url = oauth_handler.generate_auth_url()
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def auth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handle OAuth callback from Google"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if error:
        logger.error(f"OAuth error: {error}")
        return RedirectResponse(url="/?error=oauth_error")

    if not code:
        logger.error("No authorization code received")
        return RedirectResponse(url="/?error=no_code")

    try:
        # Exchange code for token
        token_data = await oauth_handler.exchange_code_for_token(code)
        access_token = token_data.get("access_token")

        if not access_token:
            logger.error("No access token received")
            return RedirectResponse(url="/?error=no_token")

        # Get user info
        user_info = await oauth_handler.get_user_info(access_token)

        # Cache profile picture if available
        profile_picture_url = user_info.get("picture")
        if profile_picture_url:
            try:
                # Fetch and cache the profile picture
                async with httpx.AsyncClient() as client:
                    response = await client.get(profile_picture_url)
                    if response.status_code == 200 and redis_store:
                        # Store in Redis with user ID as identifier
                        image_path = await redis_store.store_image(
                            "profile",
                            f"{user_info['id']}/picture",
                            response.content
                        )
                        # Update picture URL to use our cached version
                        user_info["picture"] = image_path
                    else:
                        logger.warning(f"Failed to fetch profile picture: {response.status_code}")
            except Exception as e:
                logger.warning(f"Failed to cache profile picture: {e}")

        # Prepare user session data (basic version for now)
        user_session_data = {
            "id": user_info.get("id"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            "verified_email": user_info.get("verified_email", False),
            "authenticated": True,
            "login_time": datetime.datetime.now().isoformat()
        }

        # Enable permissions integration
        if permissions_manager is not None:
            try:
                # Create or update user in permissions system
                user_record = await permissions_manager.create_or_update_user(user_info)
                user_session_data["role"] = user_record.get("role", "user")

                # Get permissions for session
                permissions = permissions_manager.get_user_permissions(user_record.get("role", "user"))
                user_session_data["permissions"] = {
                    "can_create_albums": permissions.can_create_albums,
                    "can_create_crew": permissions.can_create_crew,
                    "can_create_memes": permissions.can_create_memes,
                    "can_edit_own_resources": permissions.can_edit_own_resources,
                    "can_delete_own_resources": permissions.can_delete_own_resources,
                    "can_edit_all_resources": permissions.can_edit_all_resources,
                    "can_delete_all_resources": permissions.can_delete_all_resources,
                    "can_manage_users": permissions.can_manage_users
                }

                logger.info(f"User {user_info.get('email')} logged in with role: {user_record.get('role', 'user')}")
            except Exception as e:
                logger.error(f"Error integrating with permissions system: {e}")
                # Fall back to basic session data
                user_session_data["role"] = "user"
                user_session_data["permissions"] = {}
        else:
            logger.warning("Permissions system not available, using basic session data")
            user_session_data["role"] = "user"
            user_session_data["permissions"] = {}

        # Create session and redirect (SessionManager handles both token creation and cookie setting)
        response = RedirectResponse(url="/")
        oauth_handler.session_manager.set_session_cookie(response, user_session_data)

        logger.info(f"🎉 User logged in successfully: {user_info.get('email')}")
        return response

    except Exception as e:
        logger.error(f"OAuth callback error: {e}", exc_info=True)
        return RedirectResponse(url="/?error=auth_failed")


@router.get("/logout")
async def logout():
    """Logout user and clear session"""
    response = RedirectResponse(url="/")
    oauth_handler.session_manager.clear_session_cookie(response)
    return response


# API routes for auth status
api_router = APIRouter(prefix="/api/auth", tags=["auth-api"])


@api_router.get("/user")
async def get_auth_user(user: dict = Depends(get_current_user)):
    """Get current authenticated user info"""
    if user:
        return {
            "authenticated": True,
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "picture": user.get("picture"),
                "verified_email": user.get("verified_email", False),
                "role": user.get("role", "user"),
                "permissions": user.get("permissions", {})
            }
        }
    else:
        return {"authenticated": False, "user": None}


@api_router.get("/status")
async def auth_status(user: dict = Depends(get_current_user)):
    """Get authentication status"""
    return {
        "authenticated": user is not None,
        "user_email": user.get("email") if user else None
    }
