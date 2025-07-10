import json
import secrets
import httpx
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
import logging

from config import settings

logger = logging.getLogger(__name__)

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

# Global instances
oauth_handler = OAuthHandler()
session_manager = SessionManager()

# Dependency functions for FastAPI
def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user"""
    return oauth_handler.get_current_user(request)

def require_auth(request: Request) -> Dict[str, Any]:
    """FastAPI dependency to require authentication"""
    return oauth_handler.require_auth(request) 
