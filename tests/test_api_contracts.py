"""
API contract tests: verify response schemas match what the frontend expects.
ponytail: mock DB + auth, test the serialization contract, not business logic.
"""
import os
import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("AUTH_DISABLED", "true")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient with mocked DB and auth."""
    from src.api.server import app
    from src.db.session import get_db
    from src.auth.dependencies import get_current_user
    from src.auth.models import UserContext, UserRole

    mock_db = MagicMock()

    def override_db():
        yield mock_db

    def override_user():
        return UserContext(
            user_id=uuid.uuid4(),
            team_id=uuid.uuid4(),
            entra_oid="test",
            email="test@test.com",
            role=UserRole.reviewer,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    c = TestClient(app)
    yield c, mock_db
    app.dependency_overrides.clear()


# ── Contract 1: GET /audits/{id} matches frontend AuditDetail ────────────────

def test_audit_detail_response_schema(client):
    """Response must have all fields the frontend AuditDetail interface expects."""
    c, mock_db = client

    mock_violation = MagicMock()
    mock_violation.category = "health_claim"
    mock_violation.severity = "critical"
    mock_violation.description = "Test violation"
    mock_violation.citation_source = "FTC Guide"
    mock_violation.citation_excerpt = "Must substantiate"
    mock_violation.chunk_id = "chunk-001"

    mock_audit = MagicMock()
    mock_audit.id = uuid.uuid4()
    mock_audit.session_id = str(uuid.uuid4())
    mock_audit.video_url = "https://youtu.be/abc"
    mock_audit.video_id = "abc"
    mock_audit.ai_status = "FAIL"
    mock_audit.final_status = "FAIL"
    mock_audit.final_report = "1 violation found"
    mock_audit.ingestion_source = "upload"
    mock_audit.policy_version_id = None
    mock_audit.processing_status = "completed"
    mock_audit.audit_mode = "file"
    mock_audit.platforms = "youtube"
    mock_audit.file_hash = "sha256abc"
    mock_audit.model_version = "gpt-4o"
    mock_audit.created_at = datetime(2026, 7, 27, 12, 0, 0)
    mock_audit.violations = [mock_violation]

    with patch("src.api.routes.audits.get_audit_for_team", return_value=mock_audit):
        resp = c.get(f"/audits/{mock_audit.id}")

    assert resp.status_code == 200
    data = resp.json()

    # All fields the frontend AuditDetail interface expects:
    assert "id" in data
    assert "session_id" in data
    assert "video_url" in data
    assert "video_id" in data
    assert "ai_status" in data
    assert "final_status" in data
    assert "final_report" in data
    assert "ingestion_source" in data
    assert "processing_status" in data
    assert "audit_mode" in data
    assert "platforms" in data
    assert "file_hash" in data
    assert "model_version" in data
    assert "created_at" in data
    assert "violations" in data
    assert isinstance(data["violations"], list)

    # Violation schema
    v = data["violations"][0]
    assert "category" in v
    assert "severity" in v
    assert "description" in v
    assert "citation_source" in v
    assert "citation_excerpt" in v
    assert "chunk_id" in v


# ── Contract 2: POST /uploads/presign response schema ────────────────────────

def test_presign_response_schema(client):
    """Response must have {upload_url, blob_name, audit_id}."""
    c, mock_db = client

    # Mock Azure storage so the endpoint doesn't crash
    with patch.dict(os.environ, {
        "AZURE_STORAGE_CONNECTION_STRING": "AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net",
        "AZURE_STORAGE_CONTAINER": "uploads",
    }):
        # generate_blob_sas is imported inside the function body
        with patch("azure.storage.blob.generate_blob_sas", return_value="sig=mock"):
            resp = c.post("/uploads/presign")

    assert resp.status_code == 200
    data = resp.json()

    assert "upload_url" in data
    assert "blob_name" in data
    assert "audit_id" in data
    assert isinstance(data["upload_url"], str)
    assert isinstance(data["audit_id"], str)
    assert len(data["audit_id"]) == 36  # UUID format


# ── Contract 3: POST /prompt/generate response schema ────────────────────────

def test_prompt_generate_response_schema(client):
    """Response must have {prompt, platform, ai_tool, policy_sources_used, tools_recommended}."""
    c, mock_db = client

    resp = c.post("/prompt/generate", json={
        "brief": "Weight loss supplement for women 25-45",
        "platform": "youtube",
        "ai_tool": "cursor",
        "output_format": "json",
        "model": "gpt-4o",
    })

    assert resp.status_code == 200
    data = resp.json()

    assert "prompt" in data
    assert "platform" in data
    assert "ai_tool" in data
    assert "policy_sources_used" in data
    assert "tools_recommended" in data
    assert isinstance(data["prompt"], str)
    assert isinstance(data["policy_sources_used"], int)
    assert isinstance(data["tools_recommended"], list)
    assert len(data["prompt"]) > 50  # Should be a substantial prompt


# ── Contract 4: GET /audits paginated response schema ────────────────────────

def test_audits_list_response_schema(client):
    """Response must have {data: [...], total, page, per_page}."""
    c, mock_db = client

    # Mock the DB query to return empty list
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []
    mock_query.count.return_value = 0
    mock_db.query.return_value = mock_query

    resp = c.get("/audits?page=1&per_page=10")

    assert resp.status_code == 200
    data = resp.json()

    assert "data" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert isinstance(data["data"], list)
    assert isinstance(data["total"], int)
    assert data["page"] == 1
    assert data["per_page"] == 10
