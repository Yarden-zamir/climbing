#!/usr/bin/env python3
"""
Migration script to transfer all existing file-based data to Redis.
Run this once to migrate from files to Redis datastore.
"""

import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List
import sys
import os

from redis_store import RedisDataStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataMigrator:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_store = RedisDataStore(host=redis_host, port=redis_port)
        self.errors = []

    async def migrate_all(self, dry_run=False) -> bool:
        """Migrate all data from files to Redis"""
        logger.info(f"Starting migration (dry_run={dry_run})")

        try:
            # Health check Redis first
            health = await self.redis_store.health_check()
            if health["status"] != "healthy":
                logger.error(f"Redis not healthy: {health}")
                return False

            logger.info("✅ Redis connection healthy")

            if not dry_run:
                # Clear existing data
                logger.warning("Clearing existing Redis data...")
                await self.redis_store.clear_all_data()

            # Migration steps
            success = True

            # 1. Migrate climbers
            logger.info("🔄 Migrating climbers...")
            climbers_migrated = await self.migrate_climbers(dry_run)
            success = success and climbers_migrated

            # 2. Migrate albums
            logger.info("🔄 Migrating albums...")
            albums_migrated = await self.migrate_albums(dry_run)
            success = success and albums_migrated

            # 3. Migrate meme images
            logger.info("🔄 Migrating meme images...")
            memes_migrated = await self.migrate_memes(dry_run)
            success = success and memes_migrated

            # 4. Calculate new climbers
            if not dry_run:
                logger.info("🔄 Calculating new climbers...")
                new_climbers = await self.redis_store.calculate_new_climbers()
                logger.info(f"✅ Identified {len(new_climbers)} new climbers")

            if success:
                logger.info("🎉 Migration completed successfully!")

                # Print summary
                if not dry_run:
                    await self.print_migration_summary()

            else:
                logger.error(f"❌ Migration completed with {len(self.errors)} errors")
                for error in self.errors:
                    logger.error(f"  - {error}")

            return success

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False

    async def migrate_climbers(self, dry_run=False) -> bool:
        """Migrate climber data from directories to Redis"""
        climbers_dir = Path("climbers")

        if not climbers_dir.exists():
            logger.warning("No climbers directory found")
            return True

        success = True
        climber_count = 0

        for climber_dir in climbers_dir.iterdir():
            if not climber_dir.is_dir():
                continue

            climber_name = climber_dir.name
            details_file = climber_dir / "details.json"
            face_file = climber_dir / "face.png"

            try:
                # Read climber details
                if details_file.exists():
                    with open(details_file, 'r') as f:
                        details = json.load(f)
                else:
                    details = {}

                location = details.get("location", [])
                skills = details.get("skills", [])
                tags = details.get("tags", [])

                logger.info(f"  📝 {climber_name}: {len(skills)} skills, {len(location)} locations")

                if not dry_run:
                    # Add climber to Redis
                    await self.redis_store.add_climber(
                        name=climber_name,
                        location=location,
                        skills=skills,
                        tags=tags
                    )

                # Migrate face image
                if face_file.exists():
                    with open(face_file, 'rb') as f:
                        image_data = f.read()

                    if not dry_run:
                        await self.redis_store.store_image(
                            "climber",
                            f"{climber_name}/face",
                            image_data
                        )

                    logger.info(f"    🖼️  Face image: {len(image_data)} bytes")

                climber_count += 1

            except Exception as e:
                error_msg = f"Failed to migrate climber {climber_name}: {e}"
                logger.error(error_msg)
                self.errors.append(error_msg)
                success = False

        logger.info(f"✅ Migrated {climber_count} climbers")
        return success

    async def migrate_albums(self, dry_run=False) -> bool:
        """Migrate albums from albums.json to Redis"""
        albums_file = Path("static/albums.json")

        if not albums_file.exists():
            logger.warning("No albums.json file found")
            return True

        try:
            with open(albums_file, 'r') as f:
                albums_data = json.load(f)

            album_count = 0

            # albums_data is a dict with URL keys and crew/metadata values
            for album_url, album_info in albums_data.items():
                try:
                    crew = album_info.get("crew", [])

                    # Basic metadata (we'll fetch rich metadata later if needed)
                    metadata = {
                        "title": album_info.get("title", ""),
                        "description": album_info.get("description", ""),
                        "date": album_info.get("date", ""),
                        "imageUrl": album_info.get("imageUrl", ""),
                        "cover_image": album_info.get("cover_image", "")
                    }

                    logger.info(f"  📸 Album: {album_url} - Crew: {crew}")

                    if not dry_run:
                        await self.redis_store.add_album(album_url, crew, metadata)

                    album_count += 1

                except Exception as e:
                    error_msg = f"Failed to migrate album {album_url}: {e}"
                    logger.error(error_msg)
                    self.errors.append(error_msg)

            logger.info(f"✅ Migrated {album_count} albums")
            return True

        except Exception as e:
            error_msg = f"Failed to read albums.json: {e}"
            logger.error(error_msg)
            self.errors.append(error_msg)
            return False

    async def migrate_memes(self, dry_run=False) -> bool:
        """Migrate meme images from static/photos to Redis"""
        photos_dir = Path("static/photos")

        if not photos_dir.exists():
            logger.warning("No photos directory found")
            return True

        success = True
        meme_count = 0

        # Common image extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

        for image_file in photos_dir.iterdir():
            if not image_file.is_file():
                continue

            if image_file.suffix.lower() not in image_extensions:
                continue

            try:
                with open(image_file, 'rb') as f:
                    image_data = f.read()

                # Use filename as identifier
                image_name = image_file.name

                logger.info(f"  🎭 Meme: {image_name} ({len(image_data)} bytes)")

                if not dry_run:
                    await self.redis_store.store_image(
                        "meme",
                        image_name,
                        image_data
                    )

                meme_count += 1

            except Exception as e:
                error_msg = f"Failed to migrate meme {image_file.name}: {e}"
                logger.error(error_msg)
                self.errors.append(error_msg)
                success = False

        logger.info(f"✅ Migrated {meme_count} meme images")
        return success

    async def print_migration_summary(self):
        """Print migration summary"""
        logger.info("📊 Migration Summary:")

        # Get stats from Redis
        health = await self.redis_store.health_check()

        logger.info(f"  Total Albums: {health.get('total_albums', 0)}")
        logger.info(f"  Total Climbers: {health.get('total_climbers', 0)}")
        logger.info(f"  Total Skills: {health.get('total_skills', 0)}")
        logger.info(f"  Redis Memory: {health.get('used_memory_human', 'Unknown')}")

        # Get new climbers
        new_climbers = await self.redis_store.calculate_new_climbers()
        logger.info(f"  New Climbers: {len(new_climbers)}")

        if new_climbers:
            logger.info(f"    {', '.join(new_climbers)}")

    async def verify_migration(self) -> bool:
        """Verify the migration was successful"""
        logger.info("🔍 Verifying migration...")

        try:
            # Check basic data
            all_climbers = await self.redis_store.get_all_climbers()
            all_albums = await self.redis_store.get_all_albums()

            logger.info(f"✅ Found {len(all_climbers)} climbers in Redis")
            logger.info(f"✅ Found {len(all_albums)} albums in Redis")

            # Check some climbers have images
            climbers_with_images = 0
            for climber in all_climbers[:5]:  # Check first 5
                image_data = await self.redis_store.get_image("climber", f"{climber['name']}/face")
                if image_data:
                    climbers_with_images += 1

            logger.info(f"✅ {climbers_with_images}/{min(5, len(all_climbers))} sample climbers have face images")

            # Check albums have crew
            albums_with_crew = sum(1 for album in all_albums if album.get("crew"))
            logger.info(f"✅ {albums_with_crew}/{len(all_albums)} albums have crew data")

            return True

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False


async def main():
    """Main migration function"""
    import argparse

    parser = argparse.ArgumentParser(description='Migrate climbing app data to Redis')
    parser.add_argument('--dry-run', action='store_true', help='Run migration without making changes')
    parser.add_argument('--redis-host', default='localhost', help='Redis host')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis port')
    parser.add_argument('--verify-only', action='store_true', help='Only verify existing migration')

    args = parser.parse_args()

    try:
        migrator = DataMigrator(redis_host=args.redis_host, redis_port=args.redis_port)

        if args.verify_only:
            success = await migrator.verify_migration()
        else:
            success = await migrator.migrate_all(dry_run=args.dry_run)

            # Verify after migration
            if success and not args.dry_run:
                await migrator.verify_migration()

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
