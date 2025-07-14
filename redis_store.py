import redis
import json
import uuid
import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Any, Union
import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class RedisDataStore:
    """Enhanced Redis data store with proper data types and validation"""

    def __init__(self, host='localhost', port=6379, db=0, password=None, ssl=False):
        """Initialize Redis connections with security configuration"""
        try:
            # Common connection parameters
            connection_params = {
                'host': host,
                'port': port,
                'socket_timeout': 5,
                'health_check_interval': 30,
                'socket_keepalive': True
            }

            # Add password if provided
            if password:
                connection_params['password'] = password

            # Add SSL if enabled
            if ssl:
                connection_params['ssl'] = True

            # Text data connection (decode_responses=True for strings)
            self.redis = redis.Redis(
                db=db,
                decode_responses=True,
                **connection_params
            )

            # Binary data connection for images (decode_responses=False for bytes)
            self.binary_redis = redis.Redis(
                db=db + 1,
                decode_responses=False,
                **connection_params
            )

            # Test connections
            self.redis.ping()
            self.binary_redis.ping()
            logger.info("Redis connections established successfully")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    # === VALIDATION METHODS ===

    def _validate_name(self, name: str) -> str:
        """Validate and sanitize names"""
        if not name or not isinstance(name, str):
            raise ValidationError("Name must be a non-empty string")

        name = name.strip()
        if len(name) < 1 or len(name) > 100:
            raise ValidationError("Name must be between 1 and 100 characters")

        # Allow letters, numbers, spaces, and common punctuation
        if not re.match(r"^[a-zA-Z0-9\s\-_'.()]+$", name):
            raise ValidationError("Name contains invalid characters")

        return name

    def _validate_email(self, email: str) -> str:
        """Validate email format"""
        if not email or not isinstance(email, str):
            raise ValidationError("Email must be a non-empty string")

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, email):
            raise ValidationError("Invalid email format")

        return email.lower()

    def _validate_skills(self, skills: List[str]) -> List[str]:
        """Validate skills list"""
        if not isinstance(skills, list):
            raise ValidationError("Skills must be a list")

        allowed_skills = [
            "climber", "belayer", "lead climber", "lead belayer",
            "anchor closer", "self belayer", "rope coiler", "diversity pick"
        ]

        validated_skills = []
        for skill in skills:
            if not isinstance(skill, str):
                raise ValidationError(f"Skill must be a string: {skill}")
            skill = skill.strip()
            if skill not in allowed_skills:
                raise ValidationError(f"Invalid skill: {skill}")
            if skill not in validated_skills:  # Remove duplicates
                validated_skills.append(skill)

        return validated_skills

    def _validate_url(self, url: str) -> str:
        """Validate Google Photos URL"""
        if not url or not isinstance(url, str):
            raise ValidationError("URL must be a non-empty string")

        pattern = r"^https://photos\.app\.goo\.gl/[a-zA-Z0-9]+$"
        if not re.match(pattern, url):
            raise ValidationError("Invalid Google Photos URL format")

        return url

    # === ENHANCED CLIMBER METHODS ===

    async def add_climber(
        self, name: str, location: Optional[List[str]] = None, skills: Optional[List[str]] = None,
        tags: Optional[List[str]] = None, achievements: Optional[List[str]] = None
    ) -> None:
        """Add a new climber with validation and proper data types"""

        # Validate inputs
        name = self._validate_name(name)
        skills = self._validate_skills(skills or [])
        location = location or []
        tags = tags or []
        achievements = achievements or []

        climber_key = f"climber:{name}"

        # Check if climber already exists
        if self.redis.exists(climber_key):
            raise ValidationError(f"Climber already exists: {name}")

        # Store climber data (keep location as JSON for now)
        # Note: level values are calculated dynamically, not stored
        climber_data = {
            "name": name,
            "location": json.dumps(location),
            "climbs": "0",
            "is_new": "true",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Store climber
        pipe.hset(climber_key, mapping=climber_data)

        # Store skills as Redis set
        if skills:
            pipe.sadd(f"climber:{name}:skills", *skills)

        # Store tags as Redis set
        if tags:
            pipe.sadd(f"climber:{name}:tags", *tags)

        # Store achievements as Redis set
        if achievements:
            pipe.sadd(f"climber:{name}:achievements", *achievements)

        # Update indexes
        pipe.sadd("index:climbers:all", name)
        pipe.sadd("index:climbers:new", name)

        # Index skills
        for skill in skills:
            pipe.sadd("index:skills:all", skill)
            pipe.sadd(f"index:climbers:skill:{skill}", name)

        # Index tags
        for tag in tags:
            pipe.sadd("index:tags:all", tag)
            pipe.sadd(f"index:climbers:tag:{tag}", name)

        # Index achievements
        for achievement in achievements:
            pipe.sadd("index:achievements:all", achievement)
            pipe.sadd(f"index:climbers:achievement:{achievement}", name)

        # Execute all operations
        pipe.execute()

        logger.info(f"Added climber: {name}")

    async def get_climber(self, name: str) -> Optional[Dict]:
        """Get climber with proper data types"""
        climber_key = f"climber:{name}"
        climber_data = self.redis.hgetall(climber_key)

        if not climber_data:
            return None

        # Get data from sets instead of JSON
        skills = list(self.redis.smembers(f"climber:{name}:skills"))
        tags = list(self.redis.smembers(f"climber:{name}:tags"))
        achievements = list(self.redis.smembers(f"climber:{name}:achievements"))

        # Parse remaining JSON fields
        climber_data["location"] = json.loads(climber_data.get("location", "[]"))
        climber_data["skills"] = skills
        climber_data["tags"] = tags
        climber_data["achievements"] = achievements

        # Convert numeric fields
        climbs = int(climber_data.get("climbs", "0"))
        climber_data["climbs"] = climbs
        climber_data["is_new"] = climber_data.get("is_new", "false") == "true"

        # Calculate levels dynamically using current logic (ignore stored values)
        total_level, level_from_skills, level_from_climbs, level_from_achievements = self.calculate_climber_level(
            len(skills), climbs, len(achievements))
        climber_data["level"] = total_level
        climber_data["level_from_skills"] = level_from_skills
        climber_data["level_from_climbs"] = level_from_climbs
        climber_data["level_from_achievements"] = level_from_achievements

        # Add computed fields
        climber_data["first_climb_date"] = climber_data.get("first_climb_date", None)
        climber_data["face"] = f"/redis-image/climber/{name}/face"

        return climber_data

    async def update_climber(
        self, original_name: str, name: Optional[str] = None, location: Optional[List[str]] = None,
        skills: Optional[List[str]] = None, tags: Optional[List[str]] = None, achievements: Optional[List[str]] = None
    ) -> None:
        """Update climber with validation and proper data types"""

        # Get current climber
        current_climber = await self.get_climber(original_name)
        if not current_climber:
            raise ValidationError(f"Climber not found: {original_name}")

        # Validate inputs
        name = self._validate_name(name) if name else original_name
        skills = self._validate_skills(skills) if skills is not None else current_climber["skills"]
        location = location if location is not None else current_climber["location"]
        tags = tags if tags is not None else current_climber["tags"]
        achievements = achievements if achievements is not None else current_climber["achievements"]

        name_changed = name != original_name
        original_key = f"climber:{original_name}"
        new_key = f"climber:{name}"

        # Get current climbs
        current_climbs = current_climber["climbs"]

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Update climber data (levels calculated dynamically, not stored)
        updated_data = {
            "name": name,
            "location": json.dumps(location),
            "climbs": str(current_climbs),
            "is_new": "true" if current_climber.get("is_new", False) else "false",
            "created_at": current_climber.get("created_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat()
        }

        if name_changed:
            # Create new record
            pipe.hset(new_key, mapping=updated_data)

            # Move sets
            pipe.rename(f"climber:{original_name}:skills", f"climber:{name}:skills")
            pipe.rename(f"climber:{original_name}:tags", f"climber:{name}:tags")
            pipe.rename(f"climber:{original_name}:achievements", f"climber:{name}:achievements")

            # Update indexes
            pipe.srem("index:climbers:all", original_name)
            pipe.sadd("index:climbers:all", name)

            # Delete old record
            pipe.delete(original_key)
        else:
            # Update existing record
            pipe.hset(original_key, mapping=updated_data)

        # Update skill sets and indexes
        pipe.delete(f"climber:{name}:skills")
        if skills:
            pipe.sadd(f"climber:{name}:skills", *skills)

        # Update tag sets and indexes
        pipe.delete(f"climber:{name}:tags")
        if tags:
            pipe.sadd(f"climber:{name}:tags", *tags)

        # Update achievement sets and indexes
        pipe.delete(f"climber:{name}:achievements")
        if achievements:
            pipe.sadd(f"climber:{name}:achievements", *achievements)

        # Rebuild indexes for skills, tags, achievements
        # (This is simplified - in production you'd want to be more efficient)
        for skill in skills:
            pipe.sadd("index:skills:all", skill)
            pipe.sadd(f"index:climbers:skill:{skill}", name)

        for tag in tags:
            pipe.sadd("index:tags:all", tag)
            pipe.sadd(f"index:climbers:tag:{tag}", name)

        for achievement in achievements:
            pipe.sadd("index:achievements:all", achievement)
            pipe.sadd(f"index:climbers:achievement:{achievement}", name)

        # Execute all operations
        pipe.execute()

        logger.info(f"Updated climber: {original_name} -> {name}")

    # === ENHANCED ALBUM METHODS ===

    async def add_album(self, url: str, crew: List[str], metadata: Dict = None) -> None:
        """Add album with validation and proper data types"""

        # Validate inputs
        url = self._validate_url(url)
        crew = [self._validate_name(member) for member in crew]

        album_key = f"album:{url}"

        # Prepare album data
        album_data = {
            "url": url,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Add metadata if provided
        if metadata:
            album_data.update({
                "title": metadata.get("title", ""),
                "description": metadata.get("description", ""),
                "date": metadata.get("date", ""),
                "image_url": metadata.get("imageUrl", ""),
                "cover_image": metadata.get("cover_image", "")
            })

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Store album
        pipe.hset(album_key, mapping=album_data)

        # Store crew as Redis set
        if crew:
            pipe.sadd(f"album:{url}:crew", *crew)

        # Update indexes
        pipe.sadd("index:albums:all", url)

        # Index by crew members
        for crew_member in crew:
            pipe.sadd(f"index:albums:crew:{crew_member}", url)

        # Update climb counts for crew members
        for crew_member in crew:
            pipe.hincrby(f"climber:{crew_member}", "climbs", 1)

        # Execute all operations
        pipe.execute()

        # Recalculate levels for crew members
        for crew_member in crew:
            await self._recalculate_climber_level(crew_member)

        logger.info(f"Added album: {url} with crew: {crew}")

    async def get_album(self, url: str) -> Optional[Dict]:
        """Get album with proper data types"""
        album_key = f"album:{url}"
        album_data = self.redis.hgetall(album_key)

        if not album_data:
            return None

        # Get crew from set instead of JSON
        crew = list(self.redis.smembers(f"album:{url}:crew"))
        album_data["crew"] = crew

        return album_data

    async def update_album_crew(self, url: str, new_crew: List[str]) -> None:
        """Update album crew members using proper Redis data types"""
        
        # Validate inputs
        url = self._validate_url(url)
        new_crew = [self._validate_name(member) for member in new_crew]
        
        album_key = f"album:{url}"
        
        # Get current album and crew
        current_album = await self.get_album(url)
        if not current_album:
            raise ValidationError(f"Album not found: {url}")
        
        old_crew = current_album["crew"]
        
        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Update album timestamp
        pipe.hset(album_key, "updated_at", datetime.now().isoformat())
        
        # Clear and update crew set
        pipe.delete(f"album:{url}:crew")
        if new_crew:
            pipe.sadd(f"album:{url}:crew", *new_crew)
        
        # Remove from old crew member indexes and decrease climb counts
        for crew_member in old_crew:
            pipe.srem(f"index:albums:crew:{crew_member}", url)
            # Get current climbs and decrease if > 0
            current_climbs = self.redis.hget(f"climber:{crew_member}", "climbs")
            if current_climbs and int(current_climbs) > 0:
                pipe.hincrby(f"climber:{crew_member}", "climbs", -1)
        
        # Add to new crew member indexes and increase climb counts
        for crew_member in new_crew:
            pipe.sadd(f"index:albums:crew:{crew_member}", url)
            pipe.hincrby(f"climber:{crew_member}", "climbs", 1)
        
        # Execute all operations
        pipe.execute()
        
        # Recalculate levels for all affected climbers
        affected_climbers = set(old_crew + new_crew)
        for crew_member in affected_climbers:
            await self._recalculate_climber_level(crew_member)
        
        logger.info(f"Updated album crew: {url} from {old_crew} to {new_crew}")

    async def update_album_metadata(self, url: str, metadata: Dict) -> None:
        """Update album metadata without changing crew data"""
        
        # Validate inputs
        url = self._validate_url(url)
        album_key = f"album:{url}"
        
        # Check if album exists
        if not self.redis.exists(album_key):
            raise ValidationError(f"Album not found: {url}")
        
        # Update only metadata fields
        metadata_update = {
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "date": metadata.get("date", ""),
            "image_url": metadata.get("imageUrl", ""),
            "cover_image": metadata.get("cover_image", ""),
            "updated_at": datetime.now().isoformat()
        }
        
        # Update album with new metadata
        self.redis.hset(album_key, mapping=metadata_update)
        logger.info(f"Updated metadata for album: {url}")

    async def delete_album(self, url: str) -> bool:
        """Delete an album using proper Redis data types"""
        
        # Validate input
        url = self._validate_url(url)
        
        # Get current album
        album = await self.get_album(url)
        if not album:
            return False
        
        crew = album["crew"]
        
        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Remove from crew indexes and decrease climb counts
        for crew_member in crew:
            pipe.srem(f"index:albums:crew:{crew_member}", url)
            # Get current climbs and decrease if > 0
            current_climbs = self.redis.hget(f"climber:{crew_member}", "climbs")
            if current_climbs and int(current_climbs) > 0:
                pipe.hincrby(f"climber:{crew_member}", "climbs", -1)
        
        # Remove from main index
        pipe.srem("index:albums:all", url)
        
        # Delete album data and crew set
        pipe.delete(f"album:{url}")
        pipe.delete(f"album:{url}:crew")
        
        # Execute all operations
        pipe.execute()
        
        # Recalculate levels for affected climbers
        for crew_member in crew:
            await self._recalculate_climber_level(crew_member)
        
        logger.info(f"Deleted album: {url}")
        return True

    async def delete_climber(self, name: str) -> bool:
        """Delete a climber using proper Redis data types"""
        
        # Validate input
        name = self._validate_name(name)
        
        # Get current climber
        climber = await self.get_climber(name)
        if not climber:
            return False
        
        skills = climber["skills"]
        tags = climber["tags"]
        achievements = climber["achievements"]
        
        # Remove from all albums first
        album_urls = list(self.redis.smembers(f"index:albums:crew:{name}"))
        for url in album_urls:
            album = await self.get_album(url)
            if album:
                new_crew = [member for member in album["crew"] if member != name]
                await self.update_album_crew(url, new_crew)
        
        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Remove from indexes
        pipe.srem("index:climbers:all", name)
        pipe.srem("index:climbers:new", name)
        
        # Remove from skill indexes
        for skill in skills:
            pipe.srem(f"index:climbers:skill:{skill}", name)
        
        # Remove from tag indexes  
        for tag in tags:
            pipe.srem(f"index:climbers:tag:{tag}", name)
        
        # Remove from achievement indexes
        for achievement in achievements:
            pipe.srem(f"index:climbers:achievement:{achievement}", name)
        
        # Delete climber data and sets
        pipe.delete(f"climber:{name}")
        pipe.delete(f"climber:{name}:skills")
        pipe.delete(f"climber:{name}:tags")
        pipe.delete(f"climber:{name}:achievements")
        
        # Execute all operations
        pipe.execute()
        
        # Remove image
        await self.delete_image("climber", f"{name}/face")
        
        logger.info(f"Deleted climber: {name}")
        return True

    async def calculate_new_climbers(self) -> Set[str]:
        """Calculate which climbers are new (first participation in last 14 days)"""
        try:
            cutoff_date = datetime.now() - timedelta(days=14)
            new_climbers = set()
            
            # Get all albums sorted by date
            albums = await self.get_all_albums()
            if not albums:
                logger.info("No albums found, skipping new climbers calculation")
                return new_climbers
            
            # Process albums chronologically
            albums_with_dates = []
            import re
            
            for album in albums:
                try:
                    # Parse album date
                    date_str = album.get("date", "")
                    if not date_str:
                        continue
                    
                    try:
                        # Remove emoji and extra spaces
                        clean_date = re.sub(r'📸.*$', '', date_str).strip()
                        
                        # Handle date ranges - use first date
                        if '–' in clean_date:
                            clean_date = clean_date.split('–')[0].strip()
                        
                        # Remove day of week
                        clean_date = re.sub(r'^[A-Za-z]+,\s*', '', clean_date)
                        
                        # Add current year if not present
                        if not re.search(r'\b20\d{2}\b', clean_date):
                            clean_date = f"{clean_date}, {datetime.now().year}"
                        
                        # Parse date
                        try:
                            # Try different date formats
                            for fmt in ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]:
                                try:
                                    album_date = datetime.strptime(clean_date, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue
                        except ValueError:
                            continue
                        
                        albums_with_dates.append((album_date, album))
                        
                    except Exception as e:
                        logger.warning(f"Could not parse date '{date_str}' for album {album.get('url', 'unknown')}: {e}")
                        continue
                        
                except Exception as e:
                    logger.warning(f"Error processing album {album.get('url', 'unknown')}: {e}")
                    continue
            
            # Sort albums by date
            albums_with_dates.sort(key=lambda x: x[0])
            
            # Track first appearances
            first_appearance = {}
            
            for album_date, album in albums_with_dates:
                for crew_member in album.get("crew", []):
                    if crew_member not in first_appearance:
                        first_appearance[crew_member] = album_date
            
            # Find climbers who first appeared in the last 14 days
            for climber, first_date in first_appearance.items():
                if first_date >= cutoff_date:
                    new_climbers.add(climber)
            
            # Update the new climbers index
            pipe = self.redis.pipeline()
            pipe.delete("index:climbers:new")
            if new_climbers:
                pipe.sadd("index:climbers:new", *new_climbers)
            pipe.execute()
            
            logger.info(f"Found {len(new_climbers)} new climbers: {new_climbers}")
            return new_climbers
            
        except Exception as e:
            logger.error(f"Error calculating new climbers: {e}")
            return set()

    # === UTILITY METHODS ===

    @staticmethod
    def calculate_climber_level(skills_count: int, climbs: int, achievements_count: int = 0) -> tuple[int, int, int, int]:
        """
        Central level calculation for climbers.
        Returns: (total_level, level_from_skills, level_from_climbs, level_from_achievements)
        """
        level_from_skills = skills_count
        level_from_climbs = climbs // 5  # 1 level per 5 climbs
        level_from_achievements = achievements_count
        total_level = 1 + level_from_skills + level_from_climbs + level_from_achievements
        return total_level, level_from_skills, level_from_climbs, level_from_achievements

    @staticmethod
    def calculate_climbs_to_next_level(climbs: int) -> int:
        """Calculate how many climbs needed to reach the next level"""
        climbs_in_current_level = climbs % 5
        return 5 - climbs_in_current_level if climbs_in_current_level > 0 else 0

    async def _recalculate_climber_level(self, name: str) -> None:
        """Update climber timestamp (levels are calculated dynamically)"""
        climber_key = f"climber:{name}"

        # Just update timestamp since levels are calculated dynamically
        self.redis.hset(climber_key, "updated_at", datetime.now().isoformat())

    async def cleanup_stored_level_values(self) -> dict:
        """
        Remove stored level values from all climber records since levels are now calculated dynamically.
        This should be run once after switching to dynamic level calculation.
        """
        logger.info("Starting cleanup of stored level values...")
        
        # Fields to remove
        level_fields = ["level", "level_from_skills", "level_from_climbs"]
        
        # Get all climber keys
        climber_keys = self.redis.keys("climber:*")
        # Ensure keys are strings and filter out skill/achievement sets
        string_keys = []
        for key in climber_keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            if not key_str.endswith(":skills") and not key_str.endswith(":achievements"):
                string_keys.append(key_str)
        climber_keys = string_keys

        cleaned_count = 0
        total_fields_removed = 0
        debug_info = []

        for climber_key in climber_keys:
            try:
                # First check if this key is actually a hash
                key_type = self.redis.type(climber_key)
                key_type_str = key_type.decode() if isinstance(key_type, bytes) else key_type
                
                if key_type_str != 'hash':
                    debug_info.append(f"Skipped {climber_key}: type={key_type_str}")
                    continue
                
                # Get all fields in this hash for debugging
                all_fields = self.redis.hkeys(climber_key)
                all_fields_str = [f.decode() if isinstance(f, bytes) else f for f in all_fields]
                
                # Check if any level fields exist
                existing_fields = []
                for field in level_fields:
                    if self.redis.hexists(climber_key, field):
                        existing_fields.append(field)
                
                # Log what we found for the first few keys
                if len(debug_info) < 5:
                    debug_info.append(f"Key {climber_key}: fields={all_fields_str}, level_fields_found={existing_fields}")
                
                # Remove the fields if they exist
                if existing_fields:
                    self.redis.hdel(climber_key, *existing_fields)
                    cleaned_count += 1
                    total_fields_removed += len(existing_fields)
                    logger.info(f"Cleaned {climber_key}: removed {existing_fields}")
                    
                    # Update timestamp to indicate cleanup
                    self.redis.hset(climber_key, "updated_at", datetime.now().isoformat())
                    
            except Exception as e:
                # Log individual key errors but continue with cleanup
                logger.warning(f"Failed to clean key {climber_key}: {e}")
                continue
        
        # Log debug info
        for info in debug_info:
            logger.info(f"DEBUG: {info}")
        
        result = {
            "cleaned_climbers": cleaned_count,
            "total_fields_removed": total_fields_removed,
            "total_climbers": len(climber_keys)
        }
        
        logger.info(f"Cleanup completed: {result}")
        return result

    # === QUERY METHODS ===

    async def get_climbers_by_skill(self, skill: str) -> List[str]:
        """Get all climbers with a specific skill"""
        return list(self.redis.smembers(f"index:climbers:skill:{skill}"))

    async def get_climbers_by_tag(self, tag: str) -> List[str]:
        """Get all climbers with a specific tag"""
        return list(self.redis.smembers(f"index:climbers:tag:{tag}"))

    async def get_climbers_by_achievement(self, achievement: str) -> List[str]:
        """Get all climbers with a specific achievement"""
        return list(self.redis.smembers(f"index:climbers:achievement:{achievement}"))

    async def get_all_skills(self) -> List[str]:
        """Get all unique skills"""
        return sorted(list(self.redis.smembers("index:skills:all")))

    async def get_all_tags(self) -> List[str]:
        """Get all unique tags"""
        return sorted(list(self.redis.smembers("index:tags:all")))

    async def get_all_achievements(self) -> List[str]:
        """Get all unique achievements"""
        return sorted(list(self.redis.smembers("index:achievements:all")))

    # === BACKWARD COMPATIBILITY ===

    async def get_all_climbers(self) -> List[Dict]:
        """Get all climbers - backward compatible"""
        climber_names = list(self.redis.smembers("index:climbers:all"))
        if not climber_names:
            return []

        climbers = []
        for name in climber_names:
            climber = await self.get_climber(name)
            if climber:
                climbers.append(climber)

        # Sort by level (highest first), then by name
        climbers.sort(key=lambda x: (-x["level"], x["name"]))
        return climbers

    async def get_all_albums(self) -> List[Dict]:
        """Get all albums - backward compatible"""
        album_urls = list(self.redis.smembers("index:albums:all"))
        if not album_urls:
            return []

        albums = []
        for url in album_urls:
            album = await self.get_album(url)
            if album:
                albums.append(album)

        # Sort by album date (newest climbing dates first), fallback to updated_at for consistent order
        def parse_album_date_for_sort(date_str):
            """Parse album date for sorting - newest first"""
            if not date_str:
                return "0000-00-00"  # Empty dates go to bottom

            import re
            from datetime import datetime

            try:
                # Remove emoji and extra spaces
                clean_date = re.sub(r'📸.*$', '', date_str).strip()

                # Handle date ranges - use first date
                if '–' in clean_date:
                    clean_date = clean_date.split('–')[0].strip()

                # Remove day of week
                clean_date = re.sub(r'^[A-Za-z]+,\s*', '', clean_date)

                # Add current year if not present
                current_year = datetime.now().year
                if str(current_year) not in clean_date:
                    clean_date = f"{clean_date} {current_year}"

                # Parse date
                parsed_date = datetime.strptime(clean_date, "%b %d %Y")
                return parsed_date.strftime("%Y-%m-%d")

            except Exception:
                return "0000-00-00"  # Unparseable dates go to bottom

        def parse_updated_at_for_sort(updated_at_str):
            if not updated_at_str:
                return "0000-00-00T00:00:00"
            try:
                from datetime import datetime
                return datetime.fromisoformat(updated_at_str).isoformat()
            except Exception:
                return "0000-00-00T00:00:00"

        # Sort by date (newest first), then by updated_at (newest first)
        albums.sort(
            key=lambda x: (
                parse_album_date_for_sort(x.get("date", "")),
                parse_updated_at_for_sort(x.get("updated_at", ""))
            ),
            reverse=True
        )
        return albums

    # === IMAGES ===

    async def store_image(self, image_type: str, identifier: str, image_data: bytes) -> str:
        """Store image and return Redis path"""
        image_key = f"image:{image_type}:{identifier}"
        self.binary_redis.set(image_key, image_data)

        # Set expiration for temp images
        if image_type == "temp":
            self.binary_redis.expire(image_key, 3600)  # 1 hour

        logger.info(f"Stored image: {image_key} ({len(image_data)} bytes)")
        return f"/redis-image/{image_type}/{identifier}"

    async def get_image(self, image_type: str, identifier: str) -> Optional[bytes]:
        """Get image data"""
        image_key = f"image:{image_type}:{identifier}"
        return self.binary_redis.get(image_key)

    async def delete_image(self, image_type: str, identifier: str) -> bool:
        """Delete an image"""
        image_key = f"image:{image_type}:{identifier}"
        result = self.binary_redis.delete(image_key)
        return result > 0

    # === CACHING ===

    async def cache_album_metadata(self, url: str, metadata: Dict, ttl: int = 300) -> None:
        """Cache album metadata"""
        cache_key = f"cache:album_meta:{hashlib.md5(url.encode()).hexdigest()}"
        self.redis.setex(cache_key, ttl, json.dumps(metadata))

    async def get_cached_metadata(self, url: str) -> Optional[Dict]:
        """Get cached album metadata"""
        cache_key = f"cache:album_meta:{hashlib.md5(url.encode()).hexdigest()}"
        cached = self.redis.get(cache_key)
        return json.loads(cached) if cached else None

    # === MEMES ===

    async def add_meme(self, meme_id: str, image_data: bytes, creator_id: str) -> None:
        """Add a new meme"""
        meme_key = f"meme:{meme_id}"

        # Check if meme already exists
        if self.redis.exists(meme_key):
            raise ValueError(f"Meme already exists: {meme_id}")

        # Store image data
        image_path = await self.store_image("meme", meme_id, image_data)

        # Prepare meme data
        meme_data = {
            "id": meme_id,
            "image_path": image_path,
            "creator_id": creator_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Store meme
        self.redis.hset(meme_key, mapping=meme_data)

        # Update indexes
        self.redis.sadd("index:memes:all", meme_id)
        self.redis.sadd(f"index:memes:creator:{creator_id}", meme_id)

        logger.info(f"Added meme: {meme_id} by {creator_id}")

    async def get_meme(self, meme_id: str) -> Optional[Dict]:
        """Get meme by ID"""
        meme_key = f"meme:{meme_id}"
        meme_data = self.redis.hgetall(meme_key)

        if not meme_data:
            return None

        return meme_data

    async def get_all_memes(self) -> List[Dict]:
        """Get all memes"""
        meme_ids = self.redis.smembers("index:memes:all")
        if not meme_ids:
            return []

        # Use pipeline to batch Redis calls
        pipe = self.redis.pipeline()
        for meme_id in meme_ids:
            pipe.hgetall(f"meme:{meme_id}")

        # Execute all operations at once
        results = pipe.execute()

        memes = []
        for meme_id, meme_data in zip(meme_ids, results):
            if meme_data:
                memes.append(meme_data)

        # Sort by creation date (newest first)
        memes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return memes

    async def get_memes_by_creator(self, creator_id: str) -> List[Dict]:
        """Get all memes by a specific creator"""
        meme_ids = self.redis.smembers(f"index:memes:creator:{creator_id}")
        memes = []

        for meme_id in meme_ids:
            meme_data = self.redis.hgetall(f"meme:{meme_id}")
            if meme_data:
                memes.append(meme_data)

        # Sort by creation date (newest first)
        memes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return memes

    async def delete_meme(self, meme_id: str) -> bool:
        """Delete a meme"""
        meme = await self.get_meme(meme_id)
        if not meme:
            return False

        # Remove from creator index
        self.redis.srem(f"index:memes:creator:{meme['creator_id']}", meme_id)

        # Remove from main index
        self.redis.srem("index:memes:all", meme_id)

        # Delete image
        await self.delete_image("meme", meme_id)

        # Delete meme data
        self.redis.delete(f"meme:{meme_id}")

        logger.info(f"Deleted meme: {meme_id}")
        return True

    # === SESSIONS ===

    async def store_session(self, session_id: str, user_data: Dict, ttl: int = 604800) -> None:
        """Store session with TTL (default 7 days)"""
        session_key = f"session:{session_id}"
        self.redis.setex(session_key, ttl, json.dumps(user_data))

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data"""
        session_key = f"session:{session_id}"
        session_data = self.redis.get(session_key)
        return json.loads(session_data) if session_data else None

    async def delete_session(self, session_id: str) -> bool:
        """Delete session"""
        session_key = f"session:{session_id}"
        result = self.redis.delete(session_key)
        return result > 0

    # === UTILITY METHODS ===

    async def health_check(self) -> Dict[str, Any]:
        """Health check for Redis connections"""
        try:
            # Test text Redis connection
            text_info = self.redis.info()
            text_ping = self.redis.ping()

            # Test binary Redis connection
            binary_info = self.binary_redis.info()
            binary_ping = self.binary_redis.ping()

            return {
                "status": "healthy",
                "text_db": {
                    "connected": text_ping,
                    "db_size": text_info.get("db0", {}).get("keys", 0)
                },
                "binary_db": {
                    "connected": binary_ping,
                    "db_size": binary_info.get("db1", {}).get("keys", 0)
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    async def clear_all_data(self) -> None:
        """Clear all data - USE WITH CAUTION"""
        self.redis.flushdb()
        self.binary_redis.flushdb()
        logger.warning("All Redis data cleared!")
