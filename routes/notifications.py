import json
import logging
import base64
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import aiohttp

from auth import get_current_user_hybrid, require_auth_hybrid
from dependencies import get_redis_store
from config import settings
from validation import ValidationError
from webpush import WebPush, WebPushSubscription
from webpush.types import WebPushKeys
from pydantic import AnyHttpUrl

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class PushSubscriptionKeys(BaseModel):
    """Push subscription keys"""
    p256dh: str
    auth: str


class PushSubscriptionData(BaseModel):
    """Push subscription data from browser"""
    endpoint: str
    keys: PushSubscriptionKeys
    expirationTime: Optional[int] = None


class DeviceInfo(BaseModel):
    """Device information from browser"""
    deviceId: str
    browserName: str
    platform: str
    userAgent: str
    lastActive: str


class SubscriptionRequest(BaseModel):
    """Complete subscription request with device info"""
    subscription: PushSubscriptionData
    deviceInfo: DeviceInfo


class SubscriptionReplacementRequest(BaseModel):
    """Request to replace an expired subscription with a new one"""
    oldSubscription: PushSubscriptionData
    newSubscription: PushSubscriptionData
    deviceInfo: DeviceInfo


class NotificationPreferences(BaseModel):
    """Notification preferences for a device"""
    album_created: bool = True
    crew_member_added: bool = True
    meme_uploaded: bool = True
    system_announcements: bool = True


class NotificationPayload(BaseModel):
    """Notification payload for testing"""
    title: str
    body: str
    icon: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


def get_session_id_from_request(request: Request) -> Optional[str]:
    """Extract session ID from request cookies"""
    session_token = request.cookies.get("session")
    if not session_token:
        return None

    # The session token itself serves as our unique session identifier
    # We could hash it for shorter IDs, but the full token works fine
    import hashlib
    return hashlib.md5(session_token.encode()).hexdigest()


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Get VAPID public key for push subscriptions"""
    try:
        public_key = settings.get_raw_public_key()
        if not public_key:
            raise HTTPException(status_code=503, detail="VAPID keys not configured")

        return JSONResponse({"publicKey": public_key})
    except Exception as e:
        logger.error(f"Error getting VAPID public key: {e}")
        raise HTTPException(status_code=500, detail="Failed to get VAPID public key")


@router.post("/subscribe")
async def subscribe_to_notifications(
    request_data: SubscriptionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user_hybrid)
):
    """Subscribe device to push notifications"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # User can be None for anonymous subscriptions
    user_id = user.get("id") if user else None
    device_id = request_data.deviceInfo.deviceId

    try:
        # Convert subscription to dict for Redis storage
        subscription_data = {
            "endpoint": request_data.subscription.endpoint,
            "keys": {
                "p256dh": request_data.subscription.keys.p256dh,
                "auth": request_data.subscription.keys.auth
            },
            "expirationTime": request_data.subscription.expirationTime
        }

        # Convert device info to dict
        device_info = {
            "deviceId": device_id,
            "browserName": request_data.deviceInfo.browserName,
            "platform": request_data.deviceInfo.platform,
            "userAgent": request_data.deviceInfo.userAgent,
            "lastActive": request_data.deviceInfo.lastActive
        }

        # Create WebPushSubscription for welcome notification
        webpush_subscription = WebPushSubscription(
            endpoint=AnyHttpUrl(request_data.subscription.endpoint),
            keys=WebPushKeys(
                p256dh=request_data.subscription.keys.p256dh,
                auth=request_data.subscription.keys.auth
            )
        )

        # Store subscription in Redis with device ID
        subscription_id = await redis_store.store_push_subscription(device_id, user_id, subscription_data, device_info)

        # Send welcome notification in background
        background_tasks.add_task(
            send_welcome_notification,
            webpush_subscription
        )

        user_info = f"user {user.get('email')}" if user else "anonymous user"
        logger.info(f"Device {device_id[:15]}... for {user_info} subscribed to push notifications")

        return JSONResponse({
            "success": True,
            "subscription_id": subscription_id,
            "device_id": device_id[:15] + "...",
            "message": f"Successfully subscribed device to notifications ({request_data.deviceInfo.browserName})"
        })

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error subscribing to notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to subscribe to notifications")


@router.post("/replace-subscription")
async def replace_push_subscription(
    request_data: SubscriptionReplacementRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user_hybrid)
):
    """Replace an expired/changed push subscription with a new one"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Convert old subscription to dict
        old_subscription_data = {
            "endpoint": request_data.oldSubscription.endpoint,
            "keys": {
                "p256dh": request_data.oldSubscription.keys.p256dh,
                "auth": request_data.oldSubscription.keys.auth
            },
            "expirationTime": request_data.oldSubscription.expirationTime
        }

        # Convert new subscription to dict
        new_subscription_data = {
            "endpoint": request_data.newSubscription.endpoint,
            "keys": {
                "p256dh": request_data.newSubscription.keys.p256dh,
                "auth": request_data.newSubscription.keys.auth
            },
            "expirationTime": request_data.newSubscription.expirationTime
        }

        # Convert device info to dict
        device_info = {
            "deviceId": request_data.deviceInfo.deviceId,
            "browserName": request_data.deviceInfo.browserName,
            "platform": request_data.deviceInfo.platform,
            "userAgent": request_data.deviceInfo.userAgent,
            "lastActive": request_data.deviceInfo.lastActive
        }

        # Replace subscription in Redis
        new_subscription_id = await redis_store.replace_push_subscription(
            old_subscription_data, 
            new_subscription_data, 
            device_info
        )

        if not new_subscription_id:
            raise HTTPException(
                status_code=404, 
                detail="Original subscription not found - unable to replace"
            )

        user_info = f"user {user.get('email')}" if user else "anonymous user"
        logger.info(f"Replaced push subscription for {user_info}: {new_subscription_id[:8]}...")

        return JSONResponse({
            "success": True,
            "new_subscription_id": new_subscription_id,
            "message": f"Successfully replaced push subscription ({request_data.deviceInfo.browserName})"
        })

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error replacing push subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to replace push subscription")


@router.get("/subscriptions")
async def get_current_device_subscription(
    request: Request,
    user: dict = Depends(get_current_user_hybrid)
):
    """Get push subscription for the current device"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Extract device ID from request headers or cookies
    device_id = request.headers.get("X-Device-ID")
    if not device_id:
        return JSONResponse({
            "subscription": None,
            "message": "No device ID provided"
        })

    try:
        subscription = await redis_store.get_device_push_subscription(device_id)

        if not subscription:
            return JSONResponse({
                "subscription": None,
                "message": "No subscription found for this device"
            })

        # Remove sensitive data before returning
        safe_subscription = {
            "subscription_id": subscription.get("subscription_id"),
            "device_id": device_id[: 15] + "...", "created_at": subscription.get("created_at"),
            "last_used": subscription.get("last_used"),
            "expirationTime": subscription.get("expirationTime"),
            "browser_name": subscription.get("browser_name"),
            "platform": subscription.get("platform"),
            "endpoint_domain": subscription.get("endpoint", "").split("/")[2]
            if subscription.get("endpoint") else "unknown", "user_associated": subscription.get("user_id") !=
            "anonymous"}

        return JSONResponse({
            "subscription": safe_subscription,
            "message": "Device subscription found"
        })

    except Exception as e:
        logger.error(f"Error getting device subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to get device subscription")


@router.get("/devices")
async def get_user_devices(user: dict = Depends(require_auth_hybrid)):
    """Get all devices with push subscriptions for the current user"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        device_subscriptions = await redis_store.get_user_device_subscriptions(user_id)

        # Remove sensitive data before returning
        safe_devices = []
        for sub in device_subscriptions:
            # Parse notification preferences
            preferences_json = sub.get("notification_preferences", "{}")
            try:
                preferences = json.loads(preferences_json)
            except json.JSONDecodeError:
                preferences = {
                    "album_created": True,
                    "crew_member_added": True,
                    "meme_uploaded": True,
                    "system_announcements": True
                }

            safe_device = {
                "subscription_id": sub.get("subscription_id"),
                "device_id": sub.get("device_id", "unknown")[:15] + "...",
                "full_device_id": sub.get("device_id", "unknown"),  # Include full ID for API calls
                "browser_name": sub.get("browser_name", "unknown"),
                "platform": sub.get("platform", "unknown"),
                "created_at": sub.get("created_at"),
                "last_used": sub.get("last_used"),
                "expirationTime": sub.get("expirationTime"),
                "endpoint_domain": sub.get("endpoint", "").split("/")[2] if sub.get("endpoint") else "unknown",
                "is_active": True,  # Device has a subscription, so it's active
                "notification_preferences": preferences
            }
            safe_devices.append(safe_device)

        return JSONResponse({
            "devices": safe_devices,
            "count": len(safe_devices),
            "user_id": user_id
        })

    except Exception as e:
        logger.error(f"Error getting user devices: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user devices")


@router.get("/devices/{device_id}/preferences")
async def get_device_notification_preferences(
    device_id: str,
    user: dict = Depends(require_auth_hybrid)
):
    """Get notification preferences for a specific device"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify device ownership
        subscription = await redis_store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Get preferences
        preferences = await redis_store.get_device_notification_preferences(device_id)

        return JSONResponse({
            "device_id": device_id[:15] + "...",
            "preferences": preferences,
            "device_info": {
                "browser_name": subscription.get("browser_name", "unknown"),
                "platform": subscription.get("platform", "unknown"),
                "created_at": subscription.get("created_at")
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to get device preferences")


@router.put("/devices/{device_id}/preferences")
async def update_device_notification_preferences(
    device_id: str,
    preferences: NotificationPreferences,
    user: dict = Depends(require_auth_hybrid)
):
    """Update notification preferences for a specific device"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify device ownership
        subscription = await redis_store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Update preferences
        preferences_dict = preferences.dict()
        success = await redis_store.update_device_notification_preferences(device_id, preferences_dict)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update preferences")

        logger.info(f"Updated notification preferences for device {device_id[:15]}... by user {user.get('email')}")

        return JSONResponse({
            "success": True,
            "message": "Notification preferences updated successfully",
            "device_id": device_id[:15] + "...",
            "preferences": preferences_dict
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating device preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update device preferences")


@router.delete("/devices/{device_id}")
async def remove_device_subscription(
    device_id: str,
    user: dict = Depends(require_auth_hybrid)
):
    """Remove push notification subscription for a specific device"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify ownership of device
        subscription = await redis_store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device subscription not found")

        # Check if the subscription belongs to the current user
        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Delete device subscription
        success = await redis_store.delete_device_push_subscription(device_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to remove device subscription")

        logger.info(f"Device {device_id[:15]}... removed by user {user.get('email')}")

        return JSONResponse({
            "success": True,
            "message": f"Successfully removed device subscription ({subscription.get('browser_name', 'unknown')})",
            "device_id": device_id[:15] + "..."
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing device subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove device subscription")


@router.delete("/unsubscribe-session")
async def unsubscribe_session(
    request: Request,
    user: dict = Depends(require_auth_hybrid)
):
    """Unsubscribe all notifications for the current session"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get session ID from request
    session_id = get_session_id_from_request(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Valid session required")

    try:
        # Clean up all subscriptions for this session
        cleaned_count = await redis_store.cleanup_session_subscriptions(session_id)

        logger.info(
            f"Session {session_id[:8]}... for user {user.get('email')} unsubscribed {cleaned_count} notifications")

        return JSONResponse({
            "success": True,
            "message": f"Successfully unsubscribed {cleaned_count} notifications for this session",
            "count": cleaned_count
        })

    except Exception as e:
        logger.error(f"Error unsubscribing session: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe session")


@router.get("/health")
async def check_notifications_health(
    request: Request,
    user: dict = Depends(require_auth_hybrid)
):
    """Check the health of push notification subscriptions for debugging"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get session ID from request
    session_id = get_session_id_from_request(request)

    try:
        # Get session subscriptions
        session_subscriptions = await redis_store.get_session_push_subscriptions(session_id) if session_id else []

        # Get all user subscriptions
        all_user_subscriptions = await redis_store.get_user_push_subscriptions(user_id)

        # Analyze subscriptions by browser
        browser_analysis = {}
        for sub in all_user_subscriptions:
            endpoint = sub.get("endpoint", "")
            if "fcm.googleapis.com" in endpoint:
                browser = "Chrome/Chromium"
            elif "mozilla.com" in endpoint:
                browser = "Firefox"
            elif "push.apple.com" in endpoint:
                browser = "Safari"
            elif "wns.windows.com" in endpoint:
                browser = "Edge"
            else:
                browser = "Unknown"

            if browser not in browser_analysis:
                browser_analysis[browser] = {
                    "count": 0,
                    "recent": 0,
                    "old": 0
                }

            browser_analysis[browser]["count"] += 1

            # Check age of subscription
            created_at = sub.get("created_at")
            if created_at:
                import time
                try:
                    # Handle both string timestamps and float timestamps
                    created_timestamp = float(created_at) if isinstance(created_at, (int, float, str)) else time.time()
                    age_days = (time.time() - created_timestamp) / (24 * 3600)
                    if age_days < 7:
                        browser_analysis[browser]["recent"] += 1
                    else:
                        browser_analysis[browser]["old"] += 1
                except (ValueError, TypeError):
                    # If conversion fails, consider it an old subscription
                    browser_analysis[browser]["old"] += 1
                    logger.warning(f"Invalid created_at timestamp format: {created_at}")

        return JSONResponse({
            "vapid_configured": settings.validate_vapid_config(),
            "session_id": session_id[:8] + "..." if session_id else None,
            "current_session_subscriptions": len(session_subscriptions),
            "total_user_subscriptions": len(all_user_subscriptions),
            "browser_breakdown": browser_analysis,
            "session_subscriptions_details": [
                {
                    "subscription_id": sub.get("subscription_id"),
                    "browser": "Chrome" if "fcm.googleapis.com" in sub.get("endpoint", "") else "Other",
                    "created_at": sub.get("created_at"),
                    "last_used": sub.get("last_used"),
                    "endpoint_domain": sub.get("endpoint", "").split("/")[2] if sub.get("endpoint") else "unknown"
                }
                for sub in session_subscriptions
            ]
        })

    except Exception as e:
        logger.error(f"Error checking notifications health: {e}")
        raise HTTPException(status_code=500, detail="Failed to check notifications health")


@router.post("/validate-subscriptions")
async def validate_subscriptions(
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Validate all subscriptions for the current user and clean up invalid ones"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Get all user subscriptions
        all_subscriptions = await redis_store.get_user_push_subscriptions(user_id)

        if not all_subscriptions:
            return JSONResponse({
                "success": True,
                "message": "No subscriptions to validate",
                "total": 0,
                "validated": 0,
                "removed": 0
            })

        # Send a silent validation notification to each subscription
        validation_payload = {
            "title": "🔍 Validating notifications...",
            "body": "This is a silent test to validate your notification subscription",
            "silent": True,
            "tag": "validation_test"
        }

        # Track validation results
        background_tasks.add_task(
            validate_subscriptions_background,
            all_subscriptions,
            validation_payload,
            redis_store,
            user.get("email", "unknown")
        )

        return JSONResponse({
            "success": True,
            "message": f"Validation started for {len(all_subscriptions)} subscription(s)",
            "total": len(all_subscriptions),
            "note": "Invalid subscriptions will be automatically cleaned up"
        })

    except Exception as e:
        logger.error(f"Error validating subscriptions: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate subscriptions")


@router.post("/test")
async def send_test_notification(
    payload: NotificationPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Send a test notification to the current session's devices"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get session ID from request
    session_id = get_session_id_from_request(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Valid session required")

    # Get current session's subscriptions
    subscriptions = await redis_store.get_session_push_subscriptions(session_id)
    if not subscriptions:
        raise HTTPException(
            status_code=400,
            detail="No push subscriptions found for this session. Please enable notifications first."
        )

    # Send notification in background
    background_tasks.add_task(
        send_push_notification_to_subscriptions,
        subscriptions,
        payload.dict(),
        redis_store
    )

    return JSONResponse({
        "success": True,
        "message": f"Test notification queued for {len(subscriptions)} device(s) in this session",
        "devices": len(subscriptions)
    })


async def send_welcome_notification(subscription: WebPushSubscription):
    """Send a welcome notification to a new subscriber"""
    try:
        wp = settings.get_webpush_instance()
        
        # Create a proper JSON notification payload
        welcome_payload = {
            "title": "🧗‍♂️ Welcome!",
            "body": "You're subscribed to climbing notifications",
            "icon": "/static/favicon/android-chrome-192x192.png",
            "badge": "/static/favicon/favicon-32x32.png",
            "tag": "welcome",
            "requireInteraction": False,
            "data": {
                "url": "/"
            }
        }
        
        message = wp.get(
            message=json.dumps(welcome_payload),
            subscription=subscription
        )

        async with aiohttp.ClientSession() as session:
            await session.post(
                url=str(subscription.endpoint),
                data=message.encrypted,
                headers={k: str(v) for k, v in message.headers.items()},
            )

        logger.info("Welcome notification sent successfully")

    except Exception as e:
        logger.error(f"Failed to send welcome notification: {e}")


async def validate_subscriptions_background(
    subscriptions: List[Dict[str, Any]],
    validation_payload: Dict[str, Any],
    redis_store,
    user_email: str
):
    """
    Validate subscriptions in the background by sending silent notifications
    and cleaning up any that return 410/404 errors.
    """
    if not settings.validate_vapid_config():
        logger.error("Cannot validate subscriptions: VAPID keys not configured")
        return

    try:
        wp = settings.get_webpush_instance()
        valid_count = 0
        invalid_count = 0
        error_count = 0

        async with aiohttp.ClientSession() as session:
            for subscription in subscriptions:
                try:
                    # Convert to WebPushSubscription
                    webpush_subscription = WebPushSubscription(
                        endpoint=AnyHttpUrl(subscription["endpoint"]),
                        keys=WebPushKeys(
                            p256dh=subscription["keys"]["p256dh"],
                            auth=subscription["keys"]["auth"]
                        )
                    )

                    # Get encrypted message
                    message = wp.get(
                        message=json.dumps(validation_payload),
                        subscription=webpush_subscription
                    )

                    # Send the validation notification
                    async with session.post(
                        url=str(webpush_subscription.endpoint),
                        data=message.encrypted,
                        headers={k: str(v) for k, v in message.headers.items()},
                    ) as response:
                        if response.status in [200, 201]:
                            valid_count += 1
                            # Update last used timestamp
                            subscription_id = subscription.get("subscription_id")
                            if subscription_id:
                                await redis_store.update_subscription_last_used(subscription_id)

                        elif response.status in [404, 410]:
                            invalid_count += 1
                            endpoint_domain = subscription["endpoint"].split(
                                "/")[2] if subscription.get("endpoint") else "unknown"
                            subscription_id = subscription.get("subscription_id")
                            session_id = subscription.get("session_id", "unknown")[:8]

                            logger.info(
                                f"Validation found invalid subscription ({response.status}) for {endpoint_domain} (session: {session_id}...)")

                            if subscription_id:
                                await redis_store.delete_push_subscription(subscription_id)
                                logger.info(f"Cleaned up invalid subscription during validation: {subscription_id}")

                        else:
                            error_count += 1
                            logger.warning(f"Validation failed with status {response.status}")

                except Exception as e:
                    error_count += 1
                    logger.error(f"Error validating subscription: {e}")

        logger.info(
            f"Subscription validation complete for {user_email}: {valid_count} valid, {invalid_count} removed, {error_count} errors")

    except Exception as e:
        logger.error(f"Error in validate_subscriptions_background: {e}")


async def send_push_notification_to_subscriptions(
    subscriptions: List[Dict[str, Any]],
    notification_data: Dict[str, Any],
    redis_store
):
    """
    Send push notification to a list of subscriptions.
    This runs in the background to avoid blocking the API response.
    """
    if not settings.validate_vapid_config():
        logger.error("Cannot send push notification: VAPID keys not configured")
        return

    try:
        wp = settings.get_webpush_instance()
        successful_sends = 0
        failed_sends = 0

        async with aiohttp.ClientSession() as session:
            for subscription in subscriptions:
                try:
                    # Convert to WebPushSubscription
                    webpush_subscription = WebPushSubscription(
                        endpoint=AnyHttpUrl(subscription["endpoint"]),
                        keys=WebPushKeys(
                            p256dh=subscription["keys"]["p256dh"],
                            auth=subscription["keys"]["auth"]
                        )
                    )

                    # Get encrypted message
                    message = wp.get(
                        message=json.dumps(notification_data),
                        subscription=webpush_subscription
                    )

                    # Send the notification
                    async with session.post(
                        url=str(webpush_subscription.endpoint),
                        data=message.encrypted,
                        headers={k: str(v) for k, v in message.headers.items()},
                    ) as response:
                        if response.status == 200 or response.status == 201:
                            successful_sends += 1

                            # Update last used timestamp
                            subscription_id = subscription.get("subscription_id")
                            if subscription_id:
                                await redis_store.update_subscription_last_used(subscription_id)

                            logger.debug(f"Push notification sent successfully to {subscription['endpoint'][:50]}...")
                        else:
                            failed_sends += 1
                            endpoint_domain = subscription["endpoint"].split(
                                "/")[2] if subscription.get("endpoint") else "unknown"

                            # Handle different error codes with specific logging
                            if response.status == 410:
                                # Subscription is no longer valid
                                subscription_id = subscription.get("subscription_id")
                                session_id = subscription.get("session_id", "unknown")[:8]
                                logger.warning(
                                    f"Push subscription expired (410) for {endpoint_domain} (session: {session_id}...)")

                                if subscription_id:
                                    await redis_store.delete_push_subscription(subscription_id)
                                    logger.info(f"Cleaned up expired subscription: {subscription_id}")

                            elif response.status == 404:
                                # Endpoint not found
                                subscription_id = subscription.get("subscription_id")
                                session_id = subscription.get("session_id", "unknown")[:8]
                                logger.warning(
                                    f"Push endpoint not found (404) for {endpoint_domain} (session: {session_id}...)")

                                if subscription_id:
                                    await redis_store.delete_push_subscription(subscription_id)
                                    logger.info(f"Cleaned up invalid subscription: {subscription_id}")

                            elif response.status == 413:
                                # Payload too large
                                logger.warning(f"Push notification payload too large (413) for {endpoint_domain}")

                            elif response.status == 429:
                                # Rate limited
                                logger.warning(f"Push notification rate limited (429) for {endpoint_domain}")

                            else:
                                # Other error
                                logger.warning(
                                    f"Push notification failed with status {response.status} for {endpoint_domain}")

                except Exception as e:
                    failed_sends += 1
                    logger.error(f"Unexpected error sending push notification: {e}")

        logger.info(f"Push notification batch complete: {successful_sends} successful, {failed_sends} failed")

    except Exception as e:
        logger.error(f"Error in send_push_notification_to_subscriptions: {e}")


# Utility function to send notifications for specific events
async def send_notification_for_event(
    event_type: str,
    event_data: Dict[str, Any],
    redis_store,
    target_users: Optional[List[str]] = None
):
    """
    Send notifications for specific app events (new album, new crew member, etc.)

    Args:
        event_type: Type of event (album_created, crew_added, etc.)
        event_data: Data about the event
        redis_store: Redis store instance
        target_users: Specific user IDs to notify (if None, notify all subscribed devices)
    """
    if not settings.validate_vapid_config():
        logger.warning("Skipping push notifications: VAPID not configured")
        return

    try:
        # Get relevant subscriptions (device-based)
        if target_users:
            all_subscriptions = []
            for user_id in target_users:
                user_device_subs = await redis_store.get_user_device_subscriptions(user_id)
                all_subscriptions.extend(user_device_subs)
        else:
            all_subscriptions = await redis_store.get_all_device_push_subscriptions()

        if not all_subscriptions:
            logger.debug(f"No device subscriptions found for event {event_type}")
            return

        # Create notification payload based on event type
        notification_payload = create_notification_payload(event_type, event_data)

        if notification_payload:
            # Filter subscriptions based on their notification preferences
            filtered_subscriptions = []
            for subscription in all_subscriptions:
                preferences_json = subscription.get("notification_preferences", "{}")
                try:
                    preferences = json.loads(preferences_json)
                    # Check if this device wants this type of notification
                    if preferences.get(event_type, True):  # Default to True if preference not set
                        filtered_subscriptions.append(subscription)
                    else:
                        logger.debug(
                            f"Skipping {event_type} notification for device {subscription.get('device_id', 'unknown')[:15]}... (disabled by user)")
                except json.JSONDecodeError:
                    # If preferences can't be parsed, send notification (fail-safe)
                    filtered_subscriptions.append(subscription)

            if filtered_subscriptions:
                # Send notifications in background
                await send_push_notification_to_subscriptions(
                    filtered_subscriptions,
                    notification_payload,
                    redis_store
                )
                logger.info(
                    f"Sent {event_type} notifications to {len(filtered_subscriptions)}/{len(all_subscriptions)} device subscriptions")
            else:
                logger.info(f"No devices opted in for {event_type} notifications")

    except Exception as e:
        # Don't let notification errors break the main functionality
        logger.error(f"Error sending event notification (non-critical): {e}")
        logger.info(f"Event {event_type} completed successfully despite notification failure")


def create_notification_payload(event_type: str, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create notification payload based on event type"""

    if event_type == "album_created":
        title = event_data.get("title", "New Album")
        crew = event_data.get("crew", [])
        crew_text = f" with {', '.join(crew[:4])}" if crew else ""
        if len(crew) > 2:
            crew_text += f" and {len(crew) - 2} others"

        # Use album cover image as notification icon if available
        image_url = event_data.get("image_url")
        icon = f"/get-image?url={image_url}" if image_url else "/static/favicon/android-chrome-192x192.png"

        return {
            "title": f"🧗‍♂️ New Album: {title}",
            "body": f"{crew_text}",
            "icon": icon,
            "badge": "/static/favicon/favicon-32x32.png",
            "tag": "album_created",
            "requireInteraction": False,
            "data": {
                "url": "/albums",
                "album_url": event_data.get("url")
            }
        }

    elif event_type == "crew_member_added":
        name = event_data.get("name", "New member")

        # Use crew member's image as notification icon if available
        image_url = event_data.get("image_url")
        icon = image_url if image_url else "/static/favicon/android-chrome-192x192.png"

        return {
            "title": f"👋 {name} Has joined the crew!",
            "body": f"Welcome {name} to the climbing crew!",
            "icon": icon,
            "badge": "/static/favicon/favicon-32x32.png",
            "tag": "crew_added",
            "requireInteraction": False,
            "data": {
                "url": "/crew",
                "crew_member": name
            }
        }

    elif event_type == "meme_uploaded":
        creator = event_data.get("creator", "Someone")
        return {
            "title": "😂 New Meme Alert!",
            "body": f"{creator} shared a new climbing meme",
            "icon": "/static/favicon/android-chrome-192x192.png",
            "badge": "/static/favicon/favicon-32x32.png",
            "tag": "meme_uploaded",
            "requireInteraction": False,
            "data": {
                "url": "/memes",
                "meme_id": event_data.get("meme_id")
            }
        }

    return None
