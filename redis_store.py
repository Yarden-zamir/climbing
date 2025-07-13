import redis
import json
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Any
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RedisDataStore:
    def __init__(self, host='localhost', port=6379, db=0):
        """Initialize Redis connections"""
        try:
            # Text data connection (decode_responses=True for strings)
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_timeout=5,
                health_check_interval=30
            )

            # Binary data connection for images (decode_responses=False for bytes)
            self.binary_redis = redis.Redis(
                host=host,
                port=port,
                db=db + 1,
                decode_responses=False,
                socket_timeout=5,
                health_check_interval=30
            )

            # Test connections
            self.redis.ping()
            self.binary_redis.ping()
            logger.info("Redis connections established successfully")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    # === ALBUMS ===

    async def add_album(self, url: str, crew: List[str], metadata: Dict = None) -> None:
        """Add a new album with crew and metadata"""
        album_key = f"album:{url}"

        # Prepare album data
        album_data = {
            "url": url,
            "crew": json.dumps(crew),
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

        # Store album
        self.redis.hset(album_key, mapping=album_data)

        # Update indexes
        self.redis.sadd("index:albums:all", url)

        # Index by crew members
        for crew_member in crew:
            self.redis.sadd(f"index:albums:crew:{crew_member}", url)

        # Update climb counts for crew members
        for crew_member in crew:
            self.redis.hincrby(f"climber:{crew_member}", "climbs", 1)
            # Recalculate level
            await self._recalculate_climber_level(crew_member)

        logger.info(f"Added album: {url} with crew: {crew}")

    async def get_album(self, url: str) -> Optional[Dict]:
        """Get album by URL"""
        album_key = f"album:{url}"
        album_data = self.redis.hgetall(album_key)

        if not album_data:
            return None

        # Parse crew data
        album_data["crew"] = json.loads(album_data.get("crew", "[]"))
        return album_data

    async def get_all_albums(self) -> List[Dict]:
        """Get all albums with metadata"""
        album_urls = self.redis.smembers("index:albums:all")
        albums = []

        for url in album_urls:
            album_data = self.redis.hgetall(f"album:{url}")
            if album_data:
                album_data["crew"] = json.loads(album_data.get("crew", "[]"))
                albums.append(album_data)

        # Sort by album date (newest climbing dates first)
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

        albums.sort(key=lambda x: parse_album_date_for_sort(x.get("date", "")), reverse=True)
        return albums

    async def get_albums_by_crew(self, crew_member: str) -> List[Dict]:
        """Get all albums featuring a specific crew member"""
        album_urls = self.redis.smembers(f"index:albums:crew:{crew_member}")
        albums = []

        for url in album_urls:
            album_data = self.redis.hgetall(f"album:{url}")
            if album_data:
                album_data["crew"] = json.loads(album_data.get("crew", "[]"))
                albums.append(album_data)

        return albums

    async def update_album_crew(self, url: str, new_crew: List[str]) -> None:
        """Update album crew members"""
        album_key = f"album:{url}"

        # Get current crew
        old_album = await self.get_album(url)
        if not old_album:
            raise ValueError(f"Album not found: {url}")

        old_crew = old_album["crew"]

        # Update album
        self.redis.hset(album_key, mapping={
            "crew": json.dumps(new_crew),
            "updated_at": datetime.now().isoformat()
        })

        # Update crew indexes
        # Remove from old crew member indexes
        for crew_member in old_crew:
            self.redis.srem(f"index:albums:crew:{crew_member}", url)
            # Decrease climb count
            current_climbs = int(self.redis.hget(f"climber:{crew_member}", "climbs") or 0)
            if current_climbs > 0:
                self.redis.hset(f"climber:{crew_member}", "climbs", current_climbs - 1)
                await self._recalculate_climber_level(crew_member)

        # Add to new crew member indexes
        for crew_member in new_crew:
            self.redis.sadd(f"index:albums:crew:{crew_member}", url)
            self.redis.hincrby(f"climber:{crew_member}", "climbs", 1)
            await self._recalculate_climber_level(crew_member)

    async def update_album_metadata(self, url: str, metadata: Dict) -> None:
        """Update album metadata without changing crew data"""
        album_key = f"album:{url}"

        # Check if album exists
        if not self.redis.exists(album_key):
            raise ValueError(f"Album not found: {url}")

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
        """Delete an album"""
        album = await self.get_album(url)
        if not album:
            return False

        # Remove from crew indexes
        for crew_member in album["crew"]:
            self.redis.srem(f"index:albums:crew:{crew_member}", url)
            # Decrease climb count
            current_climbs = int(self.redis.hget(f"climber:{crew_member}", "climbs") or 0)
            if current_climbs > 0:
                self.redis.hset(f"climber:{crew_member}", "climbs", current_climbs - 1)
                await self._recalculate_climber_level(crew_member)

        # Remove from main index
        self.redis.srem("index:albums:all", url)

        # Delete album data
        self.redis.delete(f"album:{url}")

        logger.info(f"Deleted album: {url}")
        return True

    # === CLIMBERS ===

    async def add_climber(
        self, name: str, location: List[str]=None, skills: List[str]=None, tags: List[str]=None,
        achievements: List[str]=None) ->None:
        """Add a new climber"""
        climber_key = f"climber:{name}"

        # Check if climber already exists
        if self.redis.exists(climber_key):
            raise ValueError(f"Climber already exists: {name}")

        location = location or []
        skills = skills or []
        tags = tags or []
        achievements = achievements or []

        # Calculate initial level
        level_from_skills = len(skills)
        level_from_climbs = 0  # New climber starts with 0 climbs
        total_level = 1 + level_from_skills + level_from_climbs

        climber_data = {
            "name": name,
            "location": json.dumps(location),
            "skills": json.dumps(skills),
            "tags": json.dumps(tags),
            "achievements": json.dumps(achievements),
            "level": str(total_level),
            "level_from_skills": str(level_from_skills),
            "level_from_climbs": str(level_from_climbs),
            "climbs": "0",
            "is_new": "true",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Store climber
        self.redis.hset(climber_key, mapping=climber_data)

        # Update indexes
        self.redis.sadd("index:climbers:all", name)
        self.redis.sadd("index:climbers:new", name)

        # Index skills
        for skill in skills:
            self.redis.sadd("index:skills:all", skill)
            self.redis.sadd(f"index:climbers:skill:{skill}", name)

        # Index tags
        for tag in tags:
            self.redis.sadd("index:tags:all", tag)
            self.redis.sadd(f"index:climbers:tag:{tag}", name)

        # Index achievements
        for achievement in achievements:
            self.redis.sadd("index:achievements:all", achievement)
            self.redis.sadd(f"index:climbers:achievement:{achievement}", name)

        logger.info(f"Added climber: {name}")

    async def get_climber(self, name: str) -> Optional[Dict]:
        """Get climber by name"""
        climber_key = f"climber:{name}"
        climber_data = self.redis.hgetall(climber_key)

        if not climber_data:
            return None

        # Parse JSON fields
        climber_data["location"] = json.loads(climber_data.get("location", "[]"))
        climber_data["skills"] = json.loads(climber_data.get("skills", "[]"))
        climber_data["tags"] = json.loads(climber_data.get("tags", "[]"))
        climber_data["achievements"] = json.loads(climber_data.get("achievements", "[]"))

        # Convert numeric fields
        climber_data["level"] = int(climber_data.get("level", "1"))
        climber_data["level_from_skills"] = int(climber_data.get("level_from_skills", "0"))
        climber_data["level_from_climbs"] = int(climber_data.get("level_from_climbs", "0"))
        climber_data["climbs"] = int(climber_data.get("climbs", "0"))
        climber_data["is_new"] = climber_data.get("is_new", "false") == "true"

        return climber_data

    async def get_all_climbers(self) -> List[Dict]:
        """Get all climbers"""
        climber_names = self.redis.smembers("index:climbers:all")
        climbers = []

        for name in climber_names:
            climber_data = await self.get_climber(name)
            if climber_data:
                # Add face image path
                climber_data["face"] = f"/redis-image/climber/{name}/face"
                climbers.append(climber_data)

        # Sort by level (highest first), then by name
        climbers.sort(key=lambda x: (-x["level"], x["name"]))
        return climbers

    async def update_climber(self, original_name: str, name: str = None, location: List[str] = None,
                             skills: List[str] = None, tags: List[str] = None, achievements: List[str] = None) -> None:
        """Update climber information"""
        original_key = f"climber:{original_name}"

        # Get current climber data
        current_climber = await self.get_climber(original_name)
        if not current_climber:
            raise ValueError(f"Climber not found: {original_name}")

        name = name or original_name
        location = location if location is not None else current_climber["location"]
        skills = skills if skills is not None else current_climber["skills"]
        tags = tags if tags is not None else current_climber["tags"]
        achievements = achievements if achievements is not None else current_climber["achievements"]

        # Handle name change
        name_changed = original_name != name
        new_key = f"climber:{name}"

        if name_changed and self.redis.exists(new_key):
            raise ValueError(f"Climber name already exists: {name}")

        # Calculate new level
        level_from_skills = len(skills)
        current_climbs = current_climber["climbs"]
        level_from_climbs = current_climbs // 5
        total_level = 1 + level_from_skills + level_from_climbs

        # Prepare updated data
        updated_data = {
            "name": name,
            "location": json.dumps(location),
            "skills": json.dumps(skills),
            "tags": json.dumps(tags),
            "achievements": json.dumps(achievements),
            "level": str(total_level),
            "level_from_skills": str(level_from_skills),
            "level_from_climbs": str(level_from_climbs),
            "climbs": str(current_climbs),
            "is_new": "true" if current_climber.get("is_new", False) else "false",
            "created_at": current_climber.get("created_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat()
        }

        if name_changed:
            # Create new record
            self.redis.hset(new_key, mapping=updated_data)

            # Update indexes
            self.redis.srem("index:climbers:all", original_name)
            self.redis.sadd("index:climbers:all", name)

            # Update album crew references
            album_urls = self.redis.smembers(f"index:albums:crew:{original_name}")
            for url in album_urls:
                album = await self.get_album(url)
                if album:
                    new_crew = [name if member == original_name else member for member in album["crew"]]
                    self.redis.hset(f"album:{url}", "crew", json.dumps(new_crew))

                    # Update crew indexes
                    self.redis.srem(f"index:albums:crew:{original_name}", url)
                    self.redis.sadd(f"index:albums:crew:{name}", url)

            # Move image if exists
            old_image = self.binary_redis.get(f"image:climber:{original_name}:face")
            if old_image:
                self.binary_redis.set(f"image:climber:{name}:face", old_image)
                self.binary_redis.delete(f"image:climber:{original_name}:face")

            # Delete old record
            self.redis.delete(original_key)

        else:
            # Update existing record
            self.redis.hset(original_key, mapping=updated_data)

        # Update skill indexes
        # Remove from old skill indexes
        for skill in current_climber["skills"]:
            self.redis.srem(f"index:climbers:skill:{skill}", original_name)

        # Add to new skill indexes
        for skill in skills:
            self.redis.sadd("index:skills:all", skill)
            self.redis.sadd(f"index:climbers:skill:{skill}", name)

        # Update tag indexes
        # Remove from old tag indexes
        for tag in current_climber["tags"]:
            self.redis.srem(f"index:climbers:tag:{tag}", original_name)

        # Add to new tag indexes
        for tag in tags:
            self.redis.sadd("index:tags:all", tag)
            self.redis.sadd(f"index:climbers:tag:{tag}", name)

        # Update achievement indexes
        # Remove from old achievement indexes
        for achievement in current_climber["achievements"]:
            self.redis.srem(f"index:climbers:achievement:{achievement}", original_name)

        # Add to new achievement indexes
        for achievement in achievements:
            self.redis.sadd("index:achievements:all", achievement)
            self.redis.sadd(f"index:climbers:achievement:{achievement}", name)

        logger.info(f"Updated climber: {original_name} -> {name}")

    async def delete_climber(self, name: str) -> bool:
        """Delete a climber"""
        climber = await self.get_climber(name)
        if not climber:
            return False

        # Remove from all albums
        album_urls = self.redis.smembers(f"index:albums:crew:{name}")
        for url in album_urls:
            album = await self.get_album(url)
            if album:
                new_crew = [member for member in album["crew"] if member != name]
                await self.update_album_crew(url, new_crew)

        # Remove from indexes
        self.redis.srem("index:climbers:all", name)
        self.redis.srem("index:climbers:new", name)

        # Remove from skill indexes
        for skill in climber["skills"]:
            self.redis.srem(f"index:climbers:skill:{skill}", name)

        # Remove from tag indexes
        for tag in climber["tags"]:
            self.redis.srem(f"index:climbers:tag:{tag}", name)

        # Remove from achievement indexes
        for achievement in climber["achievements"]:
            self.redis.srem(f"index:climbers:achievement:{achievement}", name)

        # Remove image
        self.binary_redis.delete(f"image:climber:{name}:face")

        # Delete climber data
        self.redis.delete(f"climber:{name}")

        logger.info(f"Deleted climber: {name}")
        return True

    async def _recalculate_climber_level(self, name: str) -> None:
        """Recalculate and update climber level"""
        climber = await self.get_climber(name)
        if not climber:
            return

        level_from_skills = len(climber["skills"])
        level_from_climbs = climber["climbs"] // 5
        total_level = 1 + level_from_skills + level_from_climbs

        self.redis.hset(f"climber:{name}", mapping={
            "level": str(total_level),
            "level_from_skills": str(level_from_skills),
            "level_from_climbs": str(level_from_climbs)
        })

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

    # === SKILLS, TAGS & ACHIEVEMENTS ===

    async def get_all_skills(self) -> List[str]:
        """Get all unique skills"""
        skills = self.redis.smembers("index:skills:all")
        return sorted(list(skills))

    async def get_all_tags(self) -> List[str]:
        """Get all unique tags"""
        tags = self.redis.smembers("index:tags:all")
        return sorted(list(tags))

    async def get_all_achievements(self) -> List[str]:
        """Get all unique achievements"""
        achievements = self.redis.smembers("index:achievements:all")
        return sorted(list(achievements))

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

    # === NEW CLIMBERS MANAGEMENT ===

    async def calculate_new_climbers(self) -> Set[str]:
        """Calculate which climbers are new (first participation in last 14 days)"""
        cutoff_date = datetime.now() - timedelta(days=14)

        # Get all albums sorted by date
        albums = await self.get_all_albums()
        new_climbers = set()

        # Process albums chronologically
        albums_with_dates = []
        for album in albums:
            try:
                # Parse album date
                date_str = album.get("date", "")
                if not date_str:
                    continue

                # Simple date parsing - you can enhance this
                # Assumes dates like "Jul 15", "Jan 1", etc.
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

            except Exception as e:
                logger.warning(f"Failed to parse date for album {album.get('url', '')}: {e}")
                continue

        # Sort by date (oldest first)
        albums_with_dates.sort(key=lambda x: x[1])

        # Track first participation
        climber_first_participation = {}

        for album, album_date in albums_with_dates:
            for crew_member in album.get("crew", []):
                if crew_member not in climber_first_participation:
                    climber_first_participation[crew_member] = album_date

        # Find new climbers
        for climber, first_date in climber_first_participation.items():
            if first_date >= cutoff_date:
                new_climbers.add(climber)
                # Mark as new in Redis
                self.redis.hset(f"climber:{climber}", "is_new", "true")
            else:
                # Mark as not new
                self.redis.hset(f"climber:{climber}", "is_new", "false")

        # Update new climbers index
        self.redis.delete("index:climbers:new")
        if new_climbers:
            self.redis.sadd("index:climbers:new", *new_climbers)

        return new_climbers

    # === SESSIONS ===

    async def store_session(self, session_id: str, user_data: Dict, ttl: int = 604800) -> None:
        """Store user session (7 days default)"""
        session_key = f"session:{session_id}"
        self.redis.setex(session_key, ttl, json.dumps(user_data))

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Get user session"""
        session_key = f"session:{session_id}"
        session_data = self.redis.get(session_key)
        return json.loads(session_data) if session_data else None

    async def delete_session(self, session_id: str) -> bool:
        """Delete user session"""
        session_key = f"session:{session_id}"
        return self.redis.delete(session_key) > 0

    # === UTILITY ===

    async def health_check(self) -> Dict[str, Any]:
        """Check Redis health and return stats"""
        try:
            # Test connections
            self.redis.ping()
            self.binary_redis.ping()

            # Get stats
            info = self.redis.info()
            stats = {
                "status": "healthy",
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "total_albums": len(self.redis.smembers("index:albums:all")),
                "total_climbers": len(self.redis.smembers("index:climbers:all")),
                "total_skills": len(self.redis.smembers("index:skills:all"))
            }

            return stats

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    async def clear_all_data(self) -> None:
        """Clear all data - USE WITH CAUTION!"""
        logger.warning("Clearing all Redis data!")
        self.redis.flushdb()
        self.binary_redis.flushdb()
