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
from src.config import config

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
    """Process an audit job using V2 modules: VideoAnalyzer → ComplianceAuditor → ReportGenerator."""
    import tempfile
    from pathlib import Path
    from src.db.repository import update_processing_status
    from src.services.video_analyzer import VideoAnalyzer, AnalyzerOptions
    from src.services.compliance_auditor import ComplianceAuditor
    from src.services.report_generator import ReportGenerator
    from src.services.email_service import send_audit_report

    audit_id = message_body["audit_id"]
    blob_url = message_body["blob_url"]
    platforms = message_body.get("platforms", ["youtube"])
    email = message_body.get("email")

    # Download blob to temp file for VideoAnalyzer
    update_processing_status(db, audit_id, "transcribing")
    tmp_path = _download_blob_to_temp(blob_url)

    try:
        # Stage 1: VideoAnalyzer (Whisper + OCR + optional Vision)
        analyzer = VideoAnalyzer()
        options = AnalyzerOptions(enable_visual=False)
        analysis = analyzer.analyze(tmp_path, options)
        logger.info(
            "worker_analysis_complete audit_id=%s segments=%d ocr_frames=%d",
            audit_id, len(analysis.transcript_segments), len(analysis.ocr_frames),
        )

        # Stage 2: ComplianceAuditor
        update_processing_status(db, audit_id, "auditing")
        auditor = ComplianceAuditor()
        report = auditor.audit(analysis, platforms)
        logger.info(
            "worker_audit_complete audit_id=%s status=%s violations=%d",
            audit_id, report.overall_status, len(report.violations),
        )

        # Stage 3: ReportGenerator (generate text report for DB storage)
        generator = ReportGenerator()
        report_outputs = generator.generate(report, formats=["json", "pdf"])
        final_report = report_outputs["pdf"].decode("utf-8")

        update_processing_status(db, audit_id, "completed")

        # Persist violations
        from src.db.models import Audit, AuditViolation
        audit = db.query(Audit).filter_by(session_id=audit_id).first()
        if audit:
            for v in report.violations:
                db.add(AuditViolation(
                    audit_id=audit.id,
                    category=v.category,
                    severity=v.severity,
                    description=v.description,
                    citation_source=v.citation,
                    citation_excerpt=v.suggested_rewrite,
                    chunk_id=v.chunk_id,
                ))
            audit.ai_status = report.overall_status
            audit.final_status = report.overall_status
            audit.final_report = final_report
            audit.model_version = config.AZURE_OPENAI_CHAT_DEPLOYMENT
            db.commit()

        if email:
            try:
                pdf_bytes = report_outputs.get("pdf", b"")
                send_audit_report(email, audit_id, pdf_bytes)
            except Exception as exc:
                logger.warning("Email send failed for audit %s: %s", audit_id, exc)

        _delete_blob(blob_url)

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _download_blob_to_temp(blob_url: str) -> str:
    """Download blob to a local temp file. Returns the temp file path."""
    import tempfile
    from azure.storage.blob import BlobClient
    import os

    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
    blob_name = "/".join(blob_url.split("/")[4:])

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    blob = BlobClient.from_connection_string(conn_str, container, blob_name)
    with open(tmp.name, "wb") as f:
        f.write(blob.download_blob().readall())
    return tmp.name


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
