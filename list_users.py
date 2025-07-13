#!/usr/bin/env python3
"""
Script to list all users with their roles.
Usage: uv run python list_users.py
"""

import asyncio
import logging
from redis_store import RedisDataStore
from permissions import PermissionsManager

# Setup logging
logging.basicConfig(level=logging.WARNING)  # Only show warnings and errors
logger = logging.getLogger(__name__)

async def main():
    try:
        # Initialize Redis connection
        redis_store = RedisDataStore(host='localhost', port=6379)
        
        # Initialize permissions manager
        permissions_manager = PermissionsManager(redis_store)
        
        # Get all users
        users = await permissions_manager.get_all_users()
        
        if not users:
            print("No users found in the system.")
            return
        
        print(f"Found {len(users)} users:")
        print("-" * 80)
        print(f"{'Name':<25} {'Email':<30} {'Role':<10} {'Created':<15}")
        print("-" * 80)
        
        for user in users:
            name = user.get("name", "Unknown")[:24]
            email = user.get("email", "Unknown")[:29]
            role = user.get("role", "user").upper()
            created_at = user.get("created_at", "Unknown")[:10]  # Just the date part
            
            print(f"{name:<25} {email:<30} {role:<10} {created_at:<15}")
        
        print("-" * 80)
        print(f"Total users: {len(users)}")
        
        # Count by role
        role_counts = {}
        for user in users:
            role = user.get("role", "user")
            role_counts[role] = role_counts.get(role, 0) + 1
        
        print("\nRole distribution:")
        for role, count in sorted(role_counts.items()):
            print(f"  {role.upper()}: {count}")
            
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 
