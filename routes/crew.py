import logging
from fastapi import APIRouter, HTTPException, Depends, Form, File, UploadFile, Query
from fastapi.responses import JSONResponse

from auth import get_current_user, get_current_user_hybrid, require_auth_hybrid
from dependencies import get_redis_store, get_permissions_manager
from models.api_models import AddSkillsRequest, AddAchievementsRequest
from permissions import ResourceType
from validation import (
    ValidationError, validate_crew_form_data, validate_crew_edit_form_data,
    validate_optional_image_upload, validate_image_file, validate_name,
    validate_form_json_field, validate_skill_list, validate_location_list,
    validate_achievements_list
)
from routes.notifications import send_notification_for_event

logger = logging.getLogger("climbing_app")
router = APIRouter(prefix="/api/crew", tags=["crew"])


@router.get("")
async def get_crew():
    """Get all crew members from Redis"""
    redis_store = get_redis_store()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Try to calculate new climbers, but don't fail if it errors
        try:
            await redis_store.calculate_new_climbers()
        except Exception as e:
            logger.warning(f"Error calculating new climbers: {e}")
            # Continue anyway - we can still return crew data

        crew = await redis_store.get_all_climbers()
        return JSONResponse(crew)
    except Exception as e:
        logger.error(f"Error getting crew: {e}")
        raise HTTPException(status_code=500, detail="Unable to retrieve crew member data. Please try again later.")


@router.post("/calculate-new")
async def calculate_new_climbers_endpoint(user: dict = Depends(get_current_user)):
    """Manually trigger calculation of new climbers"""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    if not redis_store:
        logger.error("Redis store not available")
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Only allow admins to trigger this
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "manage_users")
            except Exception:
                raise HTTPException(status_code=403, detail="Admin access required")

        new_climbers = await redis_store.calculate_new_climbers()
        return JSONResponse({
            "success": True,
            "message": f"Calculated {len(new_climbers)} new climbers",
            "new_climbers": list(new_climbers)
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating new climbers: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate new climbers")


@router.post("/submit")
async def submit_crew_member(
    name: str = Form(...),
    skills: str = Form(default="[]"),
    location: str = Form(default="[]"),
    achievements: str = Form(default="[]"),
    image: UploadFile = File(None),
    user: dict = Depends(get_current_user_hybrid)
):
    """Submit a new crew member directly to Redis with optional image upload.
    
    Supports both session-based authentication (web) and JWT Bearer token authentication (API).
    """
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    try:
        # Validate and parse form data
        validated_name, validated_skills, validated_location, validated_achievements = validate_crew_form_data(
            name, skills, location, achievements
        )

        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check permissions and submission limits if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_permission(user_id, "create_crew")

                can_create = await permissions_manager.check_submission_limits(user_id, ResourceType.CREW_MEMBER)
                if not can_create:
                    raise HTTPException(
                        status_code=403,
                        detail="You have reached your crew member creation limit. Contact an admin for approval."
                    )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to create crew members. Please contact an administrator.")

        # Add climber to Redis
        await redis_store.add_climber(
            name=validated_name,
            location=validated_location,
            skills=validated_skills,
            achievements=validated_achievements
        )

        # Handle image if provided
        if validate_optional_image_upload(image):
            logger.debug(
                f"Processing image: filename={image.filename}, content_type={image.content_type}, size={image.size}")

            # Read image data
            image_data = await image.read()
            validate_image_file(image.content_type or "", len(image_data))
            logger.debug(f"Read image data: {len(image_data)} bytes")

            # Store image directly as climber image
            try:
                image_path = await redis_store.store_image("climber", f"{validated_name}/face", image_data)
                logger.debug(f"Stored image for {validated_name} at {image_path}")
            except Exception as e:
                logger.error(f"Failed to store image for {validated_name}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to store image: {str(e)}")
        else:
            logger.debug(
                f"No image provided: image={image}, filename={getattr(image, 'filename', None) if image else None}")

        # Set resource ownership and increment count if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.set_resource_owner(ResourceType.CREW_MEMBER, validated_name, user_id)
                await permissions_manager.increment_user_creation_count(user_id, ResourceType.CREW_MEMBER)
            except Exception as e:
                logger.warning(f"Failed to set ownership/increment count: {e}")

        # Send notification for new crew member
        try:
            await send_notification_for_event(
                event_type="crew_member_added",
                event_data={
                    "name": validated_name,
                    "creator": user.get("name", "Someone"),
                    "skills": validated_skills,
                    "location": validated_location
                },
                redis_store=redis_store,
                target_users=None  # Notify all users
            )
        except Exception as e:
            logger.warning(f"Failed to send crew member notification: {e}")

        return JSONResponse({
            "success": True,
            "message": "Crew member added successfully!",
            "crew_name": validated_name
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add crew member: {str(e)}")


@router.post("/edit")
async def edit_crew_member(
    original_name: str = Form(...),
    name: str = Form(...),
    skills: str = Form(default="[]"),
    location: str = Form(default="[]"),
    achievements: str = Form(default="[]"),
    image: UploadFile = File(None),
    user: dict = Depends(get_current_user)
):
    """Edit an existing crew member with comprehensive validation and error handling."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    # Track resources for cleanup on failure
    cleanup_tasks = []

    try:
        # === AUTHENTICATION & AUTHORIZATION ===
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")

        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # === INPUT VALIDATION ===
        logger.info(f"Starting crew edit: {original_name} -> {name} by user {user_id}")

        # Validate and sanitize inputs
        try:
            validated_original_name = validate_name(original_name)
            validated_name = validate_name(name)
            validated_skills = validate_form_json_field(skills, "skills", validate_skill_list)
            validated_location = validate_form_json_field(location, "location", validate_location_list)
            validated_achievements = validate_form_json_field(achievements, "achievements", validate_achievements_list)
        except ValidationError as e:
            logger.warning(f"Validation failed for crew edit {original_name}: {e}")
            raise HTTPException(status_code=400, detail=str(e))

        # === CHECK CREW MEMBER EXISTS ===
        existing_member = await redis_store.get_climber(validated_original_name)
        if not existing_member:
            logger.warning(f"Crew member not found: {validated_original_name}")
            raise HTTPException(status_code=404, detail=f"Crew member '{validated_original_name}' not found")

        # === PERMISSION CHECK ===
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, validated_original_name, "edit"
                )
                logger.debug(f"Permission check passed for user {user_id} to edit {validated_original_name}")
            except Exception as e:
                logger.error(f"Permission check failed for user {user_id} to edit {validated_original_name}: {e}")
                raise HTTPException(
                    status_code=403,
                    detail=f"You don't have permission to edit crew member '{validated_original_name}'. You can only edit crew members you created."
                )

        # === NAME CONFLICT CHECK ===
        name_changed = validated_original_name != validated_name
        if name_changed:
            # Check if new name conflicts with existing crew member
            existing_with_new_name = await redis_store.get_climber(validated_name)
            if existing_with_new_name:
                logger.warning(f"Name conflict: {validated_name} already exists")
                raise HTTPException(
                    status_code=400,
                    detail=f"A crew member named '{validated_name}' already exists. Please choose a different name."
                )

        # === IMAGE VALIDATION & PROCESSING ===
        new_image_data = None
        image_content_type = None

        # Debug logging for image detection
        logger.debug(f"Image detection for {validated_name}: image={image}, filename={getattr(image, 'filename', 'NO_ATTR') if image else 'NULL'}, content_type={getattr(image, 'content_type', 'NO_ATTR') if image else 'NULL'}, size={getattr(image, 'size', 'NO_ATTR') if image else 'NULL'}")

        if image and image.filename:
            logger.info(
                f"Processing image upload for {validated_name}: filename={image.filename}, content_type={image.content_type}")

            try:
                # Validate image file
                if not image.content_type or not image.content_type.startswith('image/'):
                    raise HTTPException(status_code=400, detail="Please upload a valid image file")

                # Read and validate image data
                new_image_data = await image.read()
                image_content_type = image.content_type

                # Validate image file size and type
                validate_image_file(image_content_type, len(new_image_data))

                logger.debug(f"Successfully validated image: {len(new_image_data)} bytes, type: {image_content_type}")

            except ValidationError as e:
                logger.error(f"Image validation failed for {validated_name}: {e}")
                raise HTTPException(status_code=400, detail=f"Image validation failed: {str(e)}")
            except Exception as e:
                logger.error(f"Image processing failed for {validated_name}: {e}")
                raise HTTPException(status_code=500, detail="Failed to process uploaded image")
        else:
            logger.debug(f"No image uploaded for {validated_name} - keeping existing image")

        # === ATOMIC DATABASE UPDATE ===
        try:
            # Step 1: Update the crew member data
            await redis_store.update_climber(
                original_name=validated_original_name,
                name=validated_name,
                location=validated_location,
                skills=validated_skills,
                achievements=validated_achievements
            )
            logger.info(f"Successfully updated crew member data: {validated_original_name} -> {validated_name}")

            # Step 2: Handle image update if provided
            if new_image_data:
                try:
                    # Store new image
                    image_path = await redis_store.store_image("climber", f"{validated_name}/face", new_image_data)
                    cleanup_tasks.append(("delete_image", "climber", f"{validated_name}/face"))
                    logger.info(f"Successfully stored new image for {validated_name}: {image_path}")

                except Exception as e:
                    logger.error(f"Failed to store image for {validated_name}: {e}")
                    # Don't fail the entire operation for image issues, just log the error
                    logger.warning(f"Crew member data updated but image upload failed for {validated_name}")

            # Step 3: Update resource ownership if name changed
            if name_changed and permissions_manager is not None:
                try:
                    # Remove old ownership and add new ownership
                    await permissions_manager.remove_resource_owner(ResourceType.CREW_MEMBER, validated_original_name, user_id)
                    await permissions_manager.set_resource_owner(ResourceType.CREW_MEMBER, validated_name, user_id)
                    logger.info(f"Updated resource ownership: {validated_original_name} -> {validated_name}")

                except Exception as e:
                    logger.warning(f"Failed to update resource ownership for {validated_name}: {e}")
                    # Don't fail the operation for ownership issues

        except Exception as e:
            logger.error(f"Database update failed for crew member {validated_original_name}: {e}")

            # Attempt cleanup
            for task in cleanup_tasks:
                try:
                    if task[0] == "delete_image":
                        await redis_store.delete_image(task[1], task[2])
                        logger.info(f"Cleanup: deleted image {task[1]}:{task[2]}")
                except Exception as cleanup_error:
                    logger.error(f"Cleanup failed for {task}: {cleanup_error}")

            raise HTTPException(status_code=500, detail=f"Failed to update crew member: {str(e)}")

        # === SUCCESS RESPONSE ===
        success_message = f"Crew member '{validated_name}' updated successfully!"
        if new_image_data:
            success_message += " New image uploaded."
        if name_changed:
            success_message += f" Name changed from '{validated_original_name}'."

        logger.info(f"Crew edit completed successfully: {validated_original_name} -> {validated_name}")

        return JSONResponse({
            "success": True,
            "message": success_message,
            "crew_name": validated_name,
            "name_changed": name_changed,
            "image_updated": new_image_data is not None,
            "previous_name": validated_original_name if name_changed else None
        })

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValidationError as e:
        logger.error(f"Validation error in crew edit {original_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in crew edit {original_name}: {e}", exc_info=True)

        # Attempt cleanup on unexpected errors
        for task in cleanup_tasks:
            try:
                if task[0] == "delete_image":
                    await redis_store.delete_image(task[1], task[2])
                    logger.info(f"Emergency cleanup: deleted image {task[1]}:{task[2]}")
            except Exception as cleanup_error:
                logger.error(f"Emergency cleanup failed for {task}: {cleanup_error}")

        raise HTTPException(status_code=500, detail="An unexpected error occurred while updating the crew member")


@router.post("/add-skills")
async def add_skills_to_crew_member(request: AddSkillsRequest, user: dict = Depends(get_current_user)):
    """Add skills to an existing crew member in Redis (no GitHub)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.skills:
        raise HTTPException(status_code=400, detail="At least one skill is required")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get current climber data
        existing_member = await redis_store.get_climber(request.crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, request.crew_name, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(
                    status_code=403, detail=f"You don't have permission to modify crew member '{request.crew_name}'. You can only edit crew members you created.")

        # Get current skills and add new ones
        current_skills = existing_member.get("skills", [])
        updated_skills = current_skills + [skill for skill in request.skills if skill not in current_skills]

        # Update climber with new skills
        await redis_store.update_climber(
            original_name=request.crew_name,
            name=request.crew_name,
            location=existing_member.get("location", []),
            skills=updated_skills
        )

        return JSONResponse({
            "success": True,
            "message": f"Skills added to {request.crew_name} successfully!",
            "crew_name": request.crew_name,
            "added_skills": [skill for skill in request.skills if skill not in current_skills]
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding skills to crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/add-achievements")
async def add_achievements_to_crew_member(request: AddAchievementsRequest, user: dict = Depends(get_current_user)):
    """Add achievements to an existing crew member in Redis (no GitHub)."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    # Validate input
    if not request.crew_name or not request.crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")
    if not request.achievements:
        raise HTTPException(status_code=400, detail="At least one achievement is required")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get current climber data
        existing_member = await redis_store.get_climber(request.crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions if permissions system is available
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, request.crew_name, "edit"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(
                    status_code=403, detail=f"You don't have permission to modify crew member '{request.crew_name}'. You can only edit crew members you created.")

        # Get current achievements and add new ones
        current_achievements = existing_member.get("achievements", [])
        updated_achievements = current_achievements + [
            achievement for achievement in request.achievements if achievement not in current_achievements]

        # Update climber with new achievements
        await redis_store.update_climber(
            original_name=request.crew_name,
            name=request.crew_name,
            location=existing_member.get("location", []),
            skills=existing_member.get("skills", []),
            tags=existing_member.get("tags", []),
            achievements=updated_achievements
        )

        return JSONResponse({
            "success": True,
            "message": f"Achievements added to {request.crew_name} successfully!",
            "crew_name": request.crew_name,
            "added_achievements": [achievement for achievement in request.achievements if achievement not in current_achievements]
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding achievements to crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/delete")
async def delete_crew_member(crew_name: str = Query(...), user: dict = Depends(get_current_user)):
    """Delete a crew member from Redis."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    # Validate crew name
    if not crew_name or not crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")

    if not redis_store:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        validated_name = validate_name(crew_name.strip())
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if crew member exists
        existing_member = await redis_store.get_climber(validated_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions
        if permissions_manager is not None:
            try:
                await permissions_manager.require_resource_access(
                    user_id, ResourceType.CREW_MEMBER, validated_name, "delete"
                )
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to delete this crew member. You can only delete crew members you created.")

        # Delete the crew member
        deleted = await redis_store.delete_climber(validated_name)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete crew member")

        return JSONResponse({
            "success": True,
            "message": f"Crew member '{validated_name}' deleted successfully!",
            "crew_name": validated_name
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete crew member")


@router.delete("/delete")
async def delete_crew_member(crew_name: str, user: dict = Depends(get_current_user)):
    """Delete a crew member from Redis."""
    redis_store = get_redis_store()
    permissions_manager = get_permissions_manager()

    # Validate crew name is provided
    if not crew_name or not crew_name.strip():
        raise HTTPException(status_code=400, detail="Crew name is required")

    try:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if crew member exists
        existing_member = await redis_store.get_climber(crew_name)
        if not existing_member:
            raise HTTPException(status_code=404, detail="Crew member not found")

        # Check resource access permissions
        if permissions_manager is not None:
            await permissions_manager.require_resource_access(
                user_id, ResourceType.CREW_MEMBER, crew_name, "delete"
            )

        # Delete the crew member
        deleted = await redis_store.delete_climber(crew_name)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete crew member")

        return JSONResponse({
            "success": True,
            "message": f"Crew member '{crew_name}' deleted successfully!",
            "crew_name": crew_name
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting crew member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete crew member")
