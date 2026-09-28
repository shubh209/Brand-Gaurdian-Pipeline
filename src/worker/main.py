"""
Worker: polls the Postgres job queue, processes uploaded videos through the pipeline.
Storage + queue go through the provider seams (Supabase). Run as: python -m src.worker.main
"""
import json
import logging
import time

from dotenv import load_dotenv

load_dotenv(override=True)

from src.config import config
from src.errors import RetryableError, PermanentError
from src.services import queue as job_queue
from src.services import storage

logger = logging.getLogger("brand-guardian.worker")
logging.basicConfig(level=logging.INFO)

# Retry config
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds: 2, 4, 8


def _blob_key(body: dict) -> str:
    """The storage key for a job's video. New producers send blob_key; fall back to
    deriving it from the audit_id for any older messages."""
    return body.get("blob_key") or storage.key_for_audit(body["audit_id"])


def _process_message(db, message_body: dict) -> None:
    """Process an audit job using V2 modules: VideoAnalyzer → ComplianceAuditor → ReportGenerator."""
    import tempfile
    from pathlib import Path
    from src.db.repository import update_processing_status
    from src.services.video_analyzer import VideoAnalyzer, AnalyzerOptions
    from src.services.compliance_auditor import ComplianceAuditor
    from src.services.report_generator import ReportGenerator
    from src.services.email_service import send_audit_report
    from src.tracing import update_trace

    audit_id = message_body["audit_id"]
    blob_key = _blob_key(message_body)
    platforms = message_body.get("platforms", ["youtube"])
    email = message_body.get("email")

    # Attach audit context to Langfuse trace
    update_trace(
        session_id=audit_id,
        metadata={"platforms": platforms, "blob_key": blob_key, "audit_mode": "file"},
        tags=["worker", "upload"] + platforms,
    )

    # Download video to a temp file for VideoAnalyzer
    update_processing_status(db, audit_id, "transcribing")
    tmp_path = storage.download_to_temp(blob_key, suffix=".mp4")

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
            audit.model_version = config.LLM_CHAT_MODEL
            db.commit()

        if email:
            try:
                pdf_bytes = report_outputs.get("pdf", b"")
                send_audit_report(email, audit_id, pdf_bytes)
            except Exception as exc:
                logger.warning("Email send failed for audit %s: %s", audit_id, exc)

        # ponytail: keep the blob on success cleanup; delete after processing completes.
        storage.delete(blob_key)

    finally:
        Path(tmp_path).unlink(missing_ok=True)


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

    logger.info("Worker started. Polling the Postgres queue every 5s...")

    while True:
        msg = job_queue.receive(visibility_timeout=600)
        if msg is not None:
            body = msg.body
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

            # Remove the job from the queue. Retryable failures already exhausted their
            # attempts inside the loop above; dead-lettering has recorded permanent ones,
            # so the message is done either way.
            job_queue.delete(msg.id)

        time.sleep(5)


if __name__ == "__main__":
    run_worker()
