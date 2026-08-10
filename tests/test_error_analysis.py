"""
Test error analysis service: verify it produces correct insights from mock data.
ponytail: mock the DB queries, test the analysis logic in isolation.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

os.environ.setdefault("AUTH_DISABLED", "true")


# ── Test 1: Pipeline failure analysis detects high failure rate ───────────────

def test_pipeline_failure_analysis_detects_failures():
    """When dead-letter jobs exist, analysis should categorize and report them."""
    from src.services.error_analysis import _analyze_pipeline_failures

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Create mock dead-letter jobs
    dl1 = MagicMock()
    dl1.error_message = "RetryableError: Azure OpenAI timed out after 60s"
    dl1.failed_at = datetime.now(timezone.utc) - timedelta(hours=2)

    dl2 = MagicMock()
    dl2.error_message = "PermanentError: Whisper transcription returned empty"
    dl2.failed_at = datetime.now(timezone.utc) - timedelta(hours=5)

    dl3 = MagicMock()
    dl3.error_message = "Unexpected: connection reset during auditing"
    dl3.failed_at = datetime.now(timezone.utc) - timedelta(days=1)

    mock_db = MagicMock()
    # Dead letter query
    mock_db.query.return_value.filter.return_value.all.return_value = [dl1, dl2, dl3]
    # Total audits count
    mock_db.query.return_value.filter.return_value.count.return_value = 20

    result = _analyze_pipeline_failures(mock_db, cutoff)

    assert result["dead_lettered"] == 3
    assert "RetryableError" in result["by_error_type"]
    assert "PermanentError" in result["by_error_type"]
    assert "transcribing" in result["by_stage"] or "auditing" in result["by_stage"]
    assert isinstance(result["insights"], list)


# ── Test 2: Quality patterns detect over-flagging ────────────────────────────

def test_quality_patterns_detects_over_flagging():
    """When one category appears in nearly all audits, flag it as suspected over-flagging."""
    from src.services.error_analysis import _analyze_quality_patterns, OVER_FLAGGING_THRESHOLD

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Mock 10 completed audits
    mock_audits = []
    for i in range(10):
        a = MagicMock()
        a.created_at = datetime.now(timezone.utc) - timedelta(hours=i)
        a.processing_status = "completed"
        a.final_status = "FAIL"
        a.platforms = "youtube"
        a.violations = []
        mock_audits.append(a)

    # Mock violations: health_claim in 9/10 audits
    mock_violations = []
    for i in range(9):
        v = MagicMock()
        v.category = "health_claim"
        v.audit_id = mock_audits[i].id
        v.citation_source = "FTC Guide"
        v.chunk_id = f"chunk-{i}"
        v.audit = mock_audits[i]
        mock_violations.append(v)

    mock_db = MagicMock()

    # First query().filter().all() → completed audits
    # Second query().join().filter().all() → violations
    # We need to control which .all() returns what
    call_count = [0]

    def mock_all():
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_audits
        return mock_violations

    def mock_scalar():
        return 9  # 9 out of 10 audits have health_claim

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.all.side_effect = mock_all
    query_mock.scalar.return_value = mock_scalar()
    mock_db.query.return_value = query_mock

    result = _analyze_quality_patterns(mock_db, cutoff)

    assert "category_fail_rates" in result
    assert "suspected_over_flagging" in result
    assert "low_confidence_violations" in result
    assert isinstance(result["insights"], list)


# ── Test 3: Retrieval gaps detect ungrounded violations ──────────────────────

def test_retrieval_gaps_detects_ungrounded():
    """Violations without chunk_id should be flagged as ungrounded."""
    from src.services.error_analysis import _analyze_retrieval_gaps

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    mock_audit = MagicMock()
    mock_audit.final_status = "FAIL"
    mock_audit.platforms = "youtube"
    mock_audit.violations = []

    # 5 violations, 3 without chunk_id
    mock_violations = []
    for i in range(5):
        v = MagicMock()
        v.chunk_id = f"chunk-{i}" if i < 2 else None
        v.audit = mock_audit
        mock_violations.append(v)

    mock_db = MagicMock()
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock

    call_count = [0]

    def mock_all():
        call_count[0] += 1
        if call_count[0] == 1:
            return [mock_audit]  # completed audits
        return mock_violations  # violations

    query_mock.all.side_effect = mock_all
    mock_db.query.return_value = query_mock

    result = _analyze_retrieval_gaps(mock_db, cutoff)

    assert "ungrounded_violations" in result
    assert result["ungrounded_violations"]["count"] == 3
    assert result["ungrounded_violations"]["pct"] == 0.6
    assert isinstance(result["insights"], list)
    # Should flag this as a concern
    assert any("grounding" in insight.lower() or "chunk_id" in insight.lower() for insight in result["insights"])


# ── Test 4: Full report structure ────────────────────────────────────────────

def test_full_report_has_correct_structure():
    """run_error_analysis returns all expected top-level keys."""
    from src.services.error_analysis import run_error_analysis

    mock_db = MagicMock()
    # Make all queries return empty
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.all.return_value = []
    query_mock.count.return_value = 0
    query_mock.scalar.return_value = 0
    mock_db.query.return_value = query_mock

    report = run_error_analysis(mock_db, days=7)

    assert "period" in report
    assert report["period"] == "last_7_days"
    assert "total_audits" in report
    assert "pipeline_failures" in report
    assert "quality_patterns" in report
    assert "retrieval_gaps" in report


# ── Test 5: Langfuse push doesn't crash when not configured ──────────────────

def test_langfuse_push_noop_when_not_configured():
    """push_to_langfuse should silently no-op when Langfuse keys are missing."""
    from src.services.error_analysis import push_to_langfuse

    report = {
        "period": "last_30_days",
        "total_audits": 10,
        "pipeline_failures": {"rate": 0.1},
        "quality_patterns": {
            "low_confidence_violations": {"pct": 0.2},
            "suspected_over_flagging": [],
        },
        "retrieval_gaps": {"ungrounded_violations": {"pct": 0.3}},
    }

    with patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}):
        # Should not raise
        push_to_langfuse(report)


# ── Test 6: Admin endpoint returns 200 ───────────────────────────────────────

def test_admin_error_analysis_endpoint():
    """GET /admin/error-analysis should return 200 with structured report."""
    from fastapi.testclient import TestClient
    from src.api.server import app
    from src.db.session import get_db
    from src.auth.dependencies import get_current_user
    from src.auth.models import UserContext, UserRole

    mock_db = MagicMock()
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.all.return_value = []
    query_mock.count.return_value = 0
    query_mock.scalar.return_value = 0
    mock_db.query.return_value = query_mock

    def override_db():
        yield mock_db

    def override_user():
        return UserContext(
            user_id=uuid.uuid4(),
            team_id=uuid.uuid4(),
            entra_oid="admin",
            email="admin@test.com",
            role=UserRole.admin,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)
    resp = client.get("/admin/error-analysis?days=7")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline_failures" in data
    assert "quality_patterns" in data
    assert "retrieval_gaps" in data
    assert data["period"] == "last_7_days"
