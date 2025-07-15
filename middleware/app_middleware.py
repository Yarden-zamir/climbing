from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class CaseInsensitiveMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Only make API routes case insensitive, not static file routes
        if request.url.path.startswith("/api/"):
            scope = dict(request.scope)  # Create a copy
            scope["path"] = request.url.path.lower()
            scope["raw_path"] = request.url.path.lower().encode()
            request = Request(scope, request.receive)

        response = await call_next(request)
        return response


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Apply no-cache headers to static assets and HTML pages
        path = request.url.path

        # Cache-bust CSS, JS, and HTML files
        if (path.endswith((".css", ".js", ".html")) or
            path in ["/", "/albums", "/memes", "/crew"] or
                path.startswith("/static/")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response 
