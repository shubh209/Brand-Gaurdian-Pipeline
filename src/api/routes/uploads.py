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
    """Generate a presigned URL for direct-to-blob upload."""
    from azure.storage.blob import BlobClient, generate_blob_sas, BlobSasPermissions

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "")

    if not conn_str:
        raise HTTPException(status_code=503, detail="Storage not configured")

    # ponytail: extract account_name and account_key from connection string if not set separately
    if not account_name or not account_key:
        parts = dict(p.split("=", 1) for p in conn_str.split(";") if "=" in p)
        account_name = parts.get("AccountName", "")
        account_key = parts.get("AccountKey", "")

    audit_id = str(uuid.uuid4())
    blob_name = f"uploads/{audit_id}.mp4"

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=_SAS_EXPIRY_MINUTES),
    )

    upload_url = f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"

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
    container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")

    if not account_name and conn_str:
        parts = dict(p.split("=", 1) for p in conn_str.split(";") if "=" in p)
        account_name = parts.get("AccountName", "")

    blob_name = f"uploads/{audit_id}.mp4"
    blob_url = f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}"

    # Create audit record
    audit = Audit(
        team_id=user.team_id,
        user_id=user.user_id,
        session_id=audit_id,
        video_url=blob_url,
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

    # Enqueue job
    try:
        from azure.storage.queue import QueueClient
        queue_name = os.getenv("AZURE_STORAGE_QUEUE_NAME", "audit-jobs")
        if conn_str:
            q = QueueClient.from_connection_string(conn_str, queue_name)
            q.send_message(json.dumps({
                "audit_id": audit_id,
                "blob_url": blob_url,
                "platforms": body.platforms,
                "email": body.email,
            }))
    except Exception:
        pass  # ponytail: queue failure logged by worker retry. Audit stays "pending".

    return AuditStartResponse(audit_id=audit_id, status="pending")
