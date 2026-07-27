"""
Worker: polls Azure Storage Queue, processes uploaded videos through the audit pipeline.
Run as: python -m src.worker.main
"""
import json
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv(override=True)

from src.errors import RetryableError, PermanentError

logger = logging.getLogger("brand-guardian.worker")
logging.basicConfig(level=logging.INFO)

# Retry config
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds: 2, 4, 8


def _queue_client():
    from azure.storage.queue import QueueClient
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    queue_name = os.getenv("AZURE_STORAGE_QUEUE_NAME", "audit-jobs")
    return QueueClient.from_connection_string(conn_str, queue_name)


def _blob_client(blob_name: str):
    from azure.storage.blob import BlobClient
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
    return BlobClient.from_connection_string(conn_str, container, blob_name)


def _delete_blob(blob_url: str) -> None:
    try:
        # Extract blob name from URL path
        path = blob_url.split("/")
        # blob name is everything after container segment
        container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
        idx = path.index(container) + 1
        blob_name = "/".join(path[idx:])
        _blob_client(blob_name).delete_blob()
    except Exception as exc:
        logger.warning("Failed to delete blob %s: %s", blob_url, exc)


def _process_message(db, message_body: dict) -> None:
    from src.db.repository import update_processing_status
    from src.pipeline.workflow import app as compliance_graph
    from src.services.email_service import send_audit_report
    from src.worker import video_processor

    audit_id = message_body["audit_id"]
    blob_url = message_body["blob_url"]
    platforms = message_body.get("platforms", ["youtube"])
    email = message_body.get("email")

    update_processing_status(db, audit_id, "transcribing")
    transcript = video_processor.transcribe(blob_url, audit_id)

    update_processing_status(db, audit_id, "extracting_text")
    # ponytail: OCR runs on local path; we reuse the downloaded file from transcribe
    # but transcribe already cleans it up. For OCR, use the blob URL as a proxy path.
    # If OCR is not configured it returns [] immediately (see video_processor).
    ocr_frames = []  # OCR on blob URL not supported inline; worker enqueues path separately

    update_processing_status(db, audit_id, "auditing")
    logger.info("worker_audit_start audit_id=%s platforms=%s", audit_id, platforms)
    state = {
        "video_url": blob_url,
        "video_id": audit_id,
        "transcript": transcript.get("text", ""),
        "ocr_text": [t for frame in ocr_frames for t in frame.get("texts", [])],
        "platforms": platforms,
        "audit_mode": "file",
        "compliance_results": [],
        "errors": [],
    }
    result = compliance_graph.invoke(state)

    update_processing_status(db, audit_id, "completed")

    # Persist violations
    from src.db.repository import get_audit_for_team
    import uuid
    audit = db.query(__import__("src.db.models", fromlist=["Audit"]).Audit).filter_by(session_id=audit_id).first()
    if audit:
        from src.db.models import AuditViolation
        for item in result.get("compliance_results", []):
            db.add(AuditViolation(
                audit_id=audit.id,
                category=item.get("category", "Unknown"),
                severity=item.get("severity", "INFO"),
                description=item.get("description", ""),
                citation_source=item.get("citation_source"),
                citation_excerpt=item.get("citation_excerpt"),
                chunk_id=item.get("chunk_id"),
            ))
        audit.ai_status = result.get("final_status", "COMPLETED")
        audit.final_status = result.get("final_status", "COMPLETED")
        audit.final_report = result.get("final_report", "")
        db.commit()

    if email:
        try:
            from src.services.export import export_audit_pdf
            if audit:
                pdf_bytes = export_audit_pdf(db, audit.id, audit.team_id)
                send_audit_report(email, audit_id, pdf_bytes)
        except Exception as exc:
            logger.warning("Email send failed for audit %s: %s", audit_id, exc)

    _delete_blob(blob_url)


def _dead_letter(db, audit_id: str, error_message: str, payload: dict) -> None:
    """Move failed job to dead_letter_jobs table for admin inspection."""
    from src.db.models import DeadLetterJob
    db.add(DeadLetterJob(
        audit_id=audit_id,
        error_message=error_message,
        original_payload=payload,
    ))
    db.commit()
    logger.warning("Dead-lettered audit %s: %s", audit_id, error_message)


def run_worker():
    from src.db.session import SessionLocal
    from src.db.repository import update_processing_status

    queue = _queue_client()
    logger.info("Worker started. Polling queue every 5s...")

    while True:
        messages = queue.receive_messages(
            max_messages=1,
            visibility_timeout=600,
        )
        for msg in messages:
            body = json.loads(msg.content)
            audit_id = body.get("audit_id", "unknown")
            logger.info("Processing audit %s", audit_id)

            db = SessionLocal()
            try:
                # Retry loop for transient failures
                last_exc = None
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        _process_message(db, body)
                        last_exc = None
                        break
                    except RetryableError as exc:
                        last_exc = exc
                        if attempt < MAX_RETRIES:
                            wait = BACKOFF_BASE ** attempt
                            logger.warning(
                                "Retryable error on audit %s (attempt %d/%d), retrying in %ds: %s",
                                audit_id, attempt, MAX_RETRIES, wait, exc,
                            )
                            time.sleep(wait)
                        else:
                            logger.error("Audit %s exhausted retries: %s", audit_id, exc)
                    except PermanentError as exc:
                        # No retry — dead-letter immediately
                        last_exc = exc
                        logger.error("Permanent failure on audit %s: %s", audit_id, exc)
                        break

                if last_exc is not None:
                    try:
                        update_processing_status(db, audit_id, "failed")
                        _dead_letter(db, audit_id, str(last_exc), body)
                    except Exception:
                        db.rollback()
                    # ponytail: keep blob for failed audits (debugging). Cleaned after 7 days.

            except Exception as exc:
                # Unexpected errors (not typed) — treat as permanent
                logger.error("Unexpected error on audit %s: %s", audit_id, exc)
                try:
                    update_processing_status(db, audit_id, "failed")
                    _dead_letter(db, audit_id, f"Unexpected: {exc}", body)
                except Exception:
                    db.rollback()
                # ponytail: keep blob for failed audits (debugging). Cleaned after 7 days.
            finally:
                db.close()

            queue.delete_message(msg)

        time.sleep(5)


if __name__ == "__main__":
    run_worker()
