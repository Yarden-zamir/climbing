import asyncio
import logging
import httpx
from utils.metadata_parser import fetch_url, parse_meta_tags

logger = logging.getLogger("climbing_app")


async def perform_album_metadata_refresh(redis_store):
    """Perform album metadata refresh - can be called manually or automatically"""
    logger.info("🔄 Starting album metadata refresh...")

    # Get all albums from Redis
    albums = await redis_store.get_all_albums()

    if not albums:
        logger.info("No albums found to refresh")
        return {"updated": 0, "errors": 0, "message": "No albums found to refresh"}

    updated_count = 0
    error_count = 0

    # Refresh metadata for each album
    async with httpx.AsyncClient(timeout=30.0) as client:
        for album in albums:
            try:
                url = album["url"]

                # Fetch fresh metadata from Google Photos
                response = await fetch_url(client, url)
                fresh_metadata = parse_meta_tags(response.text, url)

                # Update Redis with fresh metadata
                await redis_store.update_album_metadata(url, fresh_metadata)
                updated_count += 1

                # Small delay to avoid overwhelming Google Photos
                await asyncio.sleep(0.5)

            except Exception as e:
                error_count += 1
                logger.warning(f"Failed to refresh metadata for {album.get('url', 'unknown')}: {e}")
                continue

    logger.info(f"✅ Album metadata refresh completed: {updated_count} updated, {error_count} errors")
    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Refresh completed: {updated_count} updated, {error_count} errors"
    }


async def refresh_album_metadata(redis_store):
    """Background task to refresh album metadata from Google Photos once per day"""
    while True:
        try:
            # Wait 24 hours between refreshes (once per day)
            await asyncio.sleep(60*60*24)

            await perform_album_metadata_refresh(redis_store)

        except Exception as e:
            logger.error(f"❌ Album metadata refresh task failed: {e}")
            # Continue the loop even if there's an error
            continue 