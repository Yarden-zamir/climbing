"""
Rate limiting middleware for the climbing app.
"""

import time
from typing import Dict, Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis-based rate limiter"""
    
    def __init__(self, redis_store, max_requests: int = 200, window_seconds: int = 30):
        self.redis = redis_store.redis
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def is_allowed(self, key: str) -> bool:
        """Check if request is allowed based on rate limit"""
        current_time = int(time.time())
        window_start = current_time - self.window_seconds
        
        # Use Redis sorted set to track requests
        pipe = self.redis.pipeline()
        
        # Remove old requests
        pipe.zremrangebyscore(f"rate_limit:{key}", 0, window_start)
        
        # Count current requests
        pipe.zcard(f"rate_limit:{key}")
        
        # Add current request
        pipe.zadd(f"rate_limit:{key}", {str(current_time): current_time})
        
        # Set expiration
        pipe.expire(f"rate_limit:{key}", self.window_seconds)
        
        results = pipe.execute()
        current_requests = results[1]
        
        return current_requests < self.max_requests
    
    async def get_remaining_requests(self, key: str) -> int:
        """Get remaining requests for a key"""
        current_time = int(time.time())
        window_start = current_time - self.window_seconds
        
        # Clean up old requests and count
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"rate_limit:{key}", 0, window_start)
        pipe.zcard(f"rate_limit:{key}")
        
        results = pipe.execute()
        current_requests = results[1]
        
        return max(0, self.max_requests - current_requests)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware"""
    
    def __init__(self, app, redis_store, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.rate_limiter = RateLimiter(redis_store, max_requests, window_seconds)
        self.exempt_paths = {"/api/health", "/", "/static"}
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for static files and health checks
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        # Get client IP
        client_ip = self.get_client_ip(request)
        
        # Check rate limit
        if not await self.rate_limiter.is_allowed(client_ip):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": "60"}
            )
        
        # Get remaining requests for response headers
        remaining = await self.rate_limiter.get_remaining_requests(client_ip)
        
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.rate_limiter.window_seconds)
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """Get client IP address with proxy support"""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback to client host
        return request.client.host if request.client else "unknown"


class AuthRateLimiter:
    """Special rate limiter for authentication endpoints"""
    
    def __init__(self, redis_store, max_attempts: int = 5, window_seconds: int = 300):
        self.redis = redis_store.redis
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
    
    async def is_allowed(self, key: str) -> bool:
        """Check if auth attempt is allowed"""
        current_time = int(time.time())
        window_start = current_time - self.window_seconds
        
        # Use Redis sorted set to track attempts
        pipe = self.redis.pipeline()
        
        # Remove old attempts
        pipe.zremrangebyscore(f"auth_limit:{key}", 0, window_start)
        
        # Count current attempts
        pipe.zcard(f"auth_limit:{key}")
        
        results = pipe.execute()
        current_attempts = results[1]
        
        return current_attempts < self.max_attempts
    
    async def record_attempt(self, key: str, success: bool = False) -> None:
        """Record an authentication attempt"""
        current_time = int(time.time())
        
        # If successful, clear the attempts
        if success:
            self.redis.delete(f"auth_limit:{key}")
        else:
            # Record failed attempt
            self.redis.zadd(f"auth_limit:{key}", {str(current_time): current_time})
            self.redis.expire(f"auth_limit:{key}", self.window_seconds) 
