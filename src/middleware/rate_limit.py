"""
Postgres-backed rate limiter. Persists across restarts and deploys.
Sliding window: count requests in last N seconds per key+endpoint.
"""
import time
from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.db.session import SessionLocal
from src.db.models import RateLimitHit

# ponytail: configurable per-endpoint limits. Upgrade path: load from DB/config.
LIMITS = {
    "/audit/upload": {"max": 5, "window": 3600},    # 5 per hour
    "/audit": {"max": 10, "window": 3600},           # 10 per hour
    "/admin": {"max": 100, "window": 3600},          # 100 per hour
}
DEFAULT_LIMIT = {"max": 30, "window": 60}            # 30 per minute


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Postgres-backed sliding window rate limiter."""

    def _client_key(self, request: Request) -> str:
        # Prefer API key if present, else IP
        api_key = request.headers.get("x-api-key", "")
        if api_key:
            return f"key:{api_key[:16]}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        if request.client:
            return f"ip:{request.client.host}"
        return "ip:unknown"

    def _get_limit(self, path: str) -> dict:
        for prefix, limit in LIMITS.items():
            if path.startswith(prefix):
                return limit
        return DEFAULT_LIMIT

    async def dispatch(self, request: Request, call_next):
        # Only rate-limit POST requests
        if request.method != "POST":
            return await call_next(request)

        key = self._client_key(request)
        path = request.url.path
        limit_config = self._get_limit(path)
        max_requests = limit_config["max"]
        window = limit_config["window"]

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=window)

        db = SessionLocal()
        try:
            # Count hits in window
            count = (
                db.query(RateLimitHit)
                .filter(
                    RateLimitHit.key == key,
                    RateLimitHit.endpoint == path,
                    RateLimitHit.hit_at >= window_start,
                )
                .count()
            )

            remaining = max(0, max_requests - count)
            reset_at = int((now + timedelta(seconds=window)).timestamp())

            if count >= max_requests:
                retry_after = window  # seconds until window resets
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "rate_limited", "message": "Rate limit exceeded. Try again later."}},
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_at),
                        "Retry-After": str(retry_after),
                    },
                )

            # Record this hit
            db.add(RateLimitHit(key=key, endpoint=path))
            db.commit()
        except Exception:
            # ponytail: if DB is down, allow the request (fail open).
            # Ceiling: attacker can bypass during DB outage.
            # Upgrade path: fall back to in-memory counter.
            db.rollback()
            remaining = max_requests
            reset_at = int((now + timedelta(seconds=window)).timestamp())
        finally:
            db.close()

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining - 1))
        response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response
