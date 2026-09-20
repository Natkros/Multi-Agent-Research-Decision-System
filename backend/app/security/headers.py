"""Security response headers (Phase 8, brief §27). A small ASGI middleware
rather than per-route code -- these apply uniformly to every response,
including error responses, which per-route code would miss."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Baseline CSP for a JSON API: no script/style/frame sources are
        # ever served from this origin, so a maximally restrictive default
        # is safe and doesn't need per-route tuning.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        # HSTS only makes sense once the deployment actually terminates
        # HTTPS -- setting it on a plain-HTTP dev server would be a lie the
        # browser then enforces.
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response
