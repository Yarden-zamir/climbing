import json
import secrets
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
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
        # Separate salt so an OAuth state token can never be replayed as a session cookie
        self.state_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="oauth-state")

    def create_session_token(self, user_data: Dict[str, Any]) -> str:
        """Create a signed session token containing user data"""
        return self.serializer.dumps(user_data)

    def verify_session_token_with_age(self, token: str) -> Optional[tuple[Dict[str, Any], float]]:
        """Verify a session token and return (user_data, age_in_seconds)"""
        try:
            user_data, issued_at = self.serializer.loads(
                token, max_age=settings.SESSION_MAX_AGE, return_timestamp=True
            )
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid session token: {e}")
            return None
        age_seconds = (datetime.now(timezone.utc) - issued_at).total_seconds()
        return user_data, age_seconds

    def verify_session_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a session token"""
        verified = self.verify_session_token_with_age(token)
        return verified[0] if verified else None

    def set_session_cookie(self, response: Response, user_data: Dict[str, Any]):
        """Set secure session cookie on response"""
        token = self.create_session_token(user_data)
        response.set_cookie(
            key="session",
            value=token,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
        )

    def clear_session_cookie(self, response: Response):
        """Clear session cookie"""
        response.delete_cookie(key="session")

    def create_oauth_state(self, next_path: str) -> str:
        """Create a signed OAuth state that carries the post-login return path"""
        return self.state_serializer.dumps({"nonce": secrets.token_urlsafe(16), "next": next_path})

    def verify_oauth_state(self, state: Optional[str]) -> Optional[str]:
        """Verify an OAuth state and return the embedded return path, or None when invalid"""
        if not state:
            return None
        try:
            data = self.state_serializer.loads(state, max_age=settings.OAUTH_STATE_MAX_AGE)
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid OAuth state: {e}")
            return None
        next_path = data.get("next") if isinstance(data, dict) else None
        return next_path if is_safe_next_path(next_path) else "/"


def is_safe_next_path(path: Any) -> bool:
    """Only same-origin relative paths are allowed as a post-login redirect"""
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//")


class SessionRefreshMiddleware(BaseHTTPMiddleware):
    """Sliding session expiry.

    Re-issues the session cookie when the token is older than SESSION_REFRESH_AFTER,
    or when a route stored fresh user data in request.state.fresh_session_user
    (for example /api/auth/user after an admin changed the user's role).
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        token = request.cookies.get("session")
        if not token:
            return response
        # Logout and the OAuth callback already set or clear the cookie: never override them
        if any(value.startswith("session=") for value in response.headers.getlist("set-cookie")):
            return response
        verified = session_manager.verify_session_token_with_age(token)
        if verified is None:
            return response
        user_data, age_seconds = verified
        fresh_user_data = getattr(request.state, "fresh_session_user", None)
        if fresh_user_data is None and age_seconds < settings.SESSION_REFRESH_AFTER:
            return response
        session_manager.set_session_cookie(response, fresh_user_data or user_data)
        return response


class OAuthHandler:
    """Handles Google OAuth 2.0 flow"""

    def __init__(self, session_manager: "SessionManager"):
        self.session_manager = session_manager

    def generate_auth_url(self, next_path: str = "/") -> str:
        """Generate Google OAuth authorization URL; next_path is carried in the signed state"""
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": f"{settings.BASE_URL}/auth/callback",
            "scope": " ".join(settings.OAUTH_SCOPES),
            "response_type": "code",
            "access_type": "offline",
            "state": self.session_manager.create_oauth_state(next_path),
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
                headers={"Accept": "application/json"},
            )

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code",
                )

            return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Google using access token"""
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(settings.GOOGLE_USERINFO_URL, headers=headers)

            if response.status_code != 200:
                logger.error(f"User info fetch failed: {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch user information",
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
                detail="Authentication required",
            )
        return user


class JWTManager:
    """Handles JWT token generation and validation"""

    def __init__(self, store=None):
        self.secret_key = settings.SECRET_KEY
        self.algorithm = "HS256"
        self.default_token_expire_hours = 24  # Default 24 hours
        self.store = store

    def create_access_token(
        self,
        user_data: Dict[str, Any],
        selected_permissions: Optional[Dict[str, bool]] = None,
        token_name: Optional[str] = None,
        expires_in_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a JWT access token with optional selective permissions and custom expiry"""
        now = datetime.utcnow()

        # Use custom expiry or default
        expiry_hours = (
            expires_in_hours
            if expires_in_hours is not None
            else self.default_token_expire_hours
        )
        expire = now + timedelta(hours=expiry_hours)

        # Use selective permissions if provided, otherwise use all user permissions
        permissions = (
            selected_permissions
            if selected_permissions is not None
            else user_data.get("permissions", {})
        )

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
            "token_name": token_name or "API Token",  # User-friendly name
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

        # Store token metadata in Redis for management
        if self.store:
            user_id_str = user_data.get("id")
            if user_id_str:
                self._store_token_metadata(
                    user_id_str,
                    token_id,
                    {
                        "name": token_name or "API Token",
                        "created_at": now.isoformat(),
                        "expires_at": expire.isoformat(),
                        "permissions": json.dumps(permissions) if permissions else "{}",
                        "last_used": "",
                        "expires_in_hours": str(expiry_hours),
                    },
                )

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expiry_hours * 3600,  # Convert hours to seconds
            "expires_at": expire.isoformat(),
        }

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token with blacklist checking"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Check if token is blacklisted
            if self.store and self._is_token_blacklisted(payload.get("jti")):
                logger.warning(f"Blacklisted JWT token attempted: {payload.get('jti')}")
                return None

            # Update last used timestamp for access tokens
            if payload.get("type") == "access" and self.store:
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
                "token_name": payload.get("token_name", "API Token"),
            }
        return None

    # Token management (persisted in the store)

    def _store_token_metadata(self, user_id: str, token_id: str, metadata: Dict[str, Any]) -> None:
        if not self.store:
            return
        # The JWT payload uses naive UTC; the store compares against local current_timestamp
        expires_local = (
            datetime.fromisoformat(metadata["expires_at"]).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        )
        self.store.create_token(
            token_id,
            user_id,
            metadata["name"],
            json.loads(metadata.get("permissions") or "{}"),
            expires_local,
        )

    def _update_token_last_used(self, user_id: str, token_id: str) -> None:
        if self.store and token_id:
            self.store.touch_token(token_id)

    def _is_token_blacklisted(self, token_id: str) -> bool:
        if not self.store or not token_id:
            return False
        return self.store.is_token_revoked(token_id)

    def blacklist_all_user_tokens(self, user_id: str) -> int:
        """Revoke every token of a user (when the role changes)"""
        if not self.store:
            return 0
        count = self.store.revoke_user_tokens(user_id)
        logger.info(f"Revoked {count} tokens for user {user_id}")
        return count

    def get_user_tokens(self, user_id: str) -> List[Dict[str, Any]]:
        if not self.store:
            return []
        tokens = self.store.list_tokens(user_id)
        for token in tokens:
            created = datetime.fromisoformat(token["created_at"])
            expires = datetime.fromisoformat(token["expires_at"])
            token["expires_in_hours"] = str(int((expires - created).total_seconds() // 3600))
        return tokens

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        if not self.store:
            return False
        revoked = self.store.revoke_token(user_id, token_id)
        if revoked:
            logger.info(f"Revoked token {token_id} for user {user_id}")
        return revoked


# Global instances - JWT manager needs Redis store injection
session_manager = SessionManager()
oauth_handler = OAuthHandler(session_manager)
jwt_manager = None  # Will be initialized with Redis store


def initialize_jwt_manager(store):
    """Initialize JWT manager with Redis store"""
    global jwt_manager
    jwt_manager = JWTManager(store)


# Dependency functions for FastAPI
def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user (session cookies only)"""
    return oauth_handler.get_current_user(request)


def require_auth(request: Request) -> Dict[str, Any]:
    """FastAPI dependency to require authentication (session cookies only)"""
    return oauth_handler.require_auth(request)


# Hybrid authentication dependencies for API


def get_current_user_hybrid(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
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


def require_auth_hybrid(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI dependency to require authentication supporting both session cookies and JWT Bearer tokens.
    Tries JWT first, falls back to session cookies.
    """
    user = get_current_user_hybrid(request, credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please sign in to continue",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_jwt_only(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user from JWT Bearer token only"""
    if credentials and credentials.scheme.lower() == "bearer" and jwt_manager:
        return jwt_manager.verify_access_token(credentials.credentials)
    return None


def require_auth_jwt_only(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """FastAPI dependency to require JWT Bearer token authentication only"""
    user = get_current_user_jwt_only(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid JWT Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
