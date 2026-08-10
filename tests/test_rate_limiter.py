"""
Rate limiter tests: verify Postgres-backed sliding window rate limiting.
ponytail: mock the DB layer, test the middleware logic in isolation.
"""
import os
import uuid
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("AUTH_DISABLED", "true")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient with mocked auth. DB is mocked per-test for rate limit control."""
    from src.api.server import app
    from src.auth.dependencies import get_current_user
    from src.auth.models import UserContext, UserRole

    def override_user():
        return UserContext(
            user_id=uuid.uuid4(),
            team_id=uuid.uuid4(),
            entra_oid="test",
            email="test@test.com",
            role=UserRole.reviewer,
        )

    app.dependency_overrides[get_current_user] = override_user
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ── Test 1: Rate limit returns 429 after exceeding max ───────────────────────

def test_rate_limit_returns_429_after_max(client):
    """POST /audit should return 429 after exceeding the configured limit."""
    from src.db.session import SessionLocal

    call_count = [0]

    def mock_session_factory():
        """Return a mock session that tracks request count."""
        session = MagicMock()
        # Simulate count exceeding limit (10 for /audit)
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 10  # at limit
        session.query.return_value = query_mock
        session.commit.return_value = None
        session.rollback.return_value = None
        session.close.return_value = None
        return session

    with patch("src.middleware.rate_limit.SessionLocal", side_effect=lambda: mock_session_factory()):
        resp = client.post("/audit", json={"video_url": "https://youtu.be/test"})

    assert resp.status_code == 429
    data = resp.json()
    assert data["error"]["code"] == "rate_limited"


# ── Test 2: Rate limit headers present on successful request ─────────────────

def test_rate_limit_headers_present(client):
    """Successful POST should include X-RateLimit-* headers."""
    from src.db.session import get_db

    def mock_session_factory():
        session = MagicMock()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0  # well under limit
        session.query.return_value = query_mock
        session.commit.return_value = None
        session.close.return_value = None
        return session

    # Mock rate limiter DB to allow request, mock endpoint DB to avoid real queries
    with patch("src.middleware.rate_limit.SessionLocal", side_effect=lambda: mock_session_factory()):
        app_db = MagicMock()
        from src.api.server import app
        from src.db.session import get_db

        def override_db():
            yield app_db

        app.dependency_overrides[get_db] = override_db
        resp = client.post("/prompt/generate", json={
            "brief": "test",
            "platform": "youtube",
            "ai_tool": "cursor",
            "output_format": "json",
            "model": "gpt-4o",
        })
        app.dependency_overrides.pop(get_db, None)

    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers


# ── Test 3: GET requests are not rate limited ────────────────────────────────

def test_get_requests_not_rate_limited(client):
    """GET requests should bypass rate limiting entirely."""
    from src.db.session import get_db
    from src.api.server import app

    app_db = MagicMock()
    # Return empty audit list
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.offset.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.all.return_value = []
    query_mock.count.return_value = 0
    app_db.query.return_value = query_mock

    def override_db():
        yield app_db

    app.dependency_overrides[get_db] = override_db

    # GET /audits should work even without rate limiter DB
    # (rate limiter only intercepts POST)
    resp = client.get("/audits?page=1&per_page=5")

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    # No rate limit headers on GET (middleware skips it)
    # ponytail: the middleware adds headers only to POST responses it processes
    assert "x-ratelimit-limit" not in resp.headers


# ── Test 4: Different endpoints have different limits ────────────────────────

def test_different_endpoints_different_limits():
    """Upload endpoint has limit 5/hour, audit has 10/hour."""
    from src.middleware.rate_limit import LIMITS

    assert LIMITS["/audit/upload"]["max"] == 5
    assert LIMITS["/audit/upload"]["window"] == 3600
    assert LIMITS["/audit"]["max"] == 10
    assert LIMITS["/audit"]["window"] == 3600
    assert LIMITS["/admin"]["max"] == 100
