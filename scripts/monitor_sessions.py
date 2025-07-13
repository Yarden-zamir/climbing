#!/usr/bin/env python3
"""
Script to monitor and display active user sessions.
Usage: uv run python scripts/monitor_sessions.py
"""

from permissions import PermissionsManager
from redis_store import RedisDataStore
import asyncio
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path so we can import from the main project
sys.path.insert(0, str(Path(__file__).parent.parent))


# Setup logging
logging.basicConfig(level=logging.INFO)
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
                        if users_in_permissions:
                            print(f"📋 Users in permissions system: {len(users_in_permissions)}")

                            # Show role distribution
                            role_counts = {}
                            for user in users_in_permissions:
                                role = user.get("role", "user")
                                role_counts[role] = role_counts.get(role, 0) + 1

                            role_summary = ", ".join(
                                [f"{role}: {count} "for role, count in sorted(role_counts.items())])
                            print(f"📊 Role distribution: {role_summary}")
                        else:
                            print("📋 No users found in permissions system")

                    except Exception as e:
                        print(f"⚠️  Could not get permissions data: {e}")

                    last_session_count = current_count
                    print(f"\n⏰ Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                print(f"⚠️  Monitoring error: {e}")

            # Wait before next check
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        print("\n\n👋 Session monitoring stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in session monitor: {e}")
        print(f"❌ Fatal error: {e}")


async def main():
    await monitor_sessions()


if __name__ == "__main__":
    asyncio.run(main())
