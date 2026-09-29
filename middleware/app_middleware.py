from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _route_paths(routes) -> list[str]:
    """Flatten route paths; included routers (Starlette >= 1.0) nest their routes."""
    paths: list[str] = []
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
        nested = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if nested:
            paths.extend(_route_paths(nested))
    return paths


class CaseInsensitiveMiddleware(BaseHTTPMiddleware):
    """Lowercase paths (/Albums, /API/Crew) that match a route without path parameters.

    Paths with parameters (for example /api/skills/{skill_name}) are left as-is so that
    mixed-case identifiers reach the handler unchanged.
    """

    def __init__(self, app):
        super().__init__(app)
        self._static_paths: frozenset[str] | None = None

    def _get_static_paths(self, request: Request) -> frozenset[str]:
        if self._static_paths is None:
            self._static_paths = frozenset(
                path for path in _route_paths(request.app.routes) if "{" not in path
            )
        return self._static_paths

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path != path.lower() and path.lower() in self._get_static_paths(request):
            # call_next routes on the original scope object, so mutate it in place
            request.scope["path"] = path.lower()
            request.scope["raw_path"] = path.lower().encode()

        return await call_next(request)


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
