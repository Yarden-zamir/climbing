import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import quote, urlparse
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError as PydanticValidationError
import aiohttp

from auth import get_current_user_hybrid, require_auth_hybrid
from dependencies import get_store
from config import settings
from store import ValidationError
from webpush import WebPushSubscription
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


def require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def to_webpush_subscription(endpoint: str, keys: Dict[str, str]) -> WebPushSubscription:
    return WebPushSubscription(
        endpoint=AnyHttpUrl(endpoint),
        keys=WebPushKeys(p256dh=keys["p256dh"], auth=keys["auth"])
    )


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
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Validate VAPID configuration
    if not settings.validate_vapid_config():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    # User can be None for anonymous subscriptions
    user_id = user.get("id") if user else None
    device_id = request_data.deviceInfo.deviceId

    # Validate device ID
    if not device_id or len(device_id) < 10:
        raise HTTPException(status_code=400, detail="Valid device ID required")

    if not request_data.subscription.endpoint:
        raise HTTPException(status_code=400, detail="Subscription endpoint required")

    if not request_data.subscription.keys.p256dh or not request_data.subscription.keys.auth:
        raise HTTPException(status_code=400, detail="Subscription keys (p256dh, auth) required")

    try:
        webpush_subscription = to_webpush_subscription(
            request_data.subscription.endpoint,
            {"p256dh": request_data.subscription.keys.p256dh, "auth": request_data.subscription.keys.auth}
        )
    except PydanticValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid push subscription: {e}")

    try:
        # Convert subscription to dict for storage
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
            "browserName": request_data.deviceInfo.browserName or "unknown",
            "platform": request_data.deviceInfo.platform or "unknown",
            "userAgent": request_data.deviceInfo.userAgent or "",
            "lastActive": request_data.deviceInfo.lastActive or datetime.now().isoformat()
        }

        background_tasks.add_task(test_subscription_validity, webpush_subscription)

        # Store subscription with device ID
        subscription_id = await store.store_push_subscription(device_id, user_id, subscription_data, device_info)

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

    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error subscribing to notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to subscribe to notifications")


async def test_subscription_validity(subscription: WebPushSubscription):
    """Test if a subscription is valid by sending a silent notification"""
    try:
        wp = settings.get_webpush_instance()

        test_payload = {
            "title": "Test",
            "body": "Subscription validation",
            "silent": True,
            "tag": "validation"
        }

        message = wp.get(
            message=json.dumps(test_payload),
            subscription=subscription
        )

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url=str(subscription.endpoint),
                data=message.encrypted,
                headers={k: str(v) for k, v in message.headers.items()},
            ) as response:
                if response.status not in [200, 201]:
                    logger.warning(f"Subscription validation failed with status {response.status}")
                else:
                    logger.debug("Subscription validation successful")

    except Exception as e:
        logger.warning(f"Subscription validation test failed: {e}")


@router.get("/subscriptions")
async def get_current_device_subscription(
    request: Request,
    user: dict = Depends(get_current_user_hybrid)
):
    """Get push subscription for the current device"""
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Extract device ID from request headers or cookies
    device_id = request.headers.get("X-Device-ID")
    if not device_id:
        return JSONResponse({
            "subscription": None,
            "message": "No device ID provided"
        })

    try:
        subscription = await store.get_device_push_subscription(device_id)

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
            if subscription.get("endpoint") else "unknown", "user_associated": subscription.get("user_id") is not None,
            "needs_user_association": bool(user) and subscription.get("user_id") != user.get("id")}

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
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        device_subscriptions = await store.get_user_device_subscriptions(user_id)

        # Remove sensitive data before returning
        safe_devices = []
        for sub in device_subscriptions:
            preferences = sub.get("notification_preferences") or {}

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
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify device ownership
        subscription = await store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Get preferences
        preferences = await store.get_device_notification_preferences(device_id)

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
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify device ownership
        subscription = await store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Update preferences
        preferences_dict = preferences.model_dump()
        success = await store.update_device_notification_preferences(device_id, preferences_dict)

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
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify ownership of device
        subscription = await store.get_device_push_subscription(device_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Device subscription not found")

        # Check if the subscription belongs to the current user
        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied - device belongs to another user")

        # Delete device subscription
        success = await store.delete_device_push_subscription(device_id)
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


BROWSER_BY_ENDPOINT_HOST = {
    "fcm.googleapis.com": "Chrome/Chromium",
    "mozilla.com": "Firefox",
    "push.apple.com": "Safari",
    "wns.windows.com": "Edge",
}


def browser_from_endpoint(endpoint: str) -> str:
    for host, browser in BROWSER_BY_ENDPOINT_HOST.items():
        if host in endpoint:
            return browser
    return "Unknown"


def age_seconds(iso_timestamp: Optional[str]) -> Optional[float]:
    if not iso_timestamp:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(iso_timestamp)).total_seconds()
    except (ValueError, TypeError):
        logger.warning(f"Invalid ISO timestamp: {iso_timestamp}")
        return None


def wants_notification(subscription: Dict[str, Any], event_type: str) -> bool:
    preferences = subscription.get("notification_preferences") or {}
    return preferences.get(event_type, True)


@router.get("/health")
async def check_notifications_health(user: dict = Depends(require_auth_hybrid)):
    """Check the health of push notification subscriptions for debugging"""
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        subscriptions = await store.get_user_device_subscriptions(user_id)

        browser_analysis: Dict[str, Dict[str, int]] = {}
        for sub in subscriptions:
            browser = browser_from_endpoint(sub.get("endpoint", ""))
            stats = browser_analysis.setdefault(browser, {"count": 0, "recent": 0, "old": 0})
            stats["count"] += 1
            age = age_seconds(sub.get("created_at"))
            if age is not None and age < 7 * 24 * 3600:
                stats["recent"] += 1
            else:
                stats["old"] += 1

        return JSONResponse({
            "vapid_configured": settings.validate_vapid_config(),
            "total_user_subscriptions": len(subscriptions),
            "browser_breakdown": browser_analysis,
            "subscriptions_details": [
                {
                    "subscription_id": sub.get("subscription_id"),
                    "device_id": sub.get("device_id", "unknown")[:15] + "...",
                    "browser": browser_from_endpoint(sub.get("endpoint", "")),
                    "created_at": sub.get("created_at"),
                    "last_used": sub.get("last_used"),
                    "endpoint_domain": sub.get("endpoint", "").split("/")[2] if sub.get("endpoint") else "unknown"
                }
                for sub in subscriptions
            ]
        })

    except Exception as e:
        logger.error(f"Error checking notifications health: {e}")
        raise HTTPException(status_code=500, detail="Failed to check notifications health")


@router.get("/admin/stats")
async def get_notification_stats(user: dict = Depends(require_auth_hybrid)):
    """Get comprehensive notification statistics for admin panel"""
    require_admin(user)
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        all_subscriptions = await store.get_all_device_push_subscriptions()

        browser_stats: Dict[str, int] = {}
        platform_stats: Dict[str, int] = {}
        user_stats: Dict[str, int] = {}
        anonymous_subscriptions = 0
        healthy_subscriptions = 0
        stale_subscriptions = 0

        for sub in all_subscriptions:
            browser = browser_from_endpoint(sub.get("endpoint", ""))
            browser_stats[browser] = browser_stats.get(browser, 0) + 1

            platform = sub.get("platform", "unknown")
            platform_stats[platform] = platform_stats.get(platform, 0) + 1

            user_id_sub = sub.get("user_id")
            if user_id_sub:
                user_stats[user_id_sub] = user_stats.get(user_id_sub, 0) + 1
            else:
                anonymous_subscriptions += 1

            age = age_seconds(sub.get("last_used"))
            if age is None:
                continue
            if age < 24 * 3600:
                healthy_subscriptions += 1
            elif age > 7 * 24 * 3600:
                stale_subscriptions += 1

        return JSONResponse({
            "device_subscriptions": {
                "total": len(all_subscriptions),
                "healthy": healthy_subscriptions,
                "stale": stale_subscriptions,
                "by_browser": browser_stats,
                "by_platform": platform_stats
            },
            "user_stats": {
                "users_with_notifications": len(user_stats),
                "avg_devices_per_user": sum(user_stats.values()) / len(user_stats) if user_stats else 0,
                "anonymous_subscriptions": anonymous_subscriptions
            },
            "browser_distribution": browser_stats,
            "vapid_configured": settings.validate_vapid_config(),
            "generated_at": datetime.now().timestamp()
        })

    except Exception as e:
        logger.error(f"Error getting notification stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get notification stats")


@router.get("/admin/reliability")
async def get_notification_reliability(
    days: int = 7,
    user: dict = Depends(require_auth_hybrid)
):
    """Send success and failure counts per day, from counters written by send_push_notification_to_subscriptions"""
    require_admin(user)
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    days = max(1, min(days, 90))

    try:
        daily_breakdown = []
        for counters in await store.get_notification_counters(days):
            sent, failed, cleaned = counters["sent"], counters["failed"], counters["cleaned"]
            attempts = sent + failed
            daily_breakdown.append({
                "date": counters["date"],
                "attempts": attempts,
                "successful": sent,
                "failed": failed,
                "cleaned": cleaned,
                "rate": (sent / attempts * 100) if attempts else None
            })

        successful_sends = sum(d["successful"] for d in daily_breakdown)
        failed_sends = sum(d["failed"] for d in daily_breakdown)
        total_attempts = successful_sends + failed_sends

        return JSONResponse({
            "period_days": days,
            "total_attempts": total_attempts,
            "successful_sends": successful_sends,
            "failed_sends": failed_sends,
            "cleaned_subscriptions": sum(d["cleaned"] for d in daily_breakdown),
            "reliability_percentage": (successful_sends / total_attempts * 100) if total_attempts else None,
            "daily_breakdown": daily_breakdown
        })

    except Exception as e:
        logger.error(f"Error getting reliability stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get reliability stats")


@router.post("/admin/broadcast")
async def broadcast_notification(
    notification_data: NotificationPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Send a broadcast notification to all subscribers that allow system announcements (admin only)"""
    require_admin(user)
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        all_subscriptions = await store.get_all_device_push_subscriptions()
        recipients = [sub for sub in all_subscriptions if wants_notification(sub, "system_announcements")]

        if not recipients:
            raise HTTPException(status_code=404, detail="No subscriptions accept system announcements")

        broadcast_payload = {
            **notification_data.model_dump(),
            "tag": f"admin_broadcast_{int(datetime.now().timestamp())}",
            "data": {
                **(notification_data.data or {}),
                "type": "admin_broadcast",
                "sender": user.get("name", "Admin"),
                "timestamp": datetime.now().isoformat()
            }
        }

        background_tasks.add_task(
            send_push_notification_to_subscriptions,
            recipients,
            broadcast_payload,
            store
        )

        logger.info(f"Admin broadcast queued by {user.get('email')} to {len(recipients)} devices")

        return JSONResponse({
            "success": True,
            "message": f"Broadcast notification queued for {len(recipients)} devices",
            "recipients": len(recipients),
            "payload": broadcast_payload
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending admin broadcast: {e}")
        raise HTTPException(status_code=500, detail="Failed to send broadcast notification")


@router.post("/validate-subscriptions")
async def validate_subscriptions(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Validate all device subscriptions for the current user and clean up invalid ones"""
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        all_subscriptions = await store.get_user_device_subscriptions(user_id)

        if not all_subscriptions:
            return JSONResponse({
                "success": True,
                "message": "No subscriptions to validate",
                "total": 0,
                "validated": 0,
                "removed": 0
            })

        validation_payload = {
            "title": "Validating notifications",
            "body": "Silent subscription validation",
            "silent": True,
            "tag": "validation_test"
        }

        background_tasks.add_task(
            validate_subscriptions_background,
            all_subscriptions,
            validation_payload,
            store,
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


class SubscriptionTestRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


@router.post("/test-subscription")
async def test_subscription_health(
    request_data: SubscriptionTestRequest,
    user: dict = Depends(require_auth_hybrid)
):
    """Send a silent push to one of the caller's own subscriptions. valid=false only on 404/410; other failures are 502."""
    if not settings.validate_vapid_config():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    store = get_store()
    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    own_subscriptions = await store.get_user_device_subscriptions(user.get("id"))
    if not any(sub.get("endpoint") == request_data.endpoint for sub in own_subscriptions):
        raise HTTPException(status_code=403, detail="Subscription does not belong to one of your devices")

    try:
        webpush_subscription = to_webpush_subscription(
            request_data.endpoint, {"p256dh": request_data.keys.p256dh, "auth": request_data.keys.auth}
        )
    except PydanticValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid push subscription: {e}")

    test_payload = {
        "title": "Health Check",
        "body": "Testing subscription validity",
        "silent": True,
        "tag": "health_check",
        "data": {"type": "health_check"}
    }
    endpoint_domain = urlparse(request_data.endpoint).netloc or "unknown"

    try:
        message = settings.get_webpush_instance().get(
            message=json.dumps(test_payload),
            subscription=webpush_subscription
        )

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url=str(webpush_subscription.endpoint),
                data=message.encrypted,
                headers={k: str(v) for k, v in message.headers.items()},
            ) as response:
                status = response.status
    except Exception as e:
        logger.error(f"Subscription health test error for {endpoint_domain}: {e}")
        raise HTTPException(status_code=502, detail="Push service unreachable")

    if status in (200, 201):
        return JSONResponse({"valid": True, "status": status, "endpoint_domain": endpoint_domain})
    if status in (404, 410):
        logger.info(f"Subscription health test: subscription gone ({status}) for {endpoint_domain}")
        return JSONResponse({"valid": False, "status": status, "endpoint_domain": endpoint_domain})

    logger.warning(f"Subscription health test: push service returned {status} for {endpoint_domain}")
    raise HTTPException(status_code=502, detail=f"Push service returned {status}")


@router.post("/test")
async def send_test_notification(
    payload: NotificationPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Send a test notification to the calling device, or to all of the user's devices when no X-Device-ID is sent"""
    store = get_store()

    if not store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    subscriptions: List[Dict[str, Any]] = []
    device_id = request.headers.get("X-Device-ID")
    if device_id:
        device_subscription = await store.get_device_push_subscription(device_id)
        if device_subscription and device_subscription.get("user_id") == user_id:
            subscriptions = [device_subscription]
    if not subscriptions:
        subscriptions = await store.get_user_device_subscriptions(user_id)
    if not subscriptions:
        raise HTTPException(
            status_code=400,
            detail="No push subscriptions found for your devices. Please enable notifications first."
        )

    test_payload = {**payload.model_dump(), "tag": f"test_{int(datetime.now().timestamp())}"}

    background_tasks.add_task(
        send_push_notification_to_subscriptions,
        subscriptions,
        test_payload,
        store
    )

    return JSONResponse({
        "success": True,
        "message": f"Test notification queued for {len(subscriptions)} device(s)",
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
    store,
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
                                await store.update_subscription_last_used(subscription_id)

                        elif response.status in [404, 410]:
                            invalid_count += 1
                            endpoint_domain = subscription["endpoint"].split(
                                "/")[2] if subscription.get("endpoint") else "unknown"
                            subscription_id = subscription.get("subscription_id")

                            logger.info(
                                f"Validation found invalid subscription ({response.status}) for {endpoint_domain}")

                            if subscription_id:
                                await store.delete_push_subscription(subscription_id)
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
    store
):
    """
    Send push notification to a list of subscriptions.
    This runs in the background to avoid blocking the API response.
    """
    if not settings.validate_vapid_config():
        logger.error("Cannot send push notification: VAPID keys not configured")
        return

    if not subscriptions:
        logger.warning("No subscriptions provided for notification sending")
        return

    try:
        wp = settings.get_webpush_instance()
        successful_sends = 0
        failed_sends = 0
        cleaned_subscriptions = 0

        # Validate and optimize payload before sending
        optimized_payload = optimize_notification_payload(notification_data)
        payload_json = json.dumps(optimized_payload)
        payload_size = len(payload_json.encode('utf-8'))

        logger.debug(f"Optimized FCM payload size: {payload_size} bytes")
        
        # FCM has a 4KB limit, warn if we're getting close
        if payload_size > 3500:  # 3.5KB warning threshold
            logger.warning(f"Large FCM payload ({payload_size} bytes) - may cause delivery issues")
        
        if payload_size > 4000:  # 4KB hard limit
            logger.error(f"FCM payload too large ({payload_size} bytes) - truncating")
            # Fallback to minimal payload
            optimized_payload = {
                "title": notification_data.get("title", "Notification"),
                "body": notification_data.get("body", "")[:100],  # Truncate body
                "icon": "/static/favicon/android-chrome-192x192.png",
                "badge": "/static/favicon/favicon-32x32.png",
                "tag": notification_data.get("tag", "notification"),
                "data": {
                    "url": notification_data.get("data", {}).get("url", "/"),
                    "type": "truncated_notification"
                }
            }
            payload_json = json.dumps(optimized_payload)
            logger.info(f"Fallback payload size: {len(payload_json.encode('utf-8'))} bytes")

        # Set timeout for HTTP requests
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for subscription in subscriptions:
                try:
                    # Validate subscription data
                    endpoint = subscription.get("endpoint")
                    keys = subscription.get("keys", {})

                    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
                        logger.warning(
                            f"Invalid subscription data, skipping: {subscription.get('subscription_id', 'unknown')}")
                        failed_sends += 1
                        continue

                    # Convert to WebPushSubscription
                    webpush_subscription = WebPushSubscription(
                        endpoint=AnyHttpUrl(endpoint),
                        keys=WebPushKeys(
                            p256dh=keys["p256dh"],
                            auth=keys["auth"]
                        )
                    )

                    # Get encrypted message
                    message = wp.get(
                        message=payload_json,
                        subscription=webpush_subscription
                    )

                    # Send the notification with retries
                    for attempt in range(2):  # Try twice
                        try:
                            async with session.post(
                                url=str(webpush_subscription.endpoint),
                                data=message.encrypted,
                                headers={k: str(v) for k, v in message.headers.items()},
                            ) as response:
                                if response.status in [200, 201]:
                                    successful_sends += 1

                                    # Update last used timestamp
                                    subscription_id = subscription.get("subscription_id")
                                    if subscription_id:
                                        await store.update_subscription_last_used(subscription_id)

                                    logger.debug(f"Push notification sent successfully to {endpoint[:50]}...")
                                    break

                                elif response.status in [404, 410]:
                                    # Subscription is invalid - clean it up
                                    subscription_id = subscription.get("subscription_id")
                                    device_id = subscription.get("device_id")
                                    endpoint_domain = endpoint.split("/")[2] if "/" in endpoint else "unknown"

                                    logger.info(
                                        f"Invalid subscription ({response.status}) for {endpoint_domain}, cleaning up...")

                                    if subscription_id:
                                        await store.delete_push_subscription(subscription_id)
                                        cleaned_subscriptions += 1
                                        logger.info(f"Cleaned up invalid subscription: {subscription_id}")
                                    elif device_id:
                                        await store.delete_device_push_subscription(device_id)
                                        cleaned_subscriptions += 1
                                        logger.info(f"Cleaned up invalid device subscription: {device_id[:15]}...")

                                    failed_sends += 1
                                    break

                                elif response.status == 413:
                                    logger.warning(f"Push notification payload too large (413) for {endpoint[:50]}...")
                                    failed_sends += 1
                                    break

                                elif response.status == 429:
                                    logger.warning(
                                        f"Push notification rate limited (429) for {endpoint[:50]}..., retrying...")
                                    if attempt == 0:  # Only retry once for rate limiting
                                        await asyncio.sleep(1)  # Wait 1 second before retry
                                        continue
                                    failed_sends += 1
                                    break

                                else:
                                    # Log detailed error information for debugging FCM issues
                                    endpoint_domain = endpoint.split("/")[2] if "/" in endpoint else "unknown"
                                    
                                    # Try to get error response details
                                    error_text = ""
                                    try:
                                        error_text = await response.text()
                                    except:
                                        error_text = "Could not read error response"
                                    
                                    logger.warning(
                                        f"Push notification failed with status {response.status} for {endpoint_domain}")
                                    
                                    # Only log detailed error info on first attempt to avoid spam
                                    if attempt == 0:
                                        logger.warning(
                                            f"FCM Error Details - Status: {response.status}, "
                                            f"Payload size: {payload_size} bytes, "
                                            f"Response: {error_text[:200]}...")
                                    
                                    if attempt == 0:
                                        await asyncio.sleep(0.5)  # Brief retry for other errors
                                        continue
                                    failed_sends += 1
                                    break

                        except aiohttp.ClientError as e:
                            logger.warning(f"HTTP error sending notification (attempt {attempt + 1}): {e}")
                            if attempt == 0:
                                await asyncio.sleep(0.5)
                                continue
                            failed_sends += 1
                            break

                        except Exception as e:
                            logger.error(f"Unexpected error sending notification (attempt {attempt + 1}): {e}")
                            failed_sends += 1
                            break

                except Exception as e:
                    failed_sends += 1
                    logger.error(f"Error processing subscription: {e}")

        logger.info(
            f"Notification batch complete: {successful_sends} sent, {failed_sends} failed, {cleaned_subscriptions} cleaned up")
        try:
            await store.record_notification_counters(
                sent=successful_sends, failed=failed_sends, cleaned=cleaned_subscriptions
            )
        except Exception as e:
            logger.warning(f"Could not record notification counters: {e}")

    except Exception as e:
        logger.error(f"Critical error in send_push_notification_to_subscriptions: {e}")


def optimize_notification_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optimize notification payload for FCM delivery
    Remove or truncate large fields to stay under 4KB limit
    """
    optimized = payload.copy()
    
    # Truncate long text fields
    if "title" in optimized and len(optimized["title"]) > 100:
        optimized["title"] = optimized["title"][:97] + "..."
        
    if "body" in optimized and len(optimized["body"]) > 200:
        optimized["body"] = optimized["body"][:197] + "..."
    
    # Remove large data fields if payload is getting too big
    current_size = len(json.dumps(optimized).encode('utf-8'))
    
    if current_size > 3000:  # 3KB threshold for optimization
        # Remove non-essential data
        if "data" in optimized and "webNotificationFeatures" in optimized.get("data", {}):
            # Keep only essential data
            essential_data = {
                "url": optimized["data"].get("url", "/"),
                "type": optimized["data"].get("type", "notification"),
                "timestamp": optimized["data"].get("timestamp")
            }
            optimized["data"] = essential_data
            logger.debug("Removed advanced notification features to reduce payload size")
    
    return optimized


# Utility function to send notifications for specific events
async def send_notification_for_event(
    event_type: str,
    event_data: Dict[str, Any],
    store,
    target_users: Optional[List[str]] = None
):
    """
    Send notifications for specific app events (new album, new crew member, etc.)

    Args:
        event_type: Type of event (album_created, crew_added, etc.)
        event_data: Data about the event
        store: Store instance
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
                user_device_subs = await store.get_user_device_subscriptions(user_id)
                all_subscriptions.extend(user_device_subs)
        else:
            all_subscriptions = await store.get_all_device_push_subscriptions()

        if not all_subscriptions:
            logger.debug(f"No device subscriptions found for event {event_type}")
            return

        # Create notification payload based on event type
        notification_payload = create_notification_payload(event_type, event_data)

        if notification_payload:
            filtered_subscriptions = [sub for sub in all_subscriptions if wants_notification(sub, event_type)]

            if filtered_subscriptions:
                # Send notifications in background
                await send_push_notification_to_subscriptions(
                    filtered_subscriptions,
                    notification_payload,
                    store
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
        creator = event_data.get("creator", "Someone")
        crew = event_data.get("crew") or []
        shown = crew[:3]
        rest = len(crew) - len(shown)
        body = f"{creator} added an album"
        if shown:
            body += f" with {', '.join(shown)}"
            if rest:
                body += f" and {rest} more"

        image_url = event_data.get("image_url")
        icon = f"/get-image?url={quote(image_url, safe='')}&w=256" if image_url else "/static/favicon/android-chrome-192x192.png"
        album_url = event_data.get("url") or "/albums"

        return {
            "title": f"🧗‍♂️ New Album: {title}",
            "body": body,
            "icon": icon,
            "badge": "/static/favicon/favicon-32x32.png",
            "tag": f"album_created:{album_url}",
            "requireInteraction": False,
            "data": {
                "url": album_url
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
            "tag": f"crew_added:{name}",
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
            "tag": f"meme_uploaded:{event_data.get('meme_id')}",
            "requireInteraction": False,
            "data": {
                "url": "/memes",
                "meme_id": event_data.get("meme_id")
            }
        }

    return None
