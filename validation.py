"""
Input validation and sanitization utilities for the climbing app.
"""

import re
import html
import json
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import HTTPException, Form, UploadFile


class ValidationError(Exception):
    """Custom validation error"""
    pass


def sanitize_string(value: str, max_length: int = 255) -> str:
    """Sanitize string input by removing HTML and limiting length"""
    if not value:
        return ""
    
    # Remove HTML tags and decode HTML entities
    sanitized = html.escape(value.strip())
    
    # Limit length
    if len(sanitized) > max_length:
        raise ValidationError(f"Input too long (max {max_length} characters)")
    
    return sanitized


def validate_name(name: str) -> str:
    """Validate and sanitize person name"""
    if not name or not name.strip():
        raise ValidationError("Name is required")
    
    sanitized = sanitize_string(name, max_length=100)
    
    # Check for valid characters (letters, spaces, hyphens, apostrophes)
    if not re.match(r"^[a-zA-Z\s\-']+$", sanitized):
        raise ValidationError("Name contains invalid characters")
    
    return sanitized


def validate_google_photos_url(url: str) -> str:
    """Validate Google Photos URL format"""
    if not url:
        raise ValidationError("URL is required")
    
    # Basic URL validation
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValidationError("Invalid URL format")
    
    # Check for Google Photos pattern
    if not re.match(r"^https://photos\.app\.goo\.gl/[a-zA-Z0-9]+$", url):
        raise ValidationError("Must be a valid Google Photos album URL (e.g., https://photos.app.goo.gl/...)")
    
    return url


def validate_skill_list(skills: List[str]) -> List[str]:
    """Validate list of skills"""
    if not skills:
        return []
    
    validated_skills = []
    for skill in skills:
        if not skill or not skill.strip():
            continue
        
        sanitized = sanitize_string(skill, max_length=50)
        if sanitized not in validated_skills:
            validated_skills.append(sanitized)
    
    if len(validated_skills) > 20:
        raise ValidationError("Too many skills (maximum 20)")
    
    return validated_skills


def validate_location_list(locations: List[str]) -> List[str]:
    """Validate list of locations"""
    if not locations:
        return []
    
    validated_locations = []
    for location in locations:
        if not location or not location.strip():
            continue
        
        sanitized = sanitize_string(location, max_length=100)
        if sanitized not in validated_locations:
            validated_locations.append(sanitized)
    
    if len(validated_locations) > 10:
        raise ValidationError("Too many locations (maximum 10)")
    
    return validated_locations


def validate_achievements_list(achievements: List[str]) -> List[str]:
    """Validate list of achievements"""
    if not achievements:
        return []
    
    validated_achievements = []
    for achievement in achievements:
        if not achievement or not achievement.strip():
            continue
        
        sanitized = sanitize_string(achievement, max_length=100)
        if sanitized not in validated_achievements:
            validated_achievements.append(sanitized)
    
    if len(validated_achievements) > 20:
        raise ValidationError("Too many achievements (maximum 20)")
    
    return validated_achievements


def validate_image_file(content_type: str, file_size: int) -> None:
    """Validate image file type and size"""
    if not content_type or not content_type.startswith('image/'):
        raise ValidationError("File must be an image")
    
    # Check allowed image types
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if content_type not in allowed_types:
        raise ValidationError(f"Unsupported image type. Allowed: {', '.join(allowed_types)}")
    
    # Check file size (5MB limit)
    max_size = 5 * 1024 * 1024  # 5MB
    if file_size > max_size:
        raise ValidationError(f"Image too large (max {max_size // (1024*1024)}MB)")


def validate_crew_list(crew: List[str]) -> List[str]:
    """Validate crew member list"""
    if not crew:
        raise ValidationError("At least one crew member is required")
    
    validated_crew = []
    for member in crew:
        if not member or not member.strip():
            continue
        
        validated_name = validate_name(member)
        if validated_name not in validated_crew:
            validated_crew.append(validated_name)
    
    if len(validated_crew) > 10:
        raise ValidationError("Too many crew members (maximum 10)")
    
    return validated_crew


def validate_redis_key(key: str) -> str:
    """Validate Redis key to prevent injection"""
    if not key:
        raise ValidationError("Key cannot be empty")
    
    # Only allow alphanumeric, colon, hyphen, underscore
    if not re.match(r"^[a-zA-Z0-9:_-]+$", key):
        raise ValidationError("Invalid key format")
    
    if len(key) > 250:
        raise ValidationError("Key too long")
    
    return key


def validate_json_input(data: str, max_items: int = 100) -> List[str]:
    """Validate JSON input for lists"""
    if not data:
        return []
    
    try:
        parsed = json.loads(data)
        if not isinstance(parsed, list):
            raise ValidationError("Must be a JSON array")
        
        if len(parsed) > max_items:
            raise ValidationError(f"Too many items (maximum {max_items})")
        
        return [str(item) for item in parsed if item]
    
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON format")


def validate_user_id(user_id: str) -> str:
    """Validate user ID format"""
    if not user_id:
        raise ValidationError("User ID is required")
    
    # Basic alphanumeric validation
    if not re.match(r"^[a-zA-Z0-9_-]+$", user_id):
        raise ValidationError("Invalid user ID format")
    
    if len(user_id) > 100:
        raise ValidationError("User ID too long")
    
    return user_id


def validate_http_status_code(status_code: int) -> int:
    """Validate HTTP status code"""
    if not isinstance(status_code, int):
        raise ValidationError("Status code must be an integer")
    
    if status_code < 100 or status_code > 599:
        raise ValidationError("Invalid HTTP status code")
    
    return status_code


def validate_and_sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize metadata dictionary"""
    if not metadata:
        return {}
    
    sanitized = {}
    allowed_keys = ['title', 'description', 'date', 'imageUrl', 'cover_image']
    
    for key, value in metadata.items():
        if key not in allowed_keys:
            continue
        
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value, max_length=500)
        elif key == 'imageUrl' or key == 'cover_image':
            # Validate image URLs
            if value and isinstance(value, str):
                parsed = urlparse(value)
                if parsed.scheme in ['http', 'https']:
                    sanitized[key] = value
    
    return sanitized


def validate_form_json_field(field_data: str, field_name: str, validator_func=None) -> List[str]:
    """Validate JSON field from form data and apply optional validator"""
    if not field_data:
        return []
    
    try:
        parsed = json.loads(field_data)
        if not isinstance(parsed, list):
            raise ValidationError(f"{field_name} must be a JSON array")
        
        # Apply validator function if provided
        if validator_func:
            return validator_func(parsed)
        
        return [str(item) for item in parsed if item]
    
    except json.JSONDecodeError:
        raise ValidationError(f"Invalid JSON format in {field_name}")


def validate_required_string(value: str, field_name: str) -> str:
    """Validate that a string field is required and not empty"""
    if not value or not value.strip():
        raise ValidationError(f"{field_name} is required")
    return value.strip()


def validate_optional_image_upload(image: UploadFile) -> bool:
    """Validate optional image upload, return True if valid image provided"""
    if not image or not image.filename:
        return False
    
    if not image.content_type or not image.content_type.startswith('image/'):
        raise ValidationError("Please upload a valid image file")
    
    return True


def validate_user_role(role: str) -> str:
    """Validate user role"""
    valid_roles = ['admin', 'user', 'pending']
    if role not in valid_roles:
        raise ValidationError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")
    return role


def validate_resource_type(resource_type: str) -> str:
    """Validate resource type"""
    valid_types = ['album', 'crew_member', 'meme']
    if resource_type not in valid_types:
        raise ValidationError(f"Invalid resource type. Must be one of: {', '.join(valid_types)}")
    return resource_type


def validate_skill_name(skill_name: str) -> str:
    """Validate skill name"""
    if not skill_name or not skill_name.strip():
        raise ValidationError("Skill name is required")
    
    sanitized = sanitize_string(skill_name, max_length=50)
    
    # Check for valid characters (letters, spaces, hyphens)
    if not re.match(r"^[a-zA-Z\s\-]+$", sanitized):
        raise ValidationError("Skill name contains invalid characters")
    
    return sanitized


def validate_achievement_name(achievement_name: str) -> str:
    """Validate achievement name"""
    if not achievement_name or not achievement_name.strip():
        raise ValidationError("Achievement name is required")
    
    sanitized = sanitize_string(achievement_name, max_length=100)
    
    # Check for valid characters (letters, spaces, hyphens, numbers)
    if not re.match(r"^[a-zA-Z0-9\s\-]+$", sanitized):
        raise ValidationError("Achievement name contains invalid characters")
    
    return sanitized


def validate_and_raise_http_exception(validation_func, *args, **kwargs):
    """Helper to convert ValidationError to HTTPException"""
    try:
        return validation_func(*args, **kwargs)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


def validate_crew_form_data(name: str, skills: str, location: str, achievements: str):
    """Validate crew member form data and return parsed values"""
    # Validate name
    validated_name = validate_name(name)
    
    # Parse and validate JSON fields
    validated_skills = validate_form_json_field(skills, "skills", validate_skill_list)
    validated_location = validate_form_json_field(location, "location", validate_location_list)
    validated_achievements = validate_form_json_field(achievements, "achievements", validate_achievements_list)
    
    return validated_name, validated_skills, validated_location, validated_achievements


def validate_crew_edit_form_data(original_name: str, name: str, skills: str, location: str, achievements: str):
    """Validate crew member edit form data and return parsed values"""
    # Validate original name
    validated_original_name = validate_required_string(original_name, "Original name")
    
    # Validate new name
    validated_name = validate_name(name)
    
    # Parse and validate JSON fields
    validated_skills = validate_form_json_field(skills, "skills", validate_skill_list)
    validated_location = validate_form_json_field(location, "location", validate_location_list)
    validated_achievements = validate_form_json_field(achievements, "achievements", validate_achievements_list)
    
    return validated_original_name, validated_name, validated_skills, validated_location, validated_achievements 
