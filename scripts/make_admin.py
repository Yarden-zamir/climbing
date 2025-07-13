#!/usr/bin/env python3
"""
Script to make a user an admin.
Usage: uv run python scripts/make_admin.py <user_email>
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path so we can import from the main project
sys.path.insert(0, str(Path(__file__).parent.parent))

from redis_store import RedisDataStore
from permissions import PermissionsManager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/make_admin.py <user_email>")
        print("Example: uv run python scripts/make_admin.py user@example.com")
        sys.exit(1)
    
    user_email = sys.argv[1]
    
    try:
        # Initialize Redis connection
        redis_store = RedisDataStore(host='localhost', port=6379)
        
        # Initialize permissions manager
        permissions_manager = PermissionsManager(redis_store)
        
        # Check if user exists
        user = await permissions_manager.get_user_by_email(user_email)
        if not user:
            print(f"❌ User with email '{user_email}' not found.")
            sys.exit(1)
        
        current_role = user.get("role", "user")
        
        if current_role == "admin":
            print(f"✅ User '{user_email}' is already an admin.")
            return
        
        # Update user role to admin
        success = await permissions_manager.assign_admin_user(user_email)
        
        if success:
            print(f"✅ Successfully made '{user_email}' an admin!")
            print(f"   Previous role: {current_role}")
            print(f"   New role: admin")
        else:
            print(f"❌ Failed to make '{user_email}' an admin.")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
