"""
Middleware
==========
1. Auth middleware — validates Bearer token on every protected route
2. Rate limiter — per-endpoint per-IP limits
3. Request logger — logs all requests to api.log
4. Security headers — adds standard security headers to all responses

Protected routes: everything except /api/auth/*, /static/*, /
"""

import time
from collections import defaultdict
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from main.db import validate_session
from main.logger import get_logger

log = get_logger("api")

# Routes that do NOT require auth
PUBLIC_PATHS = {
    "/",
    "/api/auth/login",
    "/api/auth/register",
    "/api/health",
}

class AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on every non-public route."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths and static file serving
        if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/styles") or path.startswith("/js"):
            return await call_next(request)

        # Allow auth page
        if path == "/auth":
            return await call_next(request)

        # Allow API docs in debug
        if path.startswith("/api/docs") or path.startswith("/openapi"):
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"}
            )

        raw_token = auth_header[7:]
        session = validate_session(raw_token)
        if not session:
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired or invalid. Please log in again."}
            )

        # Attach session info to request state for use in route handlers
        request.state.user_id = session["user_id"]
        request.state.username = session["username"]
        request.state.session_id = session["id"]
        request.state.raw_token = raw_token

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter.
    Limits: /api/auth/login, /api/auth/register → 5 req/min per IP
            /api/order/* → 10 req/min per user
            others → 120 req/min per IP
    """
    # Paths that get the strict auth rate limit (not /me, /session, etc.)
    AUTH_LIMITED_PATHS = {"/api/auth/login", "/api/auth/register"}

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict = defaultdict(list)
        self._last_cleanup = time.time()

    def _is_limited(self, key: str, max_hits: int, window: int = 60) -> bool:
        now = time.time()
        # Periodic cleanup: every 120s, remove all stale entries
        if now - self._last_cleanup > 120:
            stale_keys = [k for k, v in self._hits.items() if not v or now - v[-1] > window]
            for k in stale_keys:
                del self._hits[k]
            self._last_cleanup = now

        hits = [t for t in self._hits[key] if now - t < window]
        self._hits[key] = hits
        if len(hits) >= max_hits:
            return True
        self._hits[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip = request.client.host if request.client else "unknown"

        if path in self.AUTH_LIMITED_PATHS:
            if self._is_limited(f"auth:{ip}", max_hits=5):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many login attempts. Please wait 60 seconds."}
                )
        elif path.startswith("/api/order"):
            user_id = getattr(request.state, "user_id", ip)
            if self._is_limited(f"order:{user_id}", max_hits=10):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Order rate limit exceeded. Max 10 orders per minute."}
                )
        else:
            if self._is_limited(f"api:{ip}", max_hits=120):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded."}
                )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Log every API request with timing."""
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000
        level = "warning" if response.status_code >= 400 else "info"
        getattr(log, level)(
            f"{request.method} {request.url.path} | "
            f"status={response.status_code} | time={elapsed:.1f}ms"
        )
        return response
