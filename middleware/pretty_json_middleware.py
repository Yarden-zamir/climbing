import json
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from typing import Callable

logger = logging.getLogger("climbing_app")


class PrettyJSONMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically adds pretty printing support to all JSON API responses.

    Usage:
        - Add ?pretty=true to any API endpoint to get formatted JSON
        - Works automatically without modifying individual endpoints
        - Only applies to JSON responses from API routes
    """

    def __init__(self, app, api_prefix: str = "/api"):
        super().__init__(app)
        self.api_prefix = api_prefix

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get the response from the next middleware/endpoint
        response = await call_next(request)

        # Only process API endpoints
        if not request.url.path.startswith(self.api_prefix):
            return response

        # Only process if pretty parameter is requested
        pretty_param = request.query_params.get("pretty", "").lower()
        if pretty_param not in ("true", "1", "yes"):
            return response

        # Only process JSON responses
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("application/json"):
            return response

        try:
            # Read the response body
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            # Parse and re-format the JSON
            if body:
                json_data = json.loads(body.decode('utf-8'))
                pretty_json = json.dumps(
                    json_data,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True  # Optional: sort keys for consistent output
                )

                # Create new response with pretty JSON
                # Remove Content-Length header since content size changed
                headers = dict(response.headers)
                headers.pop('content-length', None)  # Remove if exists, case-insensitive
                headers.pop('Content-Length', None)  # Remove if exists

                new_response = StarletteResponse(
                    content=pretty_json,
                    status_code=response.status_code,
                    headers=headers,
                    media_type="application/json"
                )

                logger.debug(f"Pretty printed JSON response for {request.url.path}")
                return new_response

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # If JSON parsing fails, return original response
            logger.warning(f"Failed to pretty print JSON for {request.url.path}: {e}")

        return response
