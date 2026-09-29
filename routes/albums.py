import json
import logging
from typing import Dict, List
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from auth import require_auth_hybrid
from dependencies import get_store, get_permissions_manager
from models.api_models import (
    AlbumCrewEdit,
    AlbumMetadataUpdate,
    AlbumSubmission,
    LearnedItems,
)
from permissions import ResourceType
from store import IMAGE_URL_PREFIX, ValidationError as StoreValidationError
from utils.metadata_parser import fetch_url, parse_meta_tags
from validation import ValidationError, validate_google_photos_url, validate_crew_list
from routes.notifications import send_notification_for_event

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/albums", tags=["albums"])


def _learned_by_name(learned: List[LearnedItems], crew: List[str]) -> Dict[str, LearnedItems]:
    """Index learned items by crew name; reject entries for people not in the album."""
    by_name: Dict[str, LearnedItems] = {}
    for item in learned:
        name = item.name.strip()
        if not item.skills and not item.achievements:
            continue
        if name not in crew:
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' is not in this album's crew, so nothing can be learned there",
            )
        by_name[name] = item
    return by_name


async def _require_learned_permissions(
    permissions_manager, user_id: str, learned: Dict[str, LearnedItems]
) -> None:
    """Learned items modify crew members, so they follow the crew member edit rule."""
    if permissions_manager is None:
        return
    for name in learned:
        try:
            await permissions_manager.require_resource_access(
                user_id, ResourceType.CREW_MEMBER, name, "edit"
            )
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code,
                detail=f"You can't record what {name} learned: {e.detail}",
            )


async def _apply_learned(
    store, album_url: str, learned: Dict[str, LearnedItems]
) -> Dict[str, Dict[str, List[str]]]:
    applied: Dict[str, Dict[str, List[str]]] = {}
    for name, item in learned.items():
        try:
            applied[name] = await store.record_learned_items(
                name, album_url, item.skills, item.achievements
            )
        except StoreValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return applied


@router.get("/enriched")
async def get_enriched_albums():
    """API endpoint that returns all albums with metadata from the store."""
    store = get_store()

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        albums = await store.get_all_albums()
        enriched_albums = []

        # One pass over all climbers instead of one lookup per crew entry
        climbers = {c["name"]: c for c in await store.get_all_climbers()}
        for album in albums:
            # Create enriched metadata with crew status
            crew_with_status = []
            for crew_member in album.get("crew", []):
                climber_data = climbers.get(crew_member)
                is_new = climber_data.get("is_new", False) if climber_data else False

                crew_with_status.append(
                    {
                        "name": crew_member,
                        "is_new": is_new,
                        "image_url": f"{IMAGE_URL_PREFIX}/climber/{quote(crew_member)}/face",
                    }
                )

            enriched_albums.append(
                {
                    "url": album["url"],
                    "metadata": {
                        "title": album.get("title", ""),
                        "description": album.get("description", ""),
                        "date": album.get("date", ""),
                        # Machine-readable climb date; clients must not re-parse the display string
                        "date_iso": album["climb_date"],
                        "created_at": album.get("created_at", ""),
                        "imageUrl": album.get("image_url", ""),
                        "location": album.get("location", ""),
                        "url": album["url"],
                        "crew": crew_with_status,
                    },
                }
            )

        headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=300"}
        return Response(
            content=json.dumps(enriched_albums),
            media_type="application/json",
            headers=headers,
        )

    except Exception as e:
        logger.error(f"Error getting enriched albums: {e}")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve album data. Please try again later.",
        )


@router.get("/validate-url")
async def validate_album_url(url: str = Query(...)):
    """Validate album URL and check if it already exists"""
    store = get_store()

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Validate URL format
        try:
            validated_url = validate_google_photos_url(url)
        except ValidationError as e:
            return JSONResponse({"valid": False, "error": str(e)})

        # Check if album already exists
        existing_album = await store.get_album(validated_url)
        if existing_album:
            return JSONResponse(
                {
                    "valid": True,
                    "exists": True,
                    "title": existing_album.get("title", ""),
                }
            )

        # Try to fetch metadata to validate accessibility
        try:
            async with httpx.AsyncClient() as client:
                response = await fetch_url(client, validated_url)
                metadata = parse_meta_tags(response.text, validated_url)

            return JSONResponse(
                {
                    "valid": True,
                    "exists": False,
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "imageUrl": metadata.get("imageUrl", ""),
                }
            )

        except Exception as e:
            logger.warning(f"Failed to fetch metadata for {validated_url}: {e}")
            return JSONResponse(
                {
                    "valid": True,
                    "exists": False,
                    "title": None,
                    "error": "Could not fetch album metadata",
                }
            )

    except Exception as e:
        logger.error(f"Error validating album URL: {e}")
        return JSONResponse({"valid": False, "error": "Failed to validate URL"})


@router.post("/submit")
async def submit_album(
    submission: AlbumSubmission,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth_hybrid),
):
    """Submit a new album directly to the store (no GitHub).

    Supports both session-based authentication (web) and JWT Bearer token authentication (API).
    """
    store = get_store()
    permissions_manager = get_permissions_manager()

    # Validate album URL format
    try:
        validated_url = validate_google_photos_url(submission.url)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid user session")

        # Check permissions and submission limits if permissions system is available
        if permissions_manager is not None:
            await permissions_manager.require_permission(user_id, "create_album")
            can_create = await permissions_manager.check_submission_limits(
                user_id, ResourceType.ALBUM
            )
            if not can_create:
                raise HTTPException(
                    status_code=403,
                    detail="You have reached your album creation limit. Contact an admin for approval.",
                )

        # Check if album already exists
        existing_album = await store.get_album(validated_url)
        if existing_album:
            raise HTTPException(status_code=409, detail="Album already exists")

        # Learned items only apply to existing crew members (new people pick skills on creation)
        new_names = {p.name.strip() for p in (submission.new_people or [])}
        learned = _learned_by_name(
            submission.learned, [c for c in submission.crew if c not in new_names]
        )
        await _require_learned_permissions(permissions_manager, user_id, learned)

        # Validate crew members exist or create new ones
        new_created_climbers = []
        for crew_name in submission.crew or []:
            # Check if this person is in new_people
            new_person = next(
                (p for p in (submission.new_people or []) if p.name == crew_name), None
            )
            if new_person:
                # Create new climber
                try:
                    await store.add_climber(
                        name=new_person.name,
                        location=new_person.location,
                        skills=new_person.skills,
                        achievements=new_person.achievements,
                    )
                    new_created_climbers.append(new_person)

                    # Handle image if provided
                    if new_person.temp_image_path:
                        # Move the temp image to the climber image
                        temp_image = await store.get_image(
                            "temp", new_person.name
                        )
                        if temp_image:
                            await store.store_image(
                                "climber", f"{new_person.name}/face", temp_image
                            )
                            await store.delete_image("temp", new_person.name)

                except ValueError as e:
                    if "already exists" in str(e):
                        pass  # Climber already exists, continue
                    else:
                        raise
            else:
                # Check if existing crew member exists
                existing_climber = await store.get_climber(crew_name)
                if not existing_climber:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Crew member '{crew_name}' does not exist",
                    )

        # Fetch album metadata
        async with httpx.AsyncClient() as client:
            response = await fetch_url(client, validated_url)
            metadata = parse_meta_tags(response.text, validated_url)

        # Add album to the store
        await store.add_album(
            validated_url, submission.crew, metadata, location=submission.location
        )
        learned_applied = await _apply_learned(store, validated_url, learned)

        # Set resource ownership if permissions system available
        if permissions_manager is not None:
            try:
                await permissions_manager.set_resource_owner(
                    ResourceType.ALBUM, validated_url, user_id
                )
            except Exception as e:
                logger.warning(f"Failed to set resource ownership: {e}")

        # Push delivery is slow (sequential web push with retries); never block the response on it
        background_tasks.add_task(
            send_notification_for_event,
            event_type="album_created",
            event_data={
                "title": metadata.get("title", "New Album"),
                "url": validated_url,
                "crew": submission.crew,
                "creator": user.get("name", "Someone"),
                "image_url": metadata.get("imageUrl"),
            },
            store=store,
            target_users=None,
        )
        for new_person in new_created_climbers:
            background_tasks.add_task(
                send_notification_for_event,
                event_type="crew_member_added",
                event_data={
                    "name": new_person.name,
                    "creator": user.get("name", "Someone"),
                    "skills": new_person.skills,
                    "location": new_person.location,
                    "image_url": f"{IMAGE_URL_PREFIX}/climber/{quote(new_person.name)}/face",
                },
                store=store,
                target_users=None,
            )

        return JSONResponse(
            {
                "success": True,
                "message": f"Album '{metadata.get('title', 'Unknown')}' added successfully!",
                "album_url": validated_url,
                "crew": submission.crew,
                "created_climbers": [p.name for p in new_created_climbers],
                "learned": learned_applied,
            }
        )

    except HTTPException:
        raise
    except StoreValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting album: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit album")


@router.post("/edit-crew")
async def edit_album_crew(
    edit_data: AlbumCrewEdit, user: dict = Depends(require_auth_hybrid)
):
    """Edit crew members for an album.

    Supports both session-based authentication (web) and JWT Bearer token authentication (API).
    """
    store = get_store()
    permissions_manager = get_permissions_manager()

    # Validate album URL format
    try:
        validated_url = validate_google_photos_url(edit_data.album_url)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate crew data
    if not edit_data.crew:
        raise HTTPException(
            status_code=400, detail="At least one crew member is required"
        )

    # Remove duplicates and validate crew names
    try:
        validated_crew = validate_crew_list(edit_data.crew)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if album exists
        existing_album = await store.get_album(validated_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            await permissions_manager.require_resource_access(
                user_id, ResourceType.ALBUM, validated_url, "edit"
            )

        new_names = {p.name.strip() for p in (edit_data.new_people or [])}
        learned = _learned_by_name(
            edit_data.learned, [c for c in validated_crew if c not in new_names]
        )
        await _require_learned_permissions(permissions_manager, user_id, learned)

        # Track created resources for cleanup on failure
        created_climbers = []
        uploaded_images = []

        try:
            # Process new people first
            for person in edit_data.new_people or []:
                validated_name = person.name.strip()
                if not validated_name:
                    continue

                # Check if climber already exists
                existing_climber = await store.get_climber(validated_name)
                if existing_climber:
                    continue  # Skip if already exists

                try:
                    # Create new climber
                    await store.add_climber(
                        name=validated_name,
                        location=person.location or [],
                        skills=person.skills or [],
                        achievements=person.achievements or [],
                    )
                    created_climbers.append(validated_name)

                    # Set ownership if permissions available
                    if permissions_manager is not None:
                        await permissions_manager.set_resource_owner(
                            ResourceType.CREW_MEMBER, validated_name, user_id
                        )

                    # Handle image if provided
                    if person.temp_image_path:
                        temp_image = await store.get_image("temp", validated_name)
                        if temp_image:
                            # Store as climber image
                            await store.store_image("climber", f"{validated_name}/face", temp_image)
                            uploaded_images.append(
                                ("climber", f"{validated_name}/face")
                            )

                            # Clean up temp image
                            await store.delete_image("temp", validated_name)
                        else:
                            logger.warning(
                                f"Temporary image not found for {validated_name}"
                            )

                except ValidationError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid data for {validated_name}: {str(e)}",
                    )
                except Exception as e:
                    logger.error(f"Error creating climber {validated_name}: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create climber {validated_name}",
                    )

            # Validate that all crew members exist
            for crew_member in validated_crew:
                existing_climber = await store.get_climber(crew_member)
                if not existing_climber:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Crew member '{crew_member}' does not exist",
                    )

            # Update album crew (atomic operation)
            await store.update_album_crew(validated_url, validated_crew)
            learned_applied = await _apply_learned(store, validated_url, learned)

            return JSONResponse(
                {
                    "success": True,
                    "message": "Album crew updated successfully!",
                    "album_url": validated_url,
                    "crew": validated_crew,
                    "created_climbers": created_climbers,
                    "learned": learned_applied,
                }
            )

        except Exception as e:
            # Clean up created resources on failure
            logger.error(f"Album crew edit failed, cleaning up: {e}")

            for climber_name in created_climbers:
                try:
                    await store.delete_climber(climber_name)
                except:
                    pass

            for image_type, image_id in uploaded_images:
                try:
                    await store.delete_image(image_type, image_id)
                except:
                    pass

            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing album crew: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/delete")
async def delete_album(
    album_url: str = Query(...), user: dict = Depends(require_auth_hybrid)
):
    """Delete an album from the store."""
    store = get_store()
    permissions_manager = get_permissions_manager()

    # Validate album URL format
    try:
        album_url = validate_google_photos_url(album_url)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if album exists
        existing_album = await store.get_album(album_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Check resource access permissions
        if permissions_manager is not None:
            await permissions_manager.require_resource_access(
                user_id, ResourceType.ALBUM, album_url, "delete"
            )

        # Store album title for response
        album_title = existing_album.get("title", "Unknown Album")

        # Delete the album
        deleted = await store.delete_album(album_url)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete album")

        if permissions_manager is not None:
            await permissions_manager.release_resource(ResourceType.ALBUM, album_url)

        return JSONResponse(
            {
                "success": True,
                "message": f"Album '{album_title}' deleted successfully!",
                "album_url": album_url,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting album: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete album")


@router.post("/edit-metadata")
async def edit_album_metadata(
    update: AlbumMetadataUpdate, user: dict = Depends(require_auth_hybrid)
):
    """Edit album metadata such as title/description/date and location."""
    store = get_store()
    permissions_manager = get_permissions_manager()

    # Validate URL format
    try:
        validated_url = validate_google_photos_url(update.album_url)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not store:
        logger.error("Store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if album exists
        existing_album = await store.get_album(validated_url)
        if not existing_album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Check permissions
        if permissions_manager is not None:
            await permissions_manager.require_resource_access(
                user_id, ResourceType.ALBUM, validated_url, "edit"
            )

        # Build metadata dict from provided fields
        metadata = {
            "title": update.title
            if update.title is not None
            else existing_album.get("title", ""),
            "description": update.description
            if update.description is not None
            else existing_album.get("description", ""),
            "date": update.date
            if update.date is not None
            else existing_album.get("date", ""),
            "imageUrl": existing_album.get("image_url", ""),
            "cover_image": update.cover_image
            if update.cover_image is not None
            else existing_album.get("cover_image", ""),
        }

        await store.update_album_metadata(
            validated_url, metadata, location=update.location
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Album metadata updated successfully!",
                "album_url": validated_url,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing album metadata: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
