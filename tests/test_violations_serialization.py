"""
Test: GET /audits/{id} returns structured violations in the response.
ponytail: one test, minimal mocking, verifies the serialization path end-to-end.
"""
import os
import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_DISABLED", "true")


@pytest.fixture
def client_with_violations():
    """TestClient with a mocked audit that has violations."""
    with patch.dict(os.environ, {"AUTH_DISABLED": "true"}):
        from src.api.server import app
        from src.db.session import get_db
        from src.auth.dependencies import get_current_user
        from src.auth.models import UserContext, UserRole

        audit_id = uuid.uuid4()
        team_id = uuid.uuid4()

        # Build a mock Audit with violations
        mock_violation = MagicMock()
        mock_violation.category = "health_claim"
        mock_violation.severity = "critical"
        mock_violation.description = "Unsubstantiated weight loss claim"
        mock_violation.citation_source = "FTC Dietary Supplements Guide"
        mock_violation.citation_excerpt = "Advertisers must have adequate substantiation"
        mock_violation.chunk_id = "ftc-dietary-001"

        mock_audit = MagicMock()
        mock_audit.id = audit_id
        mock_audit.session_id = str(uuid.uuid4())
        mock_audit.video_url = "https://youtu.be/test123"
        mock_audit.video_id = "test123"
        mock_audit.ai_status = "FAIL"
        mock_audit.final_status = "FAIL"
        mock_audit.final_report = "2 violations found"
        mock_audit.ingestion_source = "upload"
        mock_audit.policy_version_id = None
        mock_audit.processing_status = "completed"
        mock_audit.audit_mode = "file"
        mock_audit.platforms = "youtube"
        mock_audit.file_hash = "abc123"
        mock_audit.model_version = "gpt-4o"
        mock_audit.created_at = datetime(2026, 7, 27, 12, 0, 0)
        mock_audit.violations = [mock_violation]

        mock_session = MagicMock()

        # get_audit_for_team returns our mock audit
        def override_get_db():
            yield mock_session

        def override_user():
            return UserContext(
                user_id=uuid.uuid4(),
                team_id=team_id,
                entra_oid="test-user",
                email="test@example.com",
                role=UserRole.reviewer,
            )

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_user

        # Patch get_audit_for_team to return our mock
        with patch("src.api.routes.audits.get_audit_for_team", return_value=mock_audit):
            c = TestClient(app)
            yield c, audit_id

        app.dependency_overrides.clear()


def test_get_audit_returns_violations(client_with_violations):
    """Verify GET /audits/{id} serializes violations correctly."""
    client, audit_id = client_with_violations
    resp = client.get(f"/audits/{audit_id}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["final_status"] == "FAIL"
    assert "violations" in data
    assert len(data["violations"]) == 1

    v = data["violations"][0]
    assert v["category"] == "health_claim"
    assert v["severity"] == "critical"
    assert v["description"] == "Unsubstantiated weight loss claim"
    assert v["citation_source"] == "FTC Dietary Supplements Guide"
    assert v["citation_excerpt"] == "Advertisers must have adequate substantiation"
    assert v["chunk_id"] == "ftc-dietary-001"
