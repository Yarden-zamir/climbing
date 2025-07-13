#!/usr/bin/env python3
"""
Script to promote a user to admin status by email address.
Usage: uv run python make_admin.py <email@example.com>
"""

import asyncio
import sys
import logging
import json
from redis_store import RedisDataStore
from permissions import PermissionsManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def find_user_in_sessions(redis_store, email):
    """Find a user by email in active sessions"""
    try:
        # Get all session keys
        session_keys = redis_store.redis.keys("session:*")

        for session_key in session_keys:
            session_data = redis_store.redis.get(session_key)
            if session_data:
                try:
                    user_data = json.loads(session_data)
                    if user_data.get("email") == email:
                        logger.info(f"Found user {email} in session {session_key}")
                        return user_data
                except json.JSONDecodeError:
                    continue

        return None
    except Exception as e:
        logger.error(f"Error searching sessions: {e}")
        return None


async def main():
    if len(sys.argv) != 2:
        print("Usage: uv run python make_admin.py <email@example.com>")
        sys.exit(1)

    email = sys.argv[1]

    if not email or "@" not in email:
        print("Error: Please provide a valid email address")
        sys.exit(1)

    try:
        # Initialize Redis connection
        logger.info("Connecting to Redis...")
        redis_store = RedisDataStore(host='localhost', port=6379)

        # Initialize permissions manager
        permissions_manager = PermissionsManager(redis_store)

        # Find user by email
        logger.info(f"Looking for user with email: {email}")
        user = await permissions_manager.get_user_by_email(email)

        if not user:
            # User not found in permissions system, check if they exist in sessions
            logger.info(f"User not found in permissions system, checking sessions...")
            user_from_session = await find_user_in_sessions(redis_store, email)

            if user_from_session:
                logger.info(f"Found user in sessions, creating user record...")
                user = await permissions_manager.create_or_update_user(user_from_session)
                logger.info(f"Created user record for {email}")
            else:
                logger.error(f"User with email '{email}' not found in sessions or permissions system")
                print(f"❌ User with email '{email}' not found")
                print("Make sure the user has logged in at least once before promoting to admin.")
                sys.exit(1)

        # Check current role
        current_role = user.get("role", "user")
        logger.info(f"Found user: {user.get('name')} ({email}) - Current role: {current_role}")

        if current_role == "admin":
            logger.info("User is already an admin")
            print(f"✅ User '{user.get('name')}' ({email}) is already an admin")
            return

        # Promote to admin
        logger.info(f"Promoting user {user.get('name')} to admin...")
        success = await permissions_manager.assign_admin_user(email)

        if success:
            logger.info("User successfully promoted to admin")
            print(f"✅ Successfully promoted '{user.get('name')}' ({email}) to admin")
            print(f"   User ID: {user.get('id')}")
            print(f"   Previous role: {current_role}")
            print(f"   New role: admin")
        else:
            logger.error("Failed to promote user to admin")
            print(f"❌ Failed to promote '{user.get('name')}' ({email}) to admin")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
