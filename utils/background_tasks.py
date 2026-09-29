import asyncio
import logging
from pathlib import Path

import httpx
from utils.metadata_parser import parse_meta_tags

logger = logging.getLogger("climbing_app")

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds
BACKOFF_MULTIPLIER = 2
RETRYABLE_STATUS_CODES = {502, 503, 504, 429}


async def fetch_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Fetch URL with exponential backoff for transient errors (504, 502, 503, 429, timeouts)."""
    last_exception = None
    backoff = INITIAL_BACKOFF

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            if e.response.status_code in RETRYABLE_STATUS_CODES:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"Got {e.response.status_code} for {url}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exception = e
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Timeout/connection error for {url}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
            continue

    raise last_exception or Exception(f"Failed to fetch {url} after {MAX_RETRIES} attempts")


async def perform_album_metadata_refresh(store):
    """Perform album metadata refresh - can be called manually or automatically"""
    logger.info("🔄 Starting album metadata refresh...")

    # Get all albums from the store
    albums = await store.get_all_albums()

    if not albums:
        logger.info("No albums found to refresh")
        return {"updated": 0, "errors": 0, "message": "No albums found to refresh"}

    updated_count = 0
    error_count = 0
    skipped_count = 0

    # Longer timeout for metadata fetching, with connect/read/write timeouts
    timeout = httpx.Timeout(60.0, connect=10.0)

    # Refresh metadata for each album
    async with httpx.AsyncClient(timeout=timeout) as client:
        for album in albums:
            try:
                url = album["url"]

                # Fetch fresh metadata from Google Photos with retry logic
                response = await fetch_with_retry(client, url)
                fresh_metadata = parse_meta_tags(response.text, url)

                # Update the store with fresh metadata
                await store.update_album_metadata(url, fresh_metadata)
                updated_count += 1

                # Small delay to avoid overwhelming Google Photos
                await asyncio.sleep(0.5)

            except Exception as e:
                error_count += 1
                error_msg = str(e)
                # Truncate long error messages
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."
                logger.warning(f"Failed to refresh metadata for {album.get('url', 'unknown')}: {error_msg}")

                # Longer delay after errors to avoid rate limiting
                await asyncio.sleep(2.0)
                continue

    logger.info(f"✅ Album metadata refresh completed: {updated_count} updated, {error_count} errors, {skipped_count} skipped")
    return {
        "updated": updated_count,
        "errors": error_count,
        "skipped": skipped_count,
        "message": f"Refresh completed: {updated_count} updated, {error_count} errors"
    }


async def refresh_album_metadata(store):
    """Background task to refresh album metadata from Google Photos once per day"""
    while True:
        try:
            # Wait 24 hours between refreshes (once per day)
            await asyncio.sleep(60*60*24)

            await perform_album_metadata_refresh(store)

        except Exception as e:
            logger.error(f"❌ Album metadata refresh task failed: {e}")
            # Continue the loop even if there's an error
            continue


async def backup_database(store, directory: Path):
    """Snapshot the database once a day and drop expired temporary images."""
    while True:
        try:
            path = await asyncio.to_thread(store.backup, directory)
            logger.info(f"💾 Database backed up to {path}")
            store.purge_expired_images()
            await asyncio.sleep(60 * 60 * 24)
        except Exception as e:
            logger.error(f"❌ Database backup failed: {e}")
            await asyncio.sleep(60 * 60)
 