"""
Observability middleware: correlation ID injection and latency tracking.
Every request gets an audit_id/correlation_id attached to logs.
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("brand-guardian.api")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Injects correlation ID into response headers and logs request latency."""

    async def dispatch(self, request: Request, call_next):
        # Use existing audit_id from path or generate a correlation ID
        correlation_id = request.headers.get("x-correlation-id", str(uuid.uuid4())[:8])

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.0f}"

        logger.info(
            "request_completed method=%s path=%s status=%d latency_ms=%.0f correlation_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            correlation_id,
        )

        return response
