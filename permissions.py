import logging
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from dataclasses import dataclass
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """User roles in the system"""
    ADMIN = "admin"
    USER = "user"
    PENDING = "pending"  # New users waiting for approval


class ResourceType(Enum):
    """Types of resources that can be owned"""
    ALBUM = "album"
    CREW_MEMBER = "crew_member"
    MEME = "meme"
    LOCATION = "location"


@dataclass
class SubmissionLimits:
    """Submission limits for different user roles"""
    max_albums: int = 1
    max_crew_members: int = 1
    max_memes: int = 10
    requires_approval: bool = True


@dataclass
class UserPermissions:
    """User permissions and limits"""
    can_create_albums: bool = True
    can_create_crew: bool = True
    can_create_memes: bool = True
    can_edit_own_resources: bool = True
    can_delete_own_resources: bool = True
    can_edit_all_resources: bool = False
    can_delete_all_resources: bool = False
    can_manage_users: bool = False
    submission_limits: Optional[SubmissionLimits] = None


class PermissionsManager:
    """Roles, per-role limits and resource ownership, backed by the store."""

    def __init__(self, store):
        self.store = store
        self.role_permissions = {
            UserRole.ADMIN: UserPermissions(
                can_edit_all_resources=True,
                can_delete_all_resources=True,
                can_manage_users=True,
                submission_limits=SubmissionLimits(
                    max_albums=999999, max_crew_members=999999, max_memes=999999, requires_approval=False
                ),
            ),
            UserRole.USER: UserPermissions(
                submission_limits=SubmissionLimits(max_albums=1, max_crew_members=1, max_memes=10)
            ),
            UserRole.PENDING: UserPermissions(
                can_create_albums=False,
                can_create_crew=False,
                can_create_memes=False,
                can_edit_own_resources=False,
                can_delete_own_resources=False,
                submission_limits=SubmissionLimits(max_albums=0, max_crew_members=0, max_memes=0),
            ),
        }

    # === USER MANAGEMENT ===

    async def create_or_update_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a pending user on first login, refresh profile fields afterwards."""
        user_id = user_data.get("id")
        if not user_id:
            raise ValueError("User ID is required")
        return await self.store.upsert_user(
            user_id, user_data.get("email") or "", user_data.get("name") or "", user_data.get("picture") or ""
        )

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.store.get_user(user_id)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.store.get_user_by_email(email)

    async def get_all_users(self) -> List[Dict[str, Any]]:
        return await self.store.get_all_users()

    async def get_users_by_role(self, role: UserRole) -> List[Dict[str, Any]]:
        return await self.store.get_users_by_role(role.value)

    async def update_user_role(self, user_id: str, new_role: UserRole) -> bool:
        changed = await self.store.set_user_role(user_id, new_role.value)
        if changed:
            logger.info(f"Updated user {user_id} role to {new_role.value}")
        return changed

    async def assign_admin_user(self, email: str) -> bool:
        user = await self.get_user_by_email(email)
        return bool(user) and await self.update_user_role(user["id"], UserRole.ADMIN)

    # === RESOURCE OWNERSHIP ===

    async def set_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        await self.add_resource_owner(resource_type, resource_id, user_id)

    async def add_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        await self.store.add_owner(resource_type.value, resource_id, user_id)

    async def remove_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        await self.store.remove_owner(resource_type.value, resource_id, user_id)

    async def get_resource_owner(self, resource_type: ResourceType, resource_id: str) -> Optional[str]:
        owners = await self.get_resource_owners(resource_type, resource_id)
        return owners[0] if owners else None

    async def get_resource_owners(self, resource_type: ResourceType, resource_id: str) -> List[str]:
        return await self.store.get_owners(resource_type.value, resource_id)

    async def is_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> bool:
        return await self.store.is_owner(resource_type.value, resource_id, user_id)

    async def get_user_resources(self, user_id: str, resource_type: ResourceType) -> Set[str]:
        return await self.store.get_user_resources(user_id, resource_type.value)

    async def release_resource(self, resource_type: ResourceType, resource_id: str) -> None:
        """Drop all ownership of a deleted resource; creation counts are derived, so nothing else to undo."""
        await self.store.release_resource(resource_type.value, resource_id)

    async def rename_resource(self, resource_type: ResourceType, old_id: str, new_id: str) -> None:
        await self.store.rename_resource(resource_type.value, old_id, new_id)

    async def get_unowned_resources(self, resource_type: ResourceType) -> List[str]:
        return await self.store.get_unowned_resources(resource_type.value)

    # === PERMISSION CHECKING ===

    def get_user_permissions(self, user_role: str) -> UserPermissions:
        try:
            return self.role_permissions[UserRole(user_role)]
        except ValueError:
            return self.role_permissions[UserRole.PENDING]

    async def can_user_perform_action(
        self,
        user_id: str,
        action: str,
        resource_type: Optional[ResourceType] = None,
        resource_id: Optional[str] = None,
    ) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        permissions = self.get_user_permissions(user["role"])
        if action == "create_album":
            return permissions.can_create_albums
        if action == "create_crew":
            return permissions.can_create_crew
        if action == "create_meme":
            return permissions.can_create_memes
        if action in ("edit_resource", "delete_resource"):
            all_flag = permissions.can_edit_all_resources if action == "edit_resource" else permissions.can_delete_all_resources
            own_flag = permissions.can_edit_own_resources if action == "edit_resource" else permissions.can_delete_own_resources
            if all_flag:
                return True
            if own_flag and resource_type is not None and resource_id is not None:
                return await self.is_resource_owner(resource_type, resource_id, user_id)
            return False
        if action == "manage_users":
            return permissions.can_manage_users
        return False

    async def check_submission_limits(self, user_id: str, resource_type: ResourceType) -> bool:
        """Creation counts are the number of resources the user currently owns."""
        user = await self.get_user(user_id)
        if not user:
            return False
        limits = self.get_user_permissions(user["role"]).submission_limits
        if not limits:
            return True
        maximum = {
            ResourceType.ALBUM: limits.max_albums,
            ResourceType.CREW_MEMBER: limits.max_crew_members,
            ResourceType.MEME: limits.max_memes,
        }.get(resource_type)
        if maximum is None:
            return True
        return await self.store.count_owned(user_id, resource_type.value) < maximum

    # === AUTHORIZATION HELPERS ===

    async def require_permission(
        self,
        user_id: str,
        action: str,
        resource_type: Optional[ResourceType] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        if await self.can_user_perform_action(user_id, action, resource_type, resource_id):
            return
        details = {
            "create_album": "You don't have permission to create albums. Please contact an administrator.",
            "create_crew": "You don't have permission to create crew members. Please contact an administrator.",
            "create_meme": "You don't have permission to upload memes. Please contact an administrator.",
            "edit_resource": "You don't have permission to edit this resource. You can only edit resources you created.",
            "delete_resource": "You don't have permission to delete this resource. You can only delete resources you created.",
            "manage_users": "You don't have administrative privileges required for this action.",
        }
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=details.get(action, f"You don't have permission to perform this action: {action}"),
        )

    async def require_resource_access(
        self, user_id: str, resource_type: ResourceType, resource_id: str, action: str = "edit"
    ) -> None:
        user = await self.get_user(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        permissions = self.get_user_permissions(user["role"])
        if action == "edit" and permissions.can_edit_all_resources:
            return
        if action == "delete" and permissions.can_delete_all_resources:
            return
        can_touch_own = permissions.can_edit_own_resources if action == "edit" else permissions.can_delete_own_resources
        if not can_touch_own:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your account is pending approval. You cannot {action} resources until an administrator approves you.",
            )
        if not await self.is_resource_owner(resource_type, resource_id, user_id):
            resource_name = resource_type.value.replace("_", " ")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to {action} this {resource_name}. You can only {action} {resource_name}s you created.",
            )
