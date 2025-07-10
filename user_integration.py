"""
Optional user integration utilities for linking OAuth users to crew members.
This is an example of how you could integrate Google OAuth users with your crew system.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

def load_crew_data() -> List[Dict[str, Any]]:
    """Load crew data from files"""
    crew_data = []
    climbers_dir = Path("climbers")
    
    if not climbers_dir.exists():
        return crew_data
    
    for climber_dir in climbers_dir.iterdir():
        if climber_dir.is_dir():
            details_file = climber_dir / "details.json"
            if details_file.exists():
                try:
                    with open(details_file) as f:
                        details = json.load(f)
                        details["name"] = climber_dir.name
                        crew_data.append(details)
                except Exception as e:
                    logger.error(f"Error loading crew data for {climber_dir.name}: {e}")
    
    return crew_data

def find_crew_member_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Find a crew member by their email address"""
    crew_data = load_crew_data()
    
    for member in crew_data:
        # Check if email is stored in member details
        if member.get("email", "").lower() == email.lower():
            return member
    
    return None

def find_crew_member_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Find a crew member by their name (fuzzy matching)"""
    crew_data = load_crew_data()
    name_lower = name.lower()
    
    # First try exact match
    for member in crew_data:
        if member.get("name", "").lower() == name_lower:
            return member
    
    # Then try partial matches
    for member in crew_data:
        member_name = member.get("name", "").lower()
        if name_lower in member_name or member_name in name_lower:
            return member
    
    return None

def get_user_permissions(user_data: Dict[str, Any]) -> Dict[str, bool]:
    """Determine user permissions based on OAuth data and crew membership"""
    email = user_data.get("email", "")
    name = user_data.get("name", "")
    
    # Find associated crew member
    crew_member = find_crew_member_by_email(email) or find_crew_member_by_name(name)
    
    # Default permissions
    permissions = {
        "can_view": True,  # Everyone can view
        "can_submit_albums": False,  # Only crew members can submit
        "can_edit_crew": False,  # Only specific members can edit
        "can_add_crew": False,  # Only specific members can add new crew
        "is_crew_member": crew_member is not None,
        "is_admin": False
    }
    
    if crew_member:
        # Crew members get more permissions
        permissions.update({
            "can_submit_albums": True,
            "can_edit_crew": True,
        })
        
        # Check for admin status (you could add admin field to crew details)
        if crew_member.get("admin", False) or crew_member.get("role") == "admin":
            permissions.update({
                "can_add_crew": True,
                "is_admin": True
            })
    
    return permissions

def get_enhanced_user_data(oauth_user: Dict[str, Any]) -> Dict[str, Any]:
    """Enhance OAuth user data with crew information and permissions"""
    email = oauth_user.get("email", "")
    name = oauth_user.get("name", "")
    
    # Find associated crew member
    crew_member = find_crew_member_by_email(email) or find_crew_member_by_name(name)
    
    # Get permissions
    permissions = get_user_permissions(oauth_user)
    
    enhanced_data = {
        **oauth_user,
        "permissions": permissions,
        "crew_member": crew_member,
        "crew_name": crew_member.get("name") if crew_member else None,
        "crew_skills": crew_member.get("skills", []) if crew_member else [],
        "crew_location": crew_member.get("location", []) if crew_member else []
    }
    
    return enhanced_data

def can_user_access_resource(user_data: Dict[str, Any], resource: str, action: str) -> bool:
    """Check if user can access a specific resource/action"""
    permissions = user_data.get("permissions", {})
    
    access_rules = {
        "albums": {
            "view": permissions.get("can_view", False),
            "submit": permissions.get("can_submit_albums", False),
            "edit": permissions.get("can_edit_crew", False)
        },
        "crew": {
            "view": permissions.get("can_view", False),
            "add": permissions.get("can_add_crew", False),
            "edit": permissions.get("can_edit_crew", False)
        },
        "admin": {
            "access": permissions.get("is_admin", False)
        }
    }
    
    return access_rules.get(resource, {}).get(action, False)

# Example usage in your auth dependency:
def get_enhanced_current_user(oauth_user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Get current user with enhanced crew integration"""
    if not oauth_user:
        return None
    
    return get_enhanced_user_data(oauth_user)

# Example decorator for permission checking:
def require_permission(resource: str, action: str):
    """Decorator to require specific permissions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get user from kwargs (assumes user is passed as dependency)
            user = kwargs.get('user')
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")
            
            if not can_user_access_resource(user, resource, action):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator 
