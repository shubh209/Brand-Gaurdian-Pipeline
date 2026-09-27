"""
Shared pytest fixtures.

The rate limiter is Postgres-backed and persists hits across runs (by design, so
limits survive deploys). In tests that hit real POST endpoints this accumulates
`rate_limit_hits` rows and eventually trips a spurious 429. Reset the table before
each test so rate-limit state is deterministic and isolated per test.

Tests that mock the DB (e.g. test_rate_limiter.py) are unaffected — this only touches
the real table, which those tests never use.
"""
import pytest
from sqlalchemy import text

from src.db.session import engine


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # ponytail: truncate before each test. Cheap on a tiny table; keeps 429s deterministic.
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_hits"))
    except Exception:
        # DB unavailable (e.g. fully mocked/offline test) — nothing to reset.
        pass
    yield
