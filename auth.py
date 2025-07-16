import json
import secrets
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode, parse_qs
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from config import settings

logger = logging.getLogger(__name__)

# Security scheme for JWT Bearer tokens
security = HTTPBearer(auto_error=False)

class SessionManager:
    """Handles secure session management using signed cookies"""
    
    def __init__(self):
        self.serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
    
    def create_session_token(self, user_data: Dict[str, Any]) -> str:
        """Create a signed session token containing user data"""
        return self.serializer.dumps(user_data)
    
    def verify_session_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a session token"""
        try:
            # Verify token is not expired (max age in seconds)
            user_data = self.serializer.loads(token, max_age=settings.SESSION_MAX_AGE)
            return user_data
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid session token: {e}")
            return None
    
    def set_session_cookie(self, response: RedirectResponse, user_data: Dict[str, Any]):
        """Set secure session cookie on response"""
        token = self.create_session_token(user_data)
        response.set_cookie(
            key="session",
            value=token,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            secure=settings.is_production,
            samesite="lax"
        )
    
    def clear_session_cookie(self, response: RedirectResponse):
        """Clear session cookie"""
        response.delete_cookie(key="session")

class OAuthHandler:
    """Handles Google OAuth 2.0 flow"""
    
    def __init__(self):
        self.session_manager = SessionManager()
    
    def generate_auth_url(self, state: Optional[str] = None) -> str:
        """Generate Google OAuth authorization URL"""
        if not state:
            state = secrets.token_urlsafe(32)
        
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": f"{settings.BASE_URL}/auth/callback",
            "scope": " ".join(settings.OAUTH_SCOPES),
            "response_type": "code",
            "access_type": "offline",
            "state": state,
            "prompt": "select_account"
        }
        
        return f"{settings.GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"
    
    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token"""
        token_data = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": f"{settings.BASE_URL}/auth/callback",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.GOOGLE_TOKEN_URL,
                data=token_data,
                headers={"Accept": "application/json"}
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code"
                )
            
            return response.json()
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Google using access token"""
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.GOOGLE_USERINFO_URL,
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"User info fetch failed: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch user information"
                )
            
            return response.json()
    
    def get_current_user(self, request: Request) -> Optional[Dict[str, Any]]:
        """Get current user from session cookie"""
        session_token = request.cookies.get("session")
        if not session_token:
            return None
        
        return self.session_manager.verify_session_token(session_token)
    
    def require_auth(self, request: Request) -> Dict[str, Any]:
        """Require authentication, raise HTTPException if not authenticated"""
        user = self.get_current_user(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        return user


class JWTManager:
    """Handles JWT token generation and validation"""

    def __init__(self, redis_store=None):
        self.secret_key = settings.SECRET_KEY
        self.algorithm = "HS256"
        self.default_token_expire_hours = 24  # Default 24 hours
        self.redis_store = redis_store

    def create_access_token(
            self, user_data: Dict[str, Any],
            selected_permissions: Optional[Dict[str, bool]] = None,
            token_name: Optional[str] = None,
            expires_in_hours: Optional[int] = None) -> Dict[str, Any]:
        """Create a JWT access token with optional selective permissions and custom expiry"""
        now = datetime.utcnow()
        
        # Use custom expiry or default
        expiry_hours = expires_in_hours if expires_in_hours is not None else self.default_token_expire_hours
        expire = now + timedelta(hours=expiry_hours)

        # Use selective permissions if provided, otherwise use all user permissions
        permissions = selected_permissions if selected_permissions is not None else user_data.get("permissions", {})

        # Generate unique token ID for blacklisting
        import uuid
        token_id = str(uuid.uuid4())

        payload = {
            "sub": user_data.get("id"),  # Subject (user ID)
            "email": user_data.get("email"),
            "name": user_data.get("name"),
            "role": user_data.get("role", "user"),
            "permissions": permissions,
            "iat": now,
            "exp": expire,
            "type": "access",
            "jti": token_id,  # JWT ID for blacklisting
            "token_name": token_name or "API Token"  # User-friendly name
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        # Store token metadata in Redis for management
        if self.redis_store:
            user_id_str = user_data.get("id")
            if user_id_str:
                self._store_token_metadata(user_id_str, token_id, {
                    "name": token_name or "API Token",
                    "created_at": now.isoformat(),
                    "expires_at": expire.isoformat(),
                    "permissions": json.dumps(permissions) if permissions else "{}",
                    "last_used": "",
                    "expires_in_hours": str(expiry_hours)
                })

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expiry_hours * 3600,  # Convert hours to seconds
            "expires_at": expire.isoformat()
        }

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token with blacklist checking"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Check if token is blacklisted
            if self.redis_store and self._is_token_blacklisted(payload.get("jti")):
                logger.warning(f"Blacklisted JWT token attempted: {payload.get('jti')}")
                return None

            # Update last used timestamp for access tokens
            if payload.get("type") == "access" and self.redis_store:
                self._update_token_last_used(payload.get("sub"), payload.get("jti"))

            return payload
        except ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None

    def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify an access token and return user data"""
        payload = self.verify_token(token)
        if payload and payload.get("type") == "access":
            return {
                "id": payload.get("sub"),
                "email": payload.get("email"),
                "name": payload.get("name"),
                "role": payload.get("role", "user"),
                "permissions": payload.get("permissions", {}),
                "authenticated": True,
                "token_name": payload.get("token_name", "API Token")
            }
        return None

    # Token management methods
    def _store_token_metadata(self, user_id: str, token_id: str, metadata: Dict[str, Any]) -> None:
        """Store token metadata in Redis"""
        if not self.redis_store:
            return

        key = f"token_metadata:{user_id}:{token_id}"
        self.redis_store.redis.hset(key, mapping=metadata)
        
        # Set expiry based on token expiry hours
        expiry_hours = int(metadata.get("expires_in_hours", self.default_token_expire_hours))
        self.redis_store.redis.expire(key, expiry_hours * 3600)

        # Add to user's token index
        self.redis_store.redis.sadd(f"user_tokens:{user_id}", token_id)

    def _update_token_last_used(self, user_id: str, token_id: str) -> None:
        """Update token's last used timestamp"""
        if not self.redis_store or not token_id:
            return

        key = f"token_metadata:{user_id}:{token_id}"
        self.redis_store.redis.hset(key, "last_used", datetime.utcnow().isoformat())

    def _is_token_blacklisted(self, token_id: str) -> bool:
        """Check if a token is blacklisted"""
        if not self.redis_store or not token_id:
            return False

        return self.redis_store.redis.sismember("blacklisted_tokens", token_id)

    def blacklist_token(self, token_id: str) -> None:
        """Add a token to the blacklist"""
        if not self.redis_store or not token_id:
            return

        # Add to blacklist with expiration (no need to keep forever)
        self.redis_store.redis.sadd("blacklisted_tokens", token_id)
        self.redis_store.redis.expire("blacklisted_tokens", self.default_token_expire_hours * 3600)

    def blacklist_all_user_tokens(self, user_id: str) -> int:
        """Blacklist all tokens for a user (when role changes)"""
        if not self.redis_store:
            return 0

        # Get all user's tokens
        user_tokens = self.redis_store.redis.smembers(f"user_tokens:{user_id}")

        # Blacklist each token
        blacklisted_count = 0
        for token_id in user_tokens:
            self.blacklist_token(token_id)
            blacklisted_count += 1

        # Clear user's token index
        self.redis_store.redis.delete(f"user_tokens:{user_id}")

        logger.info(f"Blacklisted {blacklisted_count} tokens for user {user_id}")
        return blacklisted_count

    def get_user_tokens(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active tokens for a user"""
        if not self.redis_store:
            return []

        token_ids = self.redis_store.redis.smembers(f"user_tokens:{user_id}")
        tokens = []

        for token_id in token_ids:
            # Skip blacklisted tokens
            if self._is_token_blacklisted(token_id):
                continue

            key = f"token_metadata:{user_id}:{token_id}"
            metadata = self.redis_store.redis.hgetall(key)

            if metadata:
                tokens.append({
                    "id": token_id,
                    "name": metadata.get("name", "API Token"),
                    "created_at": metadata.get("created_at"),
                    "expires_at": metadata.get("expires_at"),
                    "last_used": metadata.get("last_used"),
                    "expires_in_hours": metadata.get("expires_in_hours", str(self.default_token_expire_hours)),
                    "permissions": json.loads(metadata.get("permissions", "{}")) if metadata.get("permissions") else {}
                })

        return sorted(tokens, key=lambda x: x.get("created_at", ""), reverse=True)

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        """Revoke a specific token"""
        if not self.redis_store:
            return False

        # Blacklist the token
        self.blacklist_token(token_id)

        # Remove from user's token index
        self.redis_store.redis.srem(f"user_tokens:{user_id}", token_id)

        # Remove metadata
        self.redis_store.redis.delete(f"token_metadata:{user_id}:{token_id}")

        logger.info(f"Revoked token {token_id} for user {user_id}")
        return True

# Global instances - JWT manager needs Redis store injection
oauth_handler = OAuthHandler()
session_manager = SessionManager()
jwt_manager = None  # Will be initialized with Redis store


def initialize_jwt_manager(redis_store):
    """Initialize JWT manager with Redis store"""
    global jwt_manager
    jwt_manager = JWTManager(redis_store)

# Dependency functions for FastAPI
def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user (session cookies only)"""
    return oauth_handler.get_current_user(request)

def require_auth(request: Request) -> Dict[str, Any]:
    """FastAPI dependency to require authentication (session cookies only)"""
    return oauth_handler.require_auth(request)

# Hybrid authentication dependencies for API


def get_current_user_hybrid(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency to get current user supporting both session cookies and JWT Bearer tokens.
    Tries JWT first, falls back to session cookies.
    """
    # Try JWT Bearer token first
    if credentials and credentials.scheme.lower() == "bearer" and jwt_manager:
        user = jwt_manager.verify_access_token(credentials.credentials)
        if user:
            return user

    # Fall back to session cookies
    return oauth_handler.get_current_user(request)


def require_auth_hybrid(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    """
    FastAPI dependency to require authentication supporting both session cookies and JWT Bearer tokens.
    Tries JWT first, falls back to session cookies.
    """
    user = get_current_user_hybrid(request, credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid JWT Bearer token or login session.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def get_current_user_jwt_only(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user from JWT Bearer token only"""
    if credentials and credentials.scheme.lower() == "bearer" and jwt_manager:
        return jwt_manager.verify_access_token(credentials.credentials)
    return None


def require_auth_jwt_only(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """FastAPI dependency to require JWT Bearer token authentication only"""
    user = get_current_user_jwt_only(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid JWT Bearer token required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user
