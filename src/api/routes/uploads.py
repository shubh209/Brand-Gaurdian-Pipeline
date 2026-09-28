"""Presigned upload URL + audit start endpoints."""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.schemas import PresignResponse, AuditStartResponse
from src.auth.dependencies import get_current_user, require_audit_submitter
from src.auth.models import UserContext
from src.db.models import Audit
from src.db.session import get_db

router = APIRouter(prefix="/uploads", tags=["uploads"])

# ponytail: SAS token valid 5 minutes. Upgrade: make configurable via config.py.
_SAS_EXPIRY_MINUTES = 5


@router.post("/presign", response_model=PresignResponse)
def presign_upload(
    user: UserContext = Depends(require_audit_submitter),
):
    """Generate a signed URL for direct-to-storage upload (Supabase Storage)."""
    from src.services import storage

    audit_id = str(uuid.uuid4())
    blob_name = storage.key_for_audit(audit_id)

    try:
        upload_url = storage.presign_upload(blob_name)
    except Exception:
        raise HTTPException(status_code=503, detail="Storage not configured")

    return PresignResponse(
        upload_url=upload_url,
        blob_name=blob_name,
        audit_id=audit_id,
    )


class AuditStartRequest(BaseModel):
    platforms: list[str] = ["youtube"]
    email: str | None = None


@router.post("/{audit_id}/start", response_model=AuditStartResponse)
def start_audit(
    audit_id: str,
    body: AuditStartRequest,
    user: UserContext = Depends(require_audit_submitter),
    db: Session = Depends(get_db),
):
    """Tell backend the file is uploaded — enqueue processing job."""
    from src.services import storage, queue as job_queue

    blob_key = storage.key_for_audit(audit_id)

    # Create audit record
    audit = Audit(
        team_id=user.team_id,
        user_id=user.user_id,
        session_id=audit_id,
        video_url=blob_key,
        video_id=f"vid_{audit_id[:8]}",
        ai_status="PENDING",
        final_status="PENDING",
        final_report="",
        processing_status="pending",
        audit_mode="file",
        platforms=",".join(body.platforms),
    )
    db.add(audit)
    db.commit()

    # Enqueue job on the Postgres queue
    try:
        job_queue.enqueue({
            "audit_id": audit_id,
            "blob_key": blob_key,
            "platforms": body.platforms,
            "email": body.email,
        })
    except Exception:
        pass  # ponytail: queue failure leaves the audit "pending"; client can retry start.

    return AuditStartResponse(audit_id=audit_id, status="pending")
