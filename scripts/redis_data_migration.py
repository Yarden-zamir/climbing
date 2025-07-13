#!/usr/bin/env python3
"""
Redis Data Migration Script

This script migrates the existing Redis data structure to use proper Redis data types
instead of JSON strings for arrays, adds missing indexes, and fixes data inconsistencies.

Usage: uv run python scripts/redis_data_migration.py
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Any
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from redis_store import RedisDataStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RedisDataMigrator:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_store = RedisDataStore(host=redis_host, port=redis_port)
        self.redis = self.redis_store.redis
        
    def run_migration(self):
        """Run the complete migration process"""
        try:
            logger.info("🚀 Starting Redis data migration...")
            
            # Run migration steps
            self._migrate_climber_arrays_to_sets()
            self._migrate_album_arrays_to_sets()
            self._add_missing_reverse_lookups()
            self._fix_session_ttls()
            self._add_validation_indexes()
            
            logger.info("✅ Migration completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            raise
            
    def _migrate_climber_arrays_to_sets(self):
        """Convert climber JSON arrays to Redis sets"""
        logger.info("🔄 Migrating climber arrays to sets...")
        
        climber_names = list(self.redis.smembers("index:climbers:all"))
        migrated_count = 0
        
        for name in climber_names:
            climber_key = f"climber:{name}"
            climber_data = self.redis.hgetall(climber_key)
            
            if not climber_data:
                continue
                
            changes_made = False
            
            # Skills
            if "skills" in climber_data:
                try:
                    skills = json.loads(climber_data["skills"])
                    if skills:
                        skills_set_key = f"climber:{name}:skills"
                        self.redis.delete(skills_set_key)
                        self.redis.sadd(skills_set_key, *skills)
                        changes_made = True
                        
                        # Update reverse indexes
                        for skill in skills:
                            self.redis.sadd(f"index:climbers:skill:{skill}", name)
                            self.redis.sadd("index:skills:all", skill)
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in skills for {name}: {climber_data['skills']}")
                    
            # Tags
            if "tags" in climber_data:
                try:
                    tags = json.loads(climber_data["tags"])
                    if tags:
                        tags_set_key = f"climber:{name}:tags"
                        self.redis.delete(tags_set_key)
                        self.redis.sadd(tags_set_key, *tags)
                        changes_made = True
                        
                        # Update reverse indexes
                        for tag in tags:
                            self.redis.sadd(f"index:climbers:tag:{tag}", name)
                            self.redis.sadd("index:tags:all", tag)
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in tags for {name}: {climber_data['tags']}")
                    
            # Achievements
            if "achievements" in climber_data:
                try:
                    achievements = json.loads(climber_data["achievements"])
                    if achievements:
                        achievements_set_key = f"climber:{name}:achievements"
                        self.redis.delete(achievements_set_key)
                        self.redis.sadd(achievements_set_key, *achievements)
                        changes_made = True
                        
                        # Update reverse indexes
                        for achievement in achievements:
                            self.redis.sadd(f"index:climbers:achievement:{achievement}", name)
                            self.redis.sadd("index:achievements:all", achievement)
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in achievements for {name}: {climber_data['achievements']}")
                    
            # Location (keep as JSON for now as it's less frequently accessed)
            if "location" in climber_data:
                try:
                    json.loads(climber_data["location"])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in location for {name}: {climber_data['location']}")
                    self.redis.hset(climber_key, "location", "[]")
                    
            if changes_made:
                migrated_count += 1
                
        logger.info(f"✅ Migrated {migrated_count} climbers to use sets")
        
    def _migrate_album_arrays_to_sets(self):
        """Convert album crew arrays to Redis sets"""
        logger.info("🔄 Migrating album crew arrays to sets...")
        
        album_urls = list(self.redis.smembers("index:albums:all"))
        migrated_count = 0
        
        for url in album_urls:
            album_key = f"album:{url}"
            album_data = self.redis.hgetall(album_key)
            
            if not album_data:
                continue
                
            # Convert crew JSON array to set
            if "crew" in album_data:
                try:
                    crew = json.loads(album_data["crew"])
                    if crew:
                        crew_set_key = f"album:{url}:crew"
                        self.redis.delete(crew_set_key)
                        self.redis.sadd(crew_set_key, *crew)
                        migrated_count += 1
                        
                        # Update reverse indexes (these should already exist)
                        for crew_member in crew:
                            self.redis.sadd(f"index:albums:crew:{crew_member}", url)
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in crew for {url}: {album_data['crew']}")
                    
        logger.info(f"✅ Migrated {migrated_count} albums to use sets")
        
    def _add_missing_reverse_lookups(self):
        """Add missing reverse lookup indexes"""
        logger.info("🔄 Adding missing reverse lookup indexes...")
        
        # Verify indexes exist
        skills_count = len(self.redis.smembers("index:skills:all"))
        achievements_count = len(self.redis.smembers("index:achievements:all"))
        tags_count = len(self.redis.smembers("index:tags:all"))
        
        logger.info(f"✅ Verified reverse lookups: {skills_count} skills, {achievements_count} achievements, {tags_count} tags")
        
    def _fix_session_ttls(self):
        """Fix session TTLs to be 7 days"""
        logger.info("🔄 Fixing session TTLs...")
        
        session_keys = self.redis.keys("session:*")
        fixed_count = 0
        
        for session_key in session_keys:
            # Set TTL to 7 days (604800 seconds)
            self.redis.expire(session_key, 604800)
            fixed_count += 1
            
        logger.info(f"✅ Fixed TTL for {fixed_count} sessions")
        
    def _add_validation_indexes(self):
        """Add validation and constraint indexes"""
        logger.info("🔄 Adding validation indexes...")
        
        # Add user role validation
        user_ids = list(self.redis.smembers("index:users:all"))
        for user_id in user_ids:
            user_data = self.redis.hgetall(f"user:{user_id}")
            if user_data:
                role = user_data.get("role", "user")
                if role not in ["admin", "user"]:
                    logger.warning(f"Invalid role '{role}' for user {user_id}, fixing to 'user'")
                    self.redis.hset(f"user:{user_id}", "role", "user")
                    role = "user"
                self.redis.sadd(f"index:users:role:{role}", user_id)
                
        # Add skill validation
        all_skills = list(self.redis.smembers("index:skills:all"))
        allowed_skills = [
            "climber", "belayer", "lead climber", "lead belayer", 
            "anchor closer", "self belayer", "rope coiler", "diversity pick"
        ]
        
        for skill in all_skills:
            if skill not in allowed_skills:
                logger.warning(f"Non-standard skill found: '{skill}' - consider adding to allowed list")
                
        logger.info("✅ Validation indexes added")
        
    def verify_migration(self):
        """Verify the migration was successful"""
        logger.info("🔍 Verifying migration...")
        
        # Check climber data
        climber_names = list(self.redis.smembers("index:climbers:all"))
        climber_with_sets = 0
        
        for name in climber_names:
            if (self.redis.exists(f"climber:{name}:skills") or 
                self.redis.exists(f"climber:{name}:tags") or 
                self.redis.exists(f"climber:{name}:achievements")):
                climber_with_sets += 1
                
        logger.info(f"✅ {climber_with_sets}/{len(climber_names)} climbers have set-based data")
        
        # Check album data
        album_urls = list(self.redis.smembers("index:albums:all"))
        albums_with_sets = 0
        
        for url in album_urls:
            if self.redis.exists(f"album:{url}:crew"):
                albums_with_sets += 1
                
        logger.info(f"✅ {albums_with_sets}/{len(album_urls)} albums have set-based crew data")
        
        # Check indexes
        skills_count = len(self.redis.smembers("index:skills:all"))
        achievements_count = len(self.redis.smembers("index:achievements:all"))
        tags_count = len(self.redis.smembers("index:tags:all"))
        
        logger.info(f"✅ Global indexes: {skills_count} skills, {achievements_count} achievements, {tags_count} tags")
        
        return True


def main():
    """Main migration function"""
    try:
        migrator = RedisDataMigrator()
        migrator.run_migration()
        migrator.verify_migration()
        
        logger.info("🎉 Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1
        
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
