"""
Middleware
==========
1. Request logger — logs all requests to api.log
"""

import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from main.logger import get_logger

log = get_logger("api")

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
