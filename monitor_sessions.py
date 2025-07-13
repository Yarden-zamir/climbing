#!/usr/bin/env python3
"""
Script to monitor user sessions and show active users.
Usage: uv run python monitor_sessions.py
"""

import asyncio
import json
import logging
import time
from redis_store import RedisDataStore
from permissions import PermissionsManager

# Setup logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def format_user_info(session_data):
    """Format user session data for display"""
    try:
        user_info = json.loads(session_data)
        return {
            "name": user_info.get("name", "Unknown"),
            "email": user_info.get("email", "Unknown"),
            "role": user_info.get("role", "user"),
            "login_time": user_info.get("login_time", "Unknown")[:16]  # Just date and time
        }
    except:
        return {"name": "Invalid", "email": "Invalid", "role": "Invalid", "login_time": "Invalid"}


async def monitor_sessions():
    try:
        # Initialize Redis connection
        redis_store = RedisDataStore(host='localhost', port=6379)
        permissions_manager = PermissionsManager(redis_store)

        print("🔄 Session Monitor - Press Ctrl+C to stop")
        print("=" * 80)

        last_session_count = 0

        while True:
            try:
                # Get current sessions using safe access
                session_keys = []
                try:
                    all_keys = redis_store.redis.keys("session:*")
                    session_keys = [k for k in all_keys] if all_keys else []
                except Exception:
                    session_keys = []

                current_count = len(session_keys)

                # Show header periodically or when sessions change
                if current_count != last_session_count:
                    print(f"\n📊 Found {current_count} active sessions:")
                    print("-" * 80)
                    print(f"{'Name':<25} {'Email':<30} {'Role':<8} {'Login Time':<16}")
                    print("-" * 80)

                    # Get unique users (by email)
                    users_seen = set()
                    for session_key in session_keys:
                        try:
                            session_data = redis_store.redis.get(session_key)
                            if session_data:
                                user_info = format_user_info(session_data)
                                email = user_info["email"]

                                if email not in users_seen:
                                    users_seen.add(email)
                                    print(
                                        f"{user_info['name'][:24]:<25} {email[:29]:<30} {user_info['role']:<8} {user_info['login_time']:<16}")
                        except Exception:
                            continue

                    print("-" * 80)

                    # Show permissions system users
                    try:
                        users_in_permissions = await permissions_manager.get_all_users()
                        print(f"📋 Users in permissions system: {len(users_in_permissions)}")

                        if users_in_permissions:
                            for user in users_in_permissions:
                                print(
                                    f"   • {user.get('name', 'Unknown')} ({user.get('email', 'Unknown')}) - {user.get('role', 'user').upper()}")
                    except Exception as e:
                        print(f"📋 Error getting permissions users: {e}")

                    last_session_count = current_count
                    print(f"\n⏰ Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")

            except Exception as e:
                print(f"Error in monitoring loop: {e}")

            # Wait before next check
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        print("\n\n👋 Session monitoring stopped.")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(monitor_sessions())
