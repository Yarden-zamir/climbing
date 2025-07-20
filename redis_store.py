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
        if not skills:
            return []

        validated_skills = []
        for skill in skills:
            if not isinstance(skill, str):
                raise ValidationError(f"Skill must be a string: {skill}")
            skill = skill.strip()
            if not skill:
                raise ValidationError("Skill cannot be empty")
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

            # Move sets only if they exist
            if self.redis.exists(f"climber:{original_name}:skills"):
                pipe.rename(f"climber:{original_name}:skills", f"climber:{name}:skills")
            if self.redis.exists(f"climber:{original_name}:tags"):
                pipe.rename(f"climber:{original_name}:tags", f"climber:{name}:tags")
            if self.redis.exists(f"climber:{original_name}:achievements"):
                pipe.rename(f"climber:{original_name}:achievements", f"climber:{name}:achievements")

            # Update indexes
            pipe.srem("index:climbers:all", original_name)
            pipe.sadd("index:climbers:all", name)

            # Delete old record
            pipe.delete(original_key)
        else:
            # Update existing record
            pipe.hset(original_key, mapping=updated_data)

        # Clean up old indexes if name changed
        if name_changed:
            # Remove old name from skill indexes
            for skill in current_climber["skills"]:
                pipe.srem(f"index:climbers:skill:{skill}", original_name)
            
            # Remove old name from tag indexes
            for tag in current_climber["tags"]:
                pipe.srem(f"index:climbers:tag:{tag}", original_name)
            
            # Remove old name from achievement indexes
            for achievement in current_climber["achievements"]:
                pipe.srem(f"index:climbers:achievement:{achievement}", original_name)

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

        # Handle album crew references and image renaming (after pipeline execution)
        if name_changed:
            # Update album crew references
            album_urls = list(self.redis.smembers(f"index:albums:crew:{original_name}"))
            for url in album_urls:
                try:
                    # Remove old name from crew set and add new name
                    album_crew_key = f"album:{url}:crew"
                    crew_updated = False

                    # Check if old name is in the crew set
                    if self.redis.sismember(album_crew_key, original_name):
                        # Use pipeline for atomic crew update
                        crew_pipe = self.redis.pipeline()
                        crew_pipe.srem(album_crew_key, original_name)
                        crew_pipe.sadd(album_crew_key, name)
                        crew_pipe.execute()
                        crew_updated = True

                        logger.debug(f"Updated crew in album {url}: {original_name} -> {name}")

                    # Update reverse indexes
                    if crew_updated:
                        self.redis.srem(f"index:albums:crew:{original_name}", url)
                        self.redis.sadd(f"index:albums:crew:{name}", url)

                except Exception as e:
                    logger.error(f"Failed to update album crew for {url}: {e}")

            logger.info(f"Updated {len(album_urls)} album crew references for: {original_name} -> {name}")

            # Handle image renaming in binary database
            original_image_key = f"image:climber:{original_name}/face"
            new_image_key = f"image:climber:{name}/face"
            
            try:
                # Check if original image exists and get its data
                image_data = self.binary_redis.get(original_image_key)
                if image_data:
                    # Store with new key
                    self.binary_redis.set(new_image_key, image_data)
                    # Delete old key
                    self.binary_redis.delete(original_image_key)
                    logger.info(f"Moved image from {original_image_key} to {new_image_key}")
                else:
                    logger.debug(f"No image found at {original_image_key} to move")
            except Exception as e:
                logger.error(f"Failed to move image from {original_image_key} to {new_image_key}: {e}")

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
            
            # Update both the index and individual climber records
            pipe = self.redis.pipeline()
            pipe.delete("index:climbers:new")
            if new_climbers:
                pipe.sadd("index:climbers:new", *new_climbers)

            # Update individual climber records
            for climber in first_appearance.keys():
                climber_key = f"climber:{climber}"
                if self.redis.exists(climber_key):
                    is_new = climber in new_climbers
                    pipe.hset(climber_key, "is_new", "true" if is_new else "false")
                    pipe.hset(climber_key, "updated_at", datetime.now().isoformat())

            pipe.execute()
            
            logger.info(f"Found {len(new_climbers)} new climbers: {new_climbers}")
            logger.info(f"Updated is_new status for {len(first_appearance)} total climbers")
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

    # === USER PREFERENCES ===

    async def set_user_preference(self, user_id: str, preference_key: str, preference_value: any) -> None:
        """Set a user preference"""
        if not user_id or not preference_key:
            raise ValidationError("User ID and preference key are required")

        preference_field = f"preferences:{preference_key}"
        user_key = f"user:{user_id}"

        # Store preference as JSON if it's a complex object
        if isinstance(preference_value, (dict, list)):
            preference_value = json.dumps(preference_value)

        self.redis.hset(user_key, preference_field, preference_value)
        logger.info(f"Set user preference: {user_id}:{preference_key} = {preference_value}")

    async def get_user_preference(self, user_id: str, preference_key: str, default=None) -> any:
        """Get a user preference"""
        if not user_id or not preference_key:
            return default

        preference_field = f"preferences:{preference_key}"
        user_key = f"user:{user_id}"

        preference_value = self.redis.hget(user_key, preference_field)

        if preference_value is None:
            return default

        # Try to parse as JSON, fall back to string
        try:
            return json.loads(preference_value)
        except (json.JSONDecodeError, TypeError):
            return preference_value

    async def get_all_user_preferences(self, user_id: str) -> Dict[str, any]:
        """Get all user preferences"""
        if not user_id:
            return {}

        user_key = f"user:{user_id}"
        user_data = self.redis.hgetall(user_key)

        preferences = {}
        for field, value in user_data.items():
            if field.startswith("preferences:"):
                pref_key = field.replace("preferences:", "")
                try:
                    preferences[pref_key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    preferences[pref_key] = value

        return preferences

    async def delete_user_preference(self, user_id: str, preference_key: str) -> bool:
        """Delete a user preference"""
        if not user_id or not preference_key:
            return False

        preference_field = f"preferences:{preference_key}"
        user_key = f"user:{user_id}"

        result = self.redis.hdel(user_key, preference_field)
        return result > 0

    # === PUSH NOTIFICATIONS ===

    async def store_push_subscription(
            self, device_id: str, user_id: Optional[str],
            subscription_data: Dict[str, Any],
            device_info: Dict[str, Any]) -> str:
        """
        Store a push notification subscription for a device.
        
        Args:
            device_id: The persistent device identifier
            user_id: The user's unique identifier (if logged in) or None
            subscription_data: The subscription object from browser's pushManager.subscribe()
            device_info: Device information (browser, platform, etc.)
        
        Returns:
            subscription_id: Unique identifier for this subscription
        """
        if not device_id or not subscription_data:
            raise ValidationError("Device ID and subscription data are required")

        # Validate subscription data structure
        if not isinstance(subscription_data, dict):
            raise ValidationError("Subscription data must be a dictionary")

        endpoint = subscription_data.get("endpoint")
        keys = subscription_data.get("keys", {})

        if not endpoint:
            raise ValidationError("Subscription must have an endpoint")

        if not keys.get("p256dh") or not keys.get("auth"):
            raise ValidationError("Subscription must have p256dh and auth keys")

        # Generate a unique subscription ID based on device and endpoint
        subscription_identifier = f"{device_id}:{endpoint}:{keys.get('p256dh', '')}:{keys.get('auth', '')}"
        subscription_id = hashlib.md5(subscription_identifier.encode()).hexdigest()

        # Default notification preferences for new devices
        default_preferences = {
            "album_created": True,
            "crew_member_added": True,
            "meme_uploaded": True,
            "system_announcements": True
        }

        # Store subscription data with device info
        subscription_key = f"push_subscription:{subscription_id}"
        subscription_with_metadata = {
            **subscription_data,
            "subscription_id": subscription_id,
            "device_id": device_id,
            "user_id": user_id or "anonymous",
            "created_at": datetime.now().isoformat(),
            "last_used": None,
            "browser_name": device_info.get("browserName", "unknown"),
            "platform": device_info.get("platform", "unknown"),
            "user_agent": device_info.get("userAgent", "")[:200],  # Truncate
            "notification_preferences": json.dumps(default_preferences)
        }

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Store the subscription
        pipe.set(subscription_key, json.dumps(subscription_with_metadata))

        # Store device subscription (one subscription per device)
        pipe.set(f"device:{device_id}:subscription", json.dumps(subscription_with_metadata))

        # Add to global subscription index
        pipe.sadd("all_subscriptions", subscription_id)

        # Associate with user if logged in
        if user_id:
            pipe.sadd(f"user:{user_id}:devices", device_id)
            pipe.set(f"device:{device_id}:user", user_id)

        # Reverse lookup: subscription -> device
        pipe.set(f"subscription:{subscription_id}:device", device_id)

        # Execute all operations
        pipe.execute()

        logger.info(
            f"Stored push subscription {subscription_id} for device {device_id[:15]}... user {user_id or 'anonymous'}")
        return subscription_id

    async def get_device_push_subscription(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get the push subscription for a specific device"""
        if not device_id:
            return None

        subscription_data = self.redis.get(f"device:{device_id}:subscription")
        if not subscription_data:
            return None

        try:
            return json.loads(subscription_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse device subscription data for {device_id}")
            return None

    async def get_user_device_subscriptions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all device push subscriptions for a user"""
        if not user_id:
            return []

        # Get all device IDs for the user
        device_ids = list(self.redis.smembers(f"user:{user_id}:devices"))
        if not device_ids:
            return []

        # Get subscription for each device
        subscriptions = []
        for device_id in device_ids:
            subscription = await self.get_device_push_subscription(device_id)
            if subscription:
                subscriptions.append(subscription)

        return subscriptions

    async def get_all_device_push_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all device push subscriptions"""
        subscription_ids = list(self.redis.smembers("all_subscriptions"))
        if not subscription_ids:
            return []

        subscriptions = []
        for subscription_id in subscription_ids:
            subscription = await self.get_push_subscription(subscription_id)
            if subscription:
                subscriptions.append(subscription)

        return subscriptions

    async def delete_device_push_subscription(self, device_id: str) -> bool:
        """Delete a device's push subscription"""
        if not device_id:
            return False

        # Get the subscription to find the subscription_id
        subscription = await self.get_device_push_subscription(device_id)
        if not subscription:
            return False

        subscription_id = subscription.get("subscription_id")
        user_id = subscription.get("user_id")

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Remove subscription
        pipe.delete(f"push_subscription:{subscription_id}")
        pipe.delete(f"device:{device_id}:subscription")
        pipe.delete(f"subscription:{subscription_id}:device")

        # Remove from global index
        pipe.srem("all_subscriptions", subscription_id)

        # Remove device from user's devices if user exists
        if user_id and user_id != "anonymous":
            pipe.srem(f"user:{user_id}:devices", device_id)
            pipe.delete(f"device:{device_id}:user")

        # Execute all operations
        pipe.execute()

        logger.info(f"Deleted push subscription for device {device_id[:15]}...")
        return True

    async def update_device_notification_preferences(self, device_id: str, preferences: Dict[str, bool]) -> bool:
        """Update notification preferences for a specific device"""
        if not device_id or not preferences:
            return False

        # Get the current subscription to update
        subscription = await self.get_device_push_subscription(device_id)
        if not subscription:
            return False

        subscription_id = subscription.get("subscription_id")
        if not subscription_id:
            return False

        # Update the subscription data with new preferences
        subscription["notification_preferences"] = json.dumps(preferences)

        pipe = self.redis.pipeline()

        # Store as JSON string (compatible with existing format)
        pipe.set(f"push_subscription:{subscription_id}", json.dumps(subscription))
        pipe.set(f"device:{device_id}:subscription", json.dumps(subscription))

        pipe.execute()

        logger.info(f"Updated notification preferences for device {device_id[:15]}...")
        return True

    async def get_device_notification_preferences(self, device_id: str) -> Dict[str, bool]:
        """Get notification preferences for a specific device"""
        if not device_id:
            return {}

        subscription = await self.get_device_push_subscription(device_id)
        if not subscription:
            return {}

        preferences_json = subscription.get("notification_preferences", "{}")
        try:
            return json.loads(preferences_json)
        except json.JSONDecodeError:
            # Return default preferences if parsing fails
            return {
                "album_created": True,
                "crew_member_added": True,
                "meme_uploaded": True,
                "system_announcements": True
            }

    async def get_push_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Get a push subscription by ID"""
        if not subscription_id:
            return None

        subscription_key = f"push_subscription:{subscription_id}"
        subscription_data = self.redis.get(subscription_key)

        if not subscription_data:
            return None

        try:
            return json.loads(subscription_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse subscription data for {subscription_id}")
            return None

    async def get_session_push_subscriptions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all push subscriptions for a browser session"""
        if not session_id:
            return []

        # Get all subscription IDs for the session
        subscription_ids = list(self.redis.smembers(f"session_subscriptions:{session_id}"))

        if not subscription_ids:
            return []

        # Get all subscription data
        subscriptions = []
        for subscription_id in subscription_ids:
            subscription = await self.get_push_subscription(subscription_id)
            if subscription:
                # Add the subscription_id to the subscription data
                subscription["subscription_id"] = subscription_id
                subscriptions.append(subscription)

        return subscriptions

    async def get_user_push_subscriptions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all push subscriptions for a user (across all their sessions)"""
        if not user_id:
            return []

        # Get all subscription IDs for the user
        subscription_ids = list(self.redis.smembers(f"user_subscriptions:{user_id}"))

        if not subscription_ids:
            return []

        # Get all subscription data
        subscriptions = []
        for subscription_id in subscription_ids:
            subscription = await self.get_push_subscription(subscription_id)
            if subscription:
                # Add the subscription_id to the subscription data
                subscription["subscription_id"] = subscription_id
                subscriptions.append(subscription)

        return subscriptions

    async def delete_push_subscription(self, subscription_id: str) -> bool:
        """Delete a push subscription"""
        if not subscription_id:
            return False

        # Get subscription to find session_id and user_id
        subscription = await self.get_push_subscription(subscription_id)
        if not subscription:
            return False

        session_id = subscription.get("session_id")
        user_id = subscription.get("user_id")

        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()

        # Delete the subscription
        pipe.delete(f"push_subscription:{subscription_id}")

        # Remove from session's subscription index
        if session_id:
            pipe.srem(f"session_subscriptions:{session_id}", subscription_id)

        # Remove from user's subscription index
        if user_id:
            pipe.srem(f"user_subscriptions:{user_id}", subscription_id)

        # Remove from global subscription index
        pipe.srem("all_subscriptions", subscription_id)

        # Execute all operations
        results = pipe.execute()

        success = results[0] > 0  # First operation (delete) should return 1 if successful
        if success:
            logger.info(f"Deleted push subscription {subscription_id}")

        return success

    async def get_all_push_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all push subscriptions in the system"""
        subscription_ids = list(self.redis.smembers("all_subscriptions"))

        if not subscription_ids:
            return []

        subscriptions = []
        for subscription_id in subscription_ids:
            subscription = await self.get_push_subscription(subscription_id)
            if subscription:
                # Add the subscription_id to the subscription data
                subscription["subscription_id"] = subscription_id
                subscriptions.append(subscription)

        return subscriptions

    async def update_subscription_last_used(self, subscription_id: str) -> None:
        """Update the last_used timestamp for a subscription"""
        subscription = await self.get_push_subscription(subscription_id)
        if not subscription:
            return

        subscription["last_used"] = datetime.now().isoformat()
        subscription_key = f"push_subscription:{subscription_id}"
        self.redis.set(subscription_key, json.dumps(subscription))

    async def cleanup_expired_subscriptions(self) -> int:
        """
        Clean up expired push subscriptions.
        
        Returns:
            Number of subscriptions cleaned up
        """
        all_subscriptions = await self.get_all_push_subscriptions()
        cleaned_count = 0

        for subscription in all_subscriptions:
            expiration_time = subscription.get("expirationTime")
            if expiration_time and expiration_time < datetime.now().timestamp() * 1000:
                # Subscription has expired
                subscription_id = subscription.get("subscription_id")
                if subscription_id and await self.delete_push_subscription(subscription_id):
                    cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} expired push subscriptions")

        return cleaned_count

    async def cleanup_session_subscriptions(self, session_id: str) -> int:
        """
        Clean up all subscriptions for a specific session (e.g., on logout).
        
        Args:
            session_id: The session ID to clean up
            
        Returns:
            Number of subscriptions cleaned up
        """
        if not session_id:
            return 0

        subscription_ids = list(self.redis.smembers(f"session_subscriptions:{session_id}"))
        cleaned_count = 0

        for subscription_id in subscription_ids:
            if await self.delete_push_subscription(subscription_id):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} push subscriptions for session {session_id[:8]}...")

        return cleaned_count

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
