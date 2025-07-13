"""
Input validation and sanitization utilities for the climbing app.
"""

import re
import html
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import HTTPException


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


def validate_location_list(location: List[str]) -> List[str]:
    """Validate location list (city, country)"""
    if not location:
        return []
    
    validated_location = []
    for loc in location:
        if not loc or not loc.strip():
            continue
        
        sanitized = sanitize_string(loc, max_length=100)
        if sanitized:
            validated_location.append(sanitized)
    
    if len(validated_location) > 5:
        raise ValidationError("Too many location entries (maximum 5)")
    
    return validated_location


def validate_achievements_list(achievements: List[str]) -> List[str]:
    """Validate achievements list"""
    if not achievements:
        return []
    
    validated_achievements = []
    for achievement in achievements:
        if not achievement or not achievement.strip():
            continue
        
        sanitized = sanitize_string(achievement, max_length=200)
        if sanitized not in validated_achievements:
            validated_achievements.append(sanitized)
    
    if len(validated_achievements) > 10:
        raise ValidationError("Too many achievements (maximum 10)")
    
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
    import json
    
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
