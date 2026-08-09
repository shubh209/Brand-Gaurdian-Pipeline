import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.schemas import AuditSummary, PaginatedAudits, AuditDetail, ViolationOut
from src.auth.dependencies import get_current_user, require_reviewer
from src.auth.models import UserContext
from src.db.models import Audit, AuditViolation
from src.db.repository import get_audit_for_team
from src.db.session import get_db

router = APIRouter(prefix="/audits", tags=["audits"])


class ViolationResponse(BaseModel):
    category: str
    severity: str
    description: str
    citation_source: str | None = None
    citation_excerpt: str | None = None
    chunk_id: str | None = None


class ReviewResponse(BaseModel):
    decision: str
    notes: str | None
    created_at: datetime


class AuditDetailResponse(BaseModel):
    id: str
    session_id: str
    video_url: str
    video_id: str
    ai_status: str
    final_status: str
    final_report: str
    ingestion_source: str | None
    policy_version_id: str | None
    processing_status: str | None = None
    audit_mode: str | None = None
    platforms: str | None = None
    created_at: datetime
    violations: list[ViolationResponse]
    reviews: list[ReviewResponse]


class AuditListItem(BaseModel):
    id: str
    session_id: str
    video_url: str
    ai_status: str
    final_status: str
    ingestion_source: str | None
    created_at: datetime


@router.get("", response_model=PaginatedAudits)
def list_audits(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Audit).filter(Audit.team_id == user.team_id)
    if status:
        query = query.filter(Audit.final_status == status.upper())
    if platform:
        query = query.filter(Audit.platforms.contains(platform))

    total = query.count()
    offset = (page - 1) * per_page
    audits = query.order_by(Audit.created_at.desc()).offset(offset).limit(per_page).all()

    return PaginatedAudits(
        data=[
            AuditSummary(
                id=str(a.id),
                session_id=a.session_id,
                video_url=a.video_url,
                final_status=a.final_status,
                violation_count=len(a.violations),
                platforms=a.platforms,
                processing_status=a.processing_status,
                created_at=a.created_at,
            )
            for a in audits
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{audit_id}", response_model=AuditDetail)
def get_audit(
    audit_id: uuid.UUID,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit = get_audit_for_team(db, audit_id, user.team_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    return AuditDetail(
        id=str(audit.id),
        session_id=audit.session_id,
        video_url=audit.video_url,
        video_id=audit.video_id,
        ai_status=audit.ai_status,
        final_status=audit.final_status,
        final_report=audit.final_report,
        ingestion_source=audit.ingestion_source,
        policy_version_id=str(audit.policy_version_id) if audit.policy_version_id else None,
        processing_status=audit.processing_status,
        audit_mode=audit.audit_mode,
        platforms=audit.platforms,
        file_hash=audit.file_hash,
        model_version=audit.model_version,
        created_at=audit.created_at,
        violations=[
            ViolationOut(
                category=v.category,
                severity=v.severity,
                description=v.description,
                citation_source=v.citation_source,
                citation_excerpt=v.citation_excerpt,
                chunk_id=v.chunk_id,
            )
            for v in audit.violations
        ],
    )


class EmailReportRequest(BaseModel):
    email: str


@router.post("/{audit_id}/email")
def email_audit_report(
    audit_id: uuid.UUID,
    body: EmailReportRequest,
    user: UserContext = Depends(require_reviewer),
    db: Session = Depends(get_db),
):
    audit = get_audit_for_team(db, audit_id, user.team_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    from src.services.export import export_audit_pdf
    from src.services.email_service import send_audit_report

    pdf_bytes = export_audit_pdf(db, audit_id, user.team_id)
    send_audit_report(body.email, str(audit_id), pdf_bytes)
    return {"status": "sent"}


# ── SSE Stream ────────────────────────────────────────────────────────────────
import asyncio
import json as _json
from fastapi.responses import StreamingResponse


# ponytail: polls DB every 5s. Ceiling: DB load under high concurrency.
# Upgrade path: Redis pub/sub or Postgres LISTEN/NOTIFY.
_SSE_POLL_INTERVAL = 5  # seconds
_SSE_TIMEOUT = 300  # 5 minutes


@router.get("/{audit_id}/stream")
async def stream_audit_status(
    audit_id: uuid.UUID,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE endpoint — streams audit status until complete or timeout."""
    audit = get_audit_for_team(db, audit_id, user.team_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    async def event_stream():
        elapsed = 0
        last_status = None
        progress_map = {
            "pending": 10, "transcribing": 30, "extracting_text": 50,
            "auditing": 70, "completed": 100, "failed": 0,
        }

        while elapsed < _SSE_TIMEOUT:
            # Refresh from DB
            db.expire_all()
            audit_fresh = db.query(Audit).filter(Audit.id == audit_id).first()
            if not audit_fresh:
                yield f"event: error\ndata: {_json.dumps({'error': 'Audit not found'})}\n\n"
                return

            current_status = audit_fresh.processing_status or "pending"
            progress = progress_map.get(current_status, 10)

            if current_status != last_status:
                last_status = current_status
                yield f"event: status\ndata: {_json.dumps({'status': current_status, 'progress': progress})}\n\n"

            if current_status == "completed":
                # Send full result
                violations = [
                    {"category": v.category, "severity": v.severity, "description": v.description,
                     "citation_source": v.citation_source, "chunk_id": v.chunk_id}
                    for v in audit_fresh.violations
                ]
                result = {
                    "audit_id": str(audit_fresh.id),
                    "status": audit_fresh.final_status,
                    "final_report": audit_fresh.final_report,
                    "violations": violations,
                    "violation_count": len(violations),
                }
                yield f"event: complete\ndata: {_json.dumps(result)}\n\n"
                return

            if current_status == "failed":
                yield f"event: error\ndata: {_json.dumps({'error': 'Audit processing failed'})}\n\n"
                return

            await asyncio.sleep(_SSE_POLL_INTERVAL)
            elapsed += _SSE_POLL_INTERVAL

        # Timeout
        yield f"event: error\ndata: {_json.dumps({'error': 'Stream timeout (5 min)'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
