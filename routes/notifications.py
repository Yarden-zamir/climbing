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


class NotificationPayload(BaseModel):
    """Notification payload for testing"""
    title: str
    body: str
    icon: Optional[str] = None
    badge: Optional[str] = None
    tag: Optional[str] = None
    requireInteraction: Optional[bool] = False
    actions: Optional[List[Dict[str, str]]] = None
    data: Optional[Dict[str, Any]] = None


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Get the VAPID public key for client-side subscription"""
    try:
        raw_public_key = settings.get_raw_public_key()
        if not raw_public_key:
            raise HTTPException(
                status_code=503,
                detail="Push notifications not configured"
            )

        return JSONResponse({
            "publicKey": raw_public_key
        })
    except Exception as e:
        logger.error(f"Error getting VAPID public key: {e}")
        raise HTTPException(
            status_code=503,
            detail="Push notification service unavailable"
        )


@router.post("/subscribe")
async def subscribe_to_notifications(
    subscription: PushSubscriptionData,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Subscribe user to push notifications"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Convert to WebPushSubscription format (dict)
        webpush_subscription = WebPushSubscription(
            endpoint=subscription.endpoint,
            keys={
                "p256dh": subscription.keys.p256dh,
                "auth": subscription.keys.auth
            }
        )

        # Convert to dict for Redis storage
        subscription_data = {
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.keys.p256dh,
                "auth": subscription.keys.auth
            },
            "expirationTime": subscription.expirationTime
        }

        # Store subscription in Redis
        subscription_id = await redis_store.store_push_subscription(user_id, subscription_data)

        # Send welcome notification in background
        background_tasks.add_task(
            send_welcome_notification,
            webpush_subscription
        )

        logger.info(f"User {user.get('email')} subscribed to push notifications")

        return JSONResponse({
            "success": True,
            "subscription_id": subscription_id,
            "message": "Successfully subscribed to notifications"
        })

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error subscribing to notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to subscribe to notifications")


@router.get("/subscriptions")
async def get_user_subscriptions(user: dict = Depends(require_auth_hybrid)):
    """Get all push subscriptions for the current user"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        subscriptions = await redis_store.get_user_push_subscriptions(user_id)

        # Remove sensitive data before returning
        safe_subscriptions = []
        for sub in subscriptions:
            safe_sub = {
                "subscription_id": sub.get("subscription_id"),
                "created_at": sub.get("created_at"),
                "last_used": sub.get("last_used"),
                "expirationTime": sub.get("expirationTime"),
                "endpoint_domain": sub.get("endpoint", "").split("/")[2] if sub.get("endpoint") else "unknown"
            }
            safe_subscriptions.append(safe_sub)

        return JSONResponse({
            "subscriptions": safe_subscriptions,
            "count": len(safe_subscriptions)
        })

    except Exception as e:
        logger.error(f"Error getting user subscriptions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get subscriptions")


@router.delete("/unsubscribe/{subscription_id}")
async def unsubscribe_from_notifications(
    subscription_id: str,
    user: dict = Depends(require_auth_hybrid)
):
    """Unsubscribe from push notifications"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Verify ownership of subscription
        subscription = await redis_store.get_push_subscription(subscription_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        if subscription.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Delete subscription
        success = await redis_store.delete_push_subscription(subscription_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to unsubscribe")

        logger.info(f"User {user.get('email')} unsubscribed from push notifications")

        return JSONResponse({
            "success": True,
            "message": "Successfully unsubscribed from notifications"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing from notifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe")


@router.post("/test")
async def send_test_notification(
    payload: NotificationPayload,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid)
):
    """Send a test notification to the current user's devices"""
    redis_store = get_redis_store()

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get user's subscriptions
    subscriptions = await redis_store.get_user_push_subscriptions(user_id)
    if not subscriptions:
        raise HTTPException(
            status_code=400,
            detail="No push subscriptions found. Please enable notifications first."
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
        "message": f"Test notification queued for {len(subscriptions)} device(s)",
        "devices": len(subscriptions)
    })


async def send_welcome_notification(subscription: WebPushSubscription):
    """Send a welcome notification to a new subscriber"""
    try:
        wp = settings.get_webpush_instance()
        message = wp.get(
            message="Welcome! You're subscribed to climbing notifications 🧗‍♂️",
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
                        endpoint=subscription["endpoint"],
                        keys={
                            "p256dh": subscription["keys"]["p256dh"],
                            "auth": subscription["keys"]["auth"]
                        }
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
                            logger.warning(f"Push notification failed with status {response.status}")

                            # If subscription is invalid (410/404), remove it
                            if response.status in [404, 410]:
                                subscription_id = subscription.get("subscription_id")
                                if subscription_id:
                                    await redis_store.delete_push_subscription(subscription_id)
                                    logger.info(f"Removed invalid subscription: {subscription_id}")

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
        target_users: Specific user IDs to notify (if None, notify all subscribed users)
    """
    if not settings.validate_vapid_config():
        logger.warning("Skipping push notifications: VAPID not configured")
        return

    try:
        # Get relevant subscriptions
        if target_users:
            all_subscriptions = []
            for user_id in target_users:
                user_subs = await redis_store.get_user_push_subscriptions(user_id)
                all_subscriptions.extend(user_subs)
        else:
            all_subscriptions = await redis_store.get_all_push_subscriptions()

        if not all_subscriptions:
            logger.debug(f"No subscriptions found for event {event_type}")
            return

        # Create notification payload based on event type
        notification_payload = create_notification_payload(event_type, event_data)

        if notification_payload:
            # Send notifications in background
            await send_push_notification_to_subscriptions(
                all_subscriptions,
                notification_payload,
                redis_store
            )
            logger.info(f"Sent {event_type} notifications to {len(all_subscriptions)} subscriptions")

    except Exception as e:
        # Don't let notification errors break the main functionality
        logger.error(f"Error sending event notification (non-critical): {e}")
        logger.info(f"Event {event_type} completed successfully despite notification failure")


def create_notification_payload(event_type: str, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create notification payload based on event type"""

    if event_type == "album_created":
        title = event_data.get("title", "New Album")
        crew = event_data.get("crew", [])
        crew_text = f" with {', '.join(crew[:2])}" if crew else ""
        if len(crew) > 2:
            crew_text += f" and {len(crew) - 2} others"

        return {
            "title": "🧗‍♂️ New Climbing Album!",
            "body": f"{title}{crew_text}",
            "icon": "/static/favicon/android-chrome-192x192.png",
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
        return {
            "title": "👋 New Crew Member!",
            "body": f"Welcome {name} to the climbing crew!",
            "icon": "/static/favicon/android-chrome-192x192.png",
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
