import json
import logging
from datetime import datetime
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
    """Manages user permissions, roles, and resource ownership"""

    def __init__(self, redis_store):
        self.redis_store = redis_store

        # Define role permissions
        self.role_permissions = {
            UserRole.ADMIN: UserPermissions(
                can_edit_all_resources=True,
                can_delete_all_resources=True,
                can_manage_users=True,
                submission_limits=SubmissionLimits(
                    max_albums=999999,  # Effectively unlimited
                    max_crew_members=999999,  # Effectively unlimited
                    max_memes=999999,  # Effectively unlimited
                    requires_approval=False
                )
            ),
            UserRole.USER: UserPermissions(
                submission_limits=SubmissionLimits(
                    max_albums=1,
                    max_crew_members=1,
                    max_memes=10,  # Users can create up to 10 memes
                    requires_approval=True
                )
            ),
            UserRole.PENDING: UserPermissions(
                can_create_albums=False,
                can_create_crew=False,
                can_create_memes=False,
                can_edit_own_resources=False,
                can_delete_own_resources=False,
                submission_limits=SubmissionLimits(
                    max_albums=0,
                    max_crew_members=0,
                    max_memes=0,
                    requires_approval=True
                )
            )
        }

    # === USER MANAGEMENT ===

    async def create_or_update_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update user from OAuth data"""
        user_id = user_data.get("id")
        if not user_id:
            raise ValueError("User ID is required")

        user_key = f"user:{user_id}"
        existing_user = await self.get_user(user_id)

        if existing_user:
            # Update last login
            self.redis_store.redis.hset(user_key, mapping={
                "last_login": datetime.now().isoformat(),
                "name": user_data.get("name", existing_user.get("name", "")),
                "picture": user_data.get("picture", existing_user.get("picture", ""))
            })
            return existing_user
        else:
            # Create new user - start as PENDING to require manual approval
            new_user = {
                "id": user_id,
                "email": user_data.get("email"),
                "name": user_data.get("name"),
                "picture": user_data.get("picture"),
                "role": UserRole.PENDING.value,  # New users start as pending
                "created_at": datetime.now().isoformat(),
                "last_login": datetime.now().isoformat(),
                "albums_created": "0",
                "crew_members_created": "0",
                "memes_created": "0",
                "is_approved": "false"  # Require manual approval
            }

            self.redis_store.redis.hset(user_key, mapping=new_user)
            self.redis_store.redis.sadd("index:users:all", user_id)
            self.redis_store.redis.sadd(f"index:users:role:{UserRole.PENDING.value}", user_id)

            logger.info(f"Created new PENDING user: {user_data.get('email')} - requires admin approval")
            return new_user

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        user_key = f"user:{user_id}"
        user_data = self.redis_store.redis.hgetall(user_key)

        if not user_data:
            return None

        # Convert numeric fields
        user_data["albums_created"] = int(user_data.get("albums_created", "0"))
        user_data["crew_members_created"] = int(user_data.get("crew_members_created", "0"))
        user_data["memes_created"] = int(user_data.get("memes_created", "0"))
        user_data["is_approved"] = user_data.get("is_approved", "false") == "true"

        return user_data

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        # Search through all users (could be optimized with email index)
        user_ids = self.redis_store.redis.smembers("index:users:all")

        for user_id in user_ids:
            user = await self.get_user(user_id)
            if user and user.get("email") == email:
                return user

        return None

    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users"""
        user_ids = self.redis_store.redis.smembers("index:users:all")
        users = []

        for user_id in user_ids:
            user = await self.get_user(user_id)
            if user:
                users.append(user)

        # Sort by creation date (newest first)
        users.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return users

    async def update_user_role(self, user_id: str, new_role: UserRole) -> bool:
        """Update user's role"""
        user = await self.get_user(user_id)
        if not user:
            return False

        old_role = user.get("role")
        user_key = f"user:{user_id}"

        # Update role
        self.redis_store.redis.hset(user_key, "role", new_role.value)

        # Update role indexes
        if old_role:
            self.redis_store.redis.srem(f"index:users:role:{old_role}", user_id)
        self.redis_store.redis.sadd(f"index:users:role:{new_role.value}", user_id)

        logger.info(f"Updated user {user_id} role from {old_role} to {new_role.value}")
        return True

    # === RESOURCE OWNERSHIP ===

    async def set_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        """Set the owner of a resource (deprecated - use add_resource_owner for multiple owners)"""
        await self.add_resource_owner(resource_type, resource_id, user_id)

    async def add_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        """Add an owner to a resource (supports multiple owners)"""
        ownership_key = f"ownership:{resource_type.value}:{resource_id}"
        self.redis_store.redis.sadd(ownership_key, user_id)

        # Add to user's owned resources index
        self.redis_store.redis.sadd(f"index:user_resources:{user_id}:{resource_type.value}", resource_id)

        logger.info(f"Added {resource_type.value} {resource_id} owner: user {user_id}")

    async def remove_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> None:
        """Remove an owner from a resource"""
        ownership_key = f"ownership:{resource_type.value}:{resource_id}"
        self.redis_store.redis.srem(ownership_key, user_id)

        # Remove from user's owned resources index
        self.redis_store.redis.srem(f"index:user_resources:{user_id}:{resource_type.value}", resource_id)

        logger.info(f"Removed {resource_type.value} {resource_id} owner: user {user_id}")

    async def get_resource_owner(self, resource_type: ResourceType, resource_id: str) -> Optional[str]:
        """Get the first owner of a resource (for backward compatibility)"""
        owners = await self.get_resource_owners(resource_type, resource_id)
        return owners[0] if owners else None

    async def get_resource_owners(self, resource_type: ResourceType, resource_id: str) -> List[str]:
        """Get all owners of a resource"""
        ownership_key = f"ownership:{resource_type.value}:{resource_id}"
        owner_ids = self.redis_store.redis.smembers(ownership_key)
        return list(owner_ids)

    async def is_resource_owner(self, resource_type: ResourceType, resource_id: str, user_id: str) -> bool:
        """Check if a user is an owner of a resource"""
        ownership_key = f"ownership:{resource_type.value}:{resource_id}"
        return self.redis_store.redis.sismember(ownership_key, user_id)

    async def get_user_resources(self, user_id: str, resource_type: ResourceType) -> Set[str]:
        """Get all resources owned by a user"""
        return self.redis_store.redis.smembers(f"index:user_resources:{user_id}:{resource_type.value}")

    async def transfer_resource_ownership(self, resource_type: ResourceType, resource_id: str,
                                          from_user_id: str, to_user_id: str) -> bool:
        """Transfer resource ownership between users (replaces single owner)"""
        current_owners = await self.get_resource_owners(resource_type, resource_id)
        if from_user_id not in current_owners:
            return False

        # Remove from old owner's index
        await self.remove_resource_owner(resource_type, resource_id, from_user_id)

        # Add new owner
        await self.add_resource_owner(resource_type, resource_id, to_user_id)

        logger.info(f"Transferred {resource_type.value} {resource_id} from user {from_user_id} to {to_user_id}")
        return True

    # === PERMISSION CHECKING ===

    def get_user_permissions(self, user_role: str) -> UserPermissions:
        """Get permissions for a user role"""
        try:
            role_enum = UserRole(user_role)
            return self.role_permissions.get(role_enum, self.role_permissions[UserRole.USER])
        except ValueError:
            return self.role_permissions[UserRole.USER]

    async def can_user_perform_action(self, user_id: str, action: str, resource_type: Optional[ResourceType] = None,
                                      resource_id: Optional[str] = None) -> bool:
        """Check if user can perform a specific action"""
        user = await self.get_user(user_id)
        if not user:
            return False

        permissions = self.get_user_permissions(user.get("role", UserRole.USER.value))

        # Check specific actions
        if action == "create_album":
            return permissions.can_create_albums
        elif action == "create_crew":
            return permissions.can_create_crew
        elif action == "create_meme":
            return permissions.can_create_memes
        elif action == "edit_resource":
            if permissions.can_edit_all_resources:
                return True
            if permissions.can_edit_own_resources and resource_type is not None and resource_id is not None:
                return await self.is_resource_owner(resource_type, resource_id, user_id)
            return False
        elif action == "delete_resource":
            if permissions.can_delete_all_resources:
                return True
            if permissions.can_delete_own_resources and resource_type is not None and resource_id is not None:
                return await self.is_resource_owner(resource_type, resource_id, user_id)
            return False
        elif action == "manage_users":
            return permissions.can_manage_users

        return False

    async def check_submission_limits(self, user_id: str, resource_type: ResourceType) -> bool:
        """Check if user can create more resources of given type"""
        user = await self.get_user(user_id)
        if not user:
            return False

        permissions = self.get_user_permissions(user.get("role", UserRole.USER.value))
        limits = permissions.submission_limits

        if not limits:
            return True

        if resource_type == ResourceType.ALBUM:
            current_count = user.get("albums_created", 0)
            return current_count < limits.max_albums
        elif resource_type == ResourceType.CREW_MEMBER:
            current_count = user.get("crew_members_created", 0)
            return current_count < limits.max_crew_members
        elif resource_type == ResourceType.MEME:
            current_count = user.get("memes_created", 0)
            return current_count < limits.max_memes

        return True

    async def increment_user_creation_count(self, user_id: str, resource_type: ResourceType) -> None:
        """Increment user's resource creation count"""
        user_key = f"user:{user_id}"

        if resource_type == ResourceType.ALBUM:
            self.redis_store.redis.hincrby(user_key, "albums_created", 1)
        elif resource_type == ResourceType.CREW_MEMBER:
            self.redis_store.redis.hincrby(user_key, "crew_members_created", 1)
        elif resource_type == ResourceType.MEME:
            self.redis_store.redis.hincrby(user_key, "memes_created", 1)

    # === AUTHORIZATION HELPERS ===

    async def require_permission(self, user_id: str, action: str, resource_type: Optional[ResourceType] = None,
                                 resource_id: Optional[str] = None) -> None:
        """Require permission for an action, raise HTTPException if denied"""
        if not await self.can_user_perform_action(user_id, action, resource_type, resource_id):
            # Create more specific error messages based on the action
            if action == "create_album":
                detail = "You don't have permission to create albums. Please contact an administrator."
            elif action == "create_crew":
                detail = "You don't have permission to create crew members. Please contact an administrator."
            elif action == "edit_resource":
                detail = "You don't have permission to edit this resource. You can only edit resources you created."
            elif action == "delete_resource":
                detail = "You don't have permission to delete this resource. You can only delete resources you created."
            elif action == "manage_users":
                detail = "You don't have administrative privileges required for this action."
            else:
                detail = f"You don't have permission to perform this action: {action}"

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail
            )

    async def require_resource_access(self, user_id: str, resource_type: ResourceType,
                                      resource_id: str, action: str = "edit") -> None:
        """Require access to a specific resource"""
        user = await self.get_user(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )

        permissions = self.get_user_permissions(user.get("role", UserRole.USER.value))

        # Admins can access everything
        if action == "edit" and permissions.can_edit_all_resources:
            return
        if action == "delete" and permissions.can_delete_all_resources:
            return

        # Check ownership
        if not await self.is_resource_owner(resource_type, resource_id, user_id):
            resource_name = resource_type.value.replace('_', ' ')
            if action == "edit":
                detail = f"You don't have permission to edit this {resource_name}. You can only edit {resource_name}s you created."
            elif action == "delete":
                detail = f"You don't have permission to delete this {resource_name}. You can only delete {resource_name}s you created."
            else:
                detail = f"You don't have permission to access this {resource_name}. You can only access {resource_name}s you created."
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail
            )

    # === ADMIN FUNCTIONS ===

    async def get_users_by_role(self, role: UserRole) -> List[Dict[str, Any]]:
        """Get all users with a specific role"""
        user_ids = self.redis_store.redis.smembers(f"index:users:role:{role.value}")
        users = []

        for user_id in user_ids:
            user = await self.get_user(user_id)
            if user:
                users.append(user)

        return users

    async def get_unowned_resources(self, resource_type: ResourceType) -> List[str]:
        """Get resources that don't have any owners (for migration purposes)"""
        if resource_type == ResourceType.ALBUM:
            all_albums = self.redis_store.redis.smembers("index:albums:all")
            unowned = []
            for album_url in all_albums:
                owners = await self.get_resource_owners(resource_type, album_url)
                if not owners:
                    unowned.append(album_url)
            return unowned
        elif resource_type == ResourceType.CREW_MEMBER:
            all_crew = self.redis_store.redis.smembers("index:climbers:all")
            unowned = []
            for crew_name in all_crew:
                owners = await self.get_resource_owners(resource_type, crew_name)
                if not owners:
                    unowned.append(crew_name)
            return unowned

        return []

    async def assign_admin_user(self, email: str) -> bool:
        """Assign admin role to a user by email"""
        user = await self.get_user_by_email(email)
        if not user:
            return False

        return await self.update_user_role(user["id"], UserRole.ADMIN)

    # === MIGRATION HELPERS ===

    async def migrate_ownership_to_sets(self) -> Dict[str, int]:
        """Migrate existing string-based ownership to set-based ownership"""
        migrated = {"albums": 0, "crew_members": 0}
        
        try:
            # Get all ownership keys
            ownership_keys = []
            for key_pattern in ["ownership:album:*", "ownership:crew_member:*"]:
                keys = self.redis_store.redis.keys(key_pattern)
                ownership_keys.extend(keys)
            
            logger.info(f"Found {len(ownership_keys)} ownership keys to migrate")
            
            for key in ownership_keys:
                try:
                    # Check if it's already a set
                    key_type = self.redis_store.redis.type(key)
                    
                    if key_type == "string":
                        # Get the old string value (single owner)
                        old_owner = self.redis_store.redis.get(key)
                        
                        if old_owner:
                            # Delete the old string key
                            self.redis_store.redis.delete(key)
                            
                            # Create new set with the single owner
                            self.redis_store.redis.sadd(key, old_owner)
                            
                            # Count the migration
                            if "album" in key:
                                migrated["albums"] += 1
                            elif "crew_member" in key:
                                migrated["crew_members"] += 1
                                
                            logger.info(f"Migrated ownership key {key}: {old_owner}")
                    
                except Exception as e:
                    logger.error(f"Failed to migrate ownership key {key}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error during ownership migration: {e}")
            
        logger.info(f"Ownership migration completed: {migrated}")
        return migrated

    async def migrate_existing_resources_to_system_ownership(self) -> Dict[str, int]:
        """Migrate existing resources to be owned by system/admin"""
        # First migrate ownership format
        await self.migrate_ownership_to_sets()
        
        # Find first admin user or create system user
        admin_users = await self.get_users_by_role(UserRole.ADMIN)
        if admin_users:
            system_user_id = admin_users[0]["id"]
        else:
            # Create system user for existing resources
            system_user_data = {
                "id": "system",
                "email": "system@climbing.app",
                "name": "System",
                "picture": "",
                "role": UserRole.ADMIN.value,
                "created_at": datetime.now().isoformat(),
                "last_login": datetime.now().isoformat(),
                "albums_created": "0",
                "crew_members_created": "0",
                "is_approved": "true"
            }

            self.redis_store.redis.hset("user:system", mapping=system_user_data)
            self.redis_store.redis.sadd("index:users:all", "system")
            self.redis_store.redis.sadd(f"index:users:role:{UserRole.ADMIN.value}", "system")
            system_user_id = "system"

        migrated = {"albums": 0, "crew_members": 0}

        # Migrate albums
        unowned_albums = await self.get_unowned_resources(ResourceType.ALBUM)
        for album_url in unowned_albums:
            await self.add_resource_owner(ResourceType.ALBUM, album_url, system_user_id)
            migrated["albums"] += 1

        # Migrate crew members
        unowned_crew = await self.get_unowned_resources(ResourceType.CREW_MEMBER)
        for crew_name in unowned_crew:
            await self.add_resource_owner(ResourceType.CREW_MEMBER, crew_name, system_user_id)
            migrated["crew_members"] += 1

        logger.info(
            f"Migrated {migrated['albums']} albums and {migrated['crew_members']} crew members to system ownership")
        return migrated
