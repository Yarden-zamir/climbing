#!/usr/bin/env python3
"""
Test script to verify the Redis migration worked correctly.
This checks that the data structure has been properly converted.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from redis_store import RedisDataStore

def test_migration():
    """Test that the migration was successful"""
    
    # Initialize Redis store
    redis_store = RedisDataStore()
    redis = redis_store.redis
    
    print("🔍 Testing Redis migration results...")
    
    # Test climber data structure
    print("\n=== TESTING CLIMBER DATA STRUCTURE ===")
    
    # Get a sample climber
    climber_names = list(redis.smembers("index:climbers:all"))
    if climber_names:
        sample_climber = climber_names[0]
        print(f"Testing climber: {sample_climber}")
        
        # Check if sets exist
        skills_exist = redis.exists(f"climber:{sample_climber}:skills")
        tags_exist = redis.exists(f"climber:{sample_climber}:tags")
        achievements_exist = redis.exists(f"climber:{sample_climber}:achievements")
        
        print(f"✅ Skills set exists: {skills_exist}")
        print(f"✅ Tags set exists: {tags_exist}")
        print(f"✅ Achievements set exists: {achievements_exist}")
        
        # Show the sets
        if skills_exist:
            skills = list(redis.smembers(f"climber:{sample_climber}:skills"))
            print(f"Skills: {skills}")
        
        if tags_exist:
            tags = list(redis.smembers(f"climber:{sample_climber}:tags"))
            print(f"Tags: {tags}")
        
        if achievements_exist:
            achievements = list(redis.smembers(f"climber:{sample_climber}:achievements"))
            print(f"Achievements: {achievements}")
    
    # Test album data structure
    print("\n=== TESTING ALBUM DATA STRUCTURE ===")
    
    album_urls = list(redis.smembers("index:albums:all"))
    if album_urls:
        sample_album = album_urls[0]
        print(f"Testing album: {sample_album}")
        
        # Check if crew set exists
        crew_exists = redis.exists(f"album:{sample_album}:crew")
        print(f"✅ Crew set exists: {crew_exists}")
        
        if crew_exists:
            crew = list(redis.smembers(f"album:{sample_album}:crew"))
            print(f"Crew: {crew}")
    
    # Test reverse lookups
    print("\n=== TESTING REVERSE LOOKUPS ===")
    
    all_skills = list(redis.smembers("index:skills:all"))
    print(f"All skills: {all_skills}")
    
    if all_skills:
        sample_skill = all_skills[0]
        climbers_with_skill = list(redis.smembers(f"index:climbers:skill:{sample_skill}"))
        print(f"Climbers with '{sample_skill}': {climbers_with_skill}")
    
    all_tags = list(redis.smembers("index:tags:all"))
    print(f"All tags: {all_tags}")
    
    all_achievements = list(redis.smembers("index:achievements:all"))
    print(f"All achievements: {all_achievements}")
    
    # Test session TTLs
    print("\n=== TESTING SESSION TTLs ===")
    
    session_keys = redis.keys("session:*")
    if session_keys:
        sample_session = session_keys[0]
        ttl = redis.ttl(sample_session)
        print(f"Session TTL: {ttl} seconds (should be around 604800 = 7 days)")
    
    # Summary stats
    print("\n=== SUMMARY STATISTICS ===")
    
    climber_count = len(redis.smembers("index:climbers:all"))
    album_count = len(redis.smembers("index:albums:all"))
    skills_count = len(redis.smembers("index:skills:all"))
    tags_count = len(redis.smembers("index:tags:all"))
    achievements_count = len(redis.smembers("index:achievements:all"))
    
    print(f"📊 Total climbers: {climber_count}")
    print(f"📊 Total albums: {album_count}")
    print(f"📊 Total skills: {skills_count}")
    print(f"📊 Total tags: {tags_count}")
    print(f"📊 Total achievements: {achievements_count}")
    
    # Count climbers with sets
    climbers_with_sets = 0
    for name in redis.smembers("index:climbers:all"):
        if (redis.exists(f"climber:{name}:skills") or 
            redis.exists(f"climber:{name}:tags") or 
            redis.exists(f"climber:{name}:achievements")):
            climbers_with_sets += 1
    
    print(f"📊 Climbers with sets: {climbers_with_sets}/{climber_count}")
    
    # Count albums with crew sets
    albums_with_crew_sets = 0
    for url in redis.smembers("index:albums:all"):
        if redis.exists(f"album:{url}:crew"):
            albums_with_crew_sets += 1
    
    print(f"📊 Albums with crew sets: {albums_with_crew_sets}/{album_count}")
    
    print("\n✅ Migration test completed!")

if __name__ == "__main__":
    test_migration() 
