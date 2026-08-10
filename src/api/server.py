import logging
import os
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from src.api.routes.admin import router as admin_router
from src.api.routes.audits import router as audits_router
from src.api.routes.dashboard import router as dashboard_router
from src.api.routes.export import router as export_router
from src.api.routes.prompt_generator import router as prompt_router
from src.api.routes.reviews import router as reviews_router
from src.api.routes.uploads import router as uploads_router
from src.api.telemetry import setup_telemetry
from src.auth.dependencies import get_current_user, require_audit_submitter
from src.auth.models import UserContext
from src.db.repository import get_current_policy_version, save_audit
from src.db.session import SessionLocal, get_db
from src.pipeline.workflow import app as compliance_graph
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.observability import ObservabilityMiddleware
from src.api.error_handlers import register_error_handlers
from src.api.schemas import HealthResponse, UploadAcceptedResponse
from src.services.export import DISCLAIMER

setup_telemetry()


def _setup_langfuse():
    """Set up Langfuse tracing if credentials are configured.
    ponytail: v4 reads env vars automatically. Just instantiate — no args needed.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        logging.getLogger("api-server").info("Langfuse tracing disabled (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)")
        return None
    try:
        from langfuse.langchain import CallbackHandler
        handler = CallbackHandler()
        logging.getLogger("api-server").info("Langfuse tracing enabled")
        return handler
    except Exception as exc:
        logging.getLogger("api-server").warning("Langfuse setup failed: %s", exc)
        return None


langfuse_handler = _setup_langfuse()

logging.basicConfig(level=logging.INFO)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logger = logging.getLogger("api-server")


def _parse_allowed_origins() -> list[str]:
    raw = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://localhost:3000,https://brand-guardian-nine.vercel.app",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://localhost:8000"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes"):
        db = SessionLocal()
        try:
            from src.auth.dependencies import ensure_default_team

            ensure_default_team(db)
        except Exception as exc:
            logger.warning("Startup bootstrap skipped (database unavailable): %s", exc)
        finally:
            db.close()
    yield


app = FastAPI(
    title="Brand Guardian AI API",
    description="Audits YouTube ad content against YouTube Ad Policies and FTC guidelines.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(ObservabilityMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audits_router)
app.include_router(reviews_router)
app.include_router(admin_router)
app.include_router(export_router)
app.include_router(dashboard_router)
app.include_router(uploads_router)
app.include_router(prompt_router)

register_error_handlers(app)


class AuditRequest(BaseModel):
    video_url: str
    platforms: list[str] = ["youtube"]

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, v: list[str]) -> list[str]:
        allowed = {"youtube", "tiktok", "facebook"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid platforms: {invalid}")
        if not v:
            raise ValueError("At least one platform required")
        return v


class ComplianceIssue(BaseModel):
    category: str
    severity: str
    description: str
    citation_source: str | None = None
    citation_excerpt: str | None = None
    chunk_id: str | None = None
    confidence: str | None = None
    risk_level: str | None = None


class AuditResponse(BaseModel):
    audit_id: str | None = None
    session_id: str
    video_id: str
    status: str
    final_status: str
    ai_status: str
    final_report: str
    ingestion_source: str | None = None
    compliance_results: List[ComplianceIssue]
    violations_by_platform: dict[str, list[ComplianceIssue]] = {}
    disclaimer: str = DISCLAIMER


class AuthMeResponse(BaseModel):
    user_id: str
    team_id: str
    email: str | None
    role: str


def _group_by_platform(results: list) -> dict[str, list]:
    """Group compliance results by their 'platform' field."""
    grouped: dict[str, list] = {}
    for item in results:
        platform = item.get("platform", "unknown") if isinstance(item, dict) else getattr(item, "platform", "unknown") or "unknown"
        grouped.setdefault(platform, []).append(item)
    return grouped


@app.post("/audit", response_model=AuditResponse)
async def audit_video(
    request: AuditRequest,
    user: UserContext = Depends(require_audit_submitter),
    db: Session = Depends(get_db),
):
    session_id = str(uuid.uuid4())
    video_id_short = f"vid_{session_id[:8]}"

    logger.info(
        "Audit request url=%s session=%s user=%s team=%s",
        request.video_url,
        session_id,
        user.user_id,
        user.team_id,
    )

    _PLATFORM_DOMAINS = {
        "youtube": ("youtube.com", "youtu.be"),
        "tiktok": ("tiktok.com",),
        "facebook": ("facebook.com", "fb.watch"),
    }

    def _url_matches_platform(url: str, platform: str) -> bool:
        return any(d in url for d in _PLATFORM_DOMAINS.get(platform, ()))

    url = request.video_url
    if not any(_url_matches_platform(url, p) for p in request.platforms):
        raise HTTPException(
            status_code=400,
            detail=f"URL does not match any of the selected platforms: {request.platforms}",
        )

    initial_inputs = {
        "video_url": request.video_url,
        "video_id": video_id_short,
        "platforms": request.platforms,
        "compliance_results": [],
        "errors": [],
    }

    try:
        config = {"callbacks": [langfuse_handler]} if langfuse_handler else {}
        final_state = await compliance_graph.ainvoke(initial_inputs, config=config)
        ai_status = final_state.get("final_status", "UNKNOWN")
        compliance_results = final_state.get("compliance_results", [])
        ingestion_source = final_state.get("ingestion_source")

        policy_version = get_current_policy_version(db)
        policy_version_id = policy_version.id if policy_version else None

        audit_id = None
        try:
            audit = save_audit(
                db,
                team_id=user.team_id,
                user_id=user.user_id,
                session_id=session_id,
                video_url=request.video_url,
                video_id=final_state.get("video_id", video_id_short),
                ai_status=ai_status,
                final_report=final_state.get("final_report", "No report generated."),
                compliance_results=compliance_results,
                policy_version_id=policy_version_id,
                ingestion_source=ingestion_source,
                raw_response={
                    "compliance_results": compliance_results,
                    "final_status": ai_status,
                    "final_report": final_state.get("final_report"),
                    "ingestion_source": ingestion_source,
                },
            )
            audit_id = str(audit.id)
        except Exception as db_exc:
            logger.warning("Audit persistence skipped (database unavailable): %s", db_exc)

        return AuditResponse(
            audit_id=audit_id,
            session_id=session_id,
            video_id=audit.video_id,
            status=audit.final_status,
            final_status=audit.final_status,
            ai_status=audit.ai_status,
            final_report=audit.final_report,
            ingestion_source=audit.ingestion_source,
            compliance_results=compliance_results,
            violations_by_platform=_group_by_platform(compliance_results),
        )

    except Exception as exc:
        logger.error("Audit failed session=%s error=%s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {exc}") from exc


_ALLOWED_UPLOAD_PLATFORMS = {"youtube", "tiktok", "facebook"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
_MAX_DURATION_SECONDS = 60


@app.post("/audit/upload", status_code=202)
async def upload_video_for_audit(
    file: UploadFile = File(...),
    platforms: list[str] = Form(default=["youtube"]),
    email: str | None = Form(default=None),
    user: UserContext = Depends(require_audit_submitter),
    db: Session = Depends(get_db),
):
    invalid = set(platforms) - _ALLOWED_UPLOAD_PLATFORMS
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid platforms: {invalid}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 500 MB limit")

    # Idempotency: SHA-256 dedup — return existing audit if same file was already processed
    import hashlib
    file_hash = hashlib.sha256(content).hexdigest()
    from src.db.models import Audit as AuditModel
    existing = db.query(AuditModel).filter(AuditModel.file_hash == file_hash, AuditModel.team_id == user.team_id).first()
    if existing:
        return {"audit_id": existing.session_id, "status": existing.processing_status or "completed", "deduplicated": True}

    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    audit_id = str(uuid.uuid4())

    # Validate duration via ffprobe
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(content)
        tmp.close()
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", tmp.name],
            capture_output=True, text=True,
        )
        try:
            duration = float(result.stdout.strip())
        except ValueError:
            duration = 0.0
        if duration > _MAX_DURATION_SECONDS:
            raise HTTPException(status_code=422, detail=f"Video exceeds {_MAX_DURATION_SECONDS}s limit")
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    # Upload to Azure Blob
    blob_url = ""
    try:
        from azure.storage.blob import BlobClient
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        container = os.getenv("AZURE_STORAGE_CONTAINER", "uploads")
        blob_name = f"uploads/{audit_id}{ext}"
        if conn_str:
            blob = BlobClient.from_connection_string(conn_str, container, blob_name)
            blob.upload_blob(content, overwrite=True)
            blob_url = blob.url
    except Exception as exc:
        logger.warning("Blob upload failed for audit %s: %s", audit_id, exc)

    # Enqueue job
    try:
        from azure.storage.queue import QueueClient
        import json as _json
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        queue_name = os.getenv("AZURE_STORAGE_QUEUE_NAME", "audit-jobs")
        if conn_str:
            q = QueueClient.from_connection_string(conn_str, queue_name)
            q.send_message(_json.dumps({
                "audit_id": audit_id,
                "blob_url": blob_url,
                "platforms": platforms,
                "email": email,
            }))
    except Exception as exc:
        logger.warning("Queue enqueue failed for audit %s: %s", audit_id, exc)

    # Persist audit row
    try:
        from src.db.models import Audit
        audit = Audit(
            team_id=user.team_id,
            user_id=user.user_id,
            session_id=audit_id,
            video_url=blob_url or f"upload:{audit_id}",
            video_id=f"vid_{audit_id[:8]}",
            ai_status="PENDING",
            final_status="PENDING",
            final_report="",
            processing_status="pending",
            audit_mode="file",
            platforms=",".join(platforms),
            file_hash=file_hash,
        )
        db.add(audit)
        db.commit()
    except Exception as exc:
        logger.warning("Audit row persist failed for %s: %s", audit_id, exc)

    return {"audit_id": audit_id, "status": "pending"}


@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "healthy", "service": "Brand Guardian AI", "version": "3.0.0"}


@app.get("/auth/me", response_model=AuthMeResponse)
def auth_me(user: UserContext = Depends(get_current_user)):
    return AuthMeResponse(
        user_id=str(user.user_id),
        team_id=str(user.team_id),
        email=user.email,
        role=user.role.value,
    )


@app.get("/")
def serve_frontend():
    return FileResponse("frontend/index.html")


@app.get("/admin")
def serve_admin():
    return FileResponse("frontend/admin.html")
