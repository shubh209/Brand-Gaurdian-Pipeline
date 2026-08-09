"""
Shared Pydantic response models for the Brand Guardian API.
All endpoints use these — no raw dicts returned.
"""
from datetime import datetime
from pydantic import BaseModel


# ── Error envelope ────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None
    trace_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Common ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# ── Upload flow ───────────────────────────────────────────────────────────────

class PresignResponse(BaseModel):
    upload_url: str
    blob_name: str
    audit_id: str


class AuditStartResponse(BaseModel):
    audit_id: str
    status: str


class UploadAcceptedResponse(BaseModel):
    audit_id: str
    status: str
    deduplicated: bool = False


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_audits: int
    pass_rate: float
    violation_count: int
    avg_time_seconds: float
    audits_this_week: int


# ── Audit list (paginated) ────────────────────────────────────────────────────

class AuditSummary(BaseModel):
    id: str
    session_id: str
    video_url: str
    final_status: str
    violation_count: int
    platforms: str | None
    processing_status: str | None
    created_at: datetime


class PaginatedAudits(BaseModel):
    data: list[AuditSummary]
    total: int
    page: int
    per_page: int


# ── Audit detail ──────────────────────────────────────────────────────────────

class ViolationOut(BaseModel):
    category: str
    severity: str
    description: str
    citation_source: str | None = None
    citation_excerpt: str | None = None
    chunk_id: str | None = None


class AuditDetail(BaseModel):
    id: str
    session_id: str
    video_url: str
    video_id: str
    ai_status: str
    final_status: str
    final_report: str
    ingestion_source: str | None = None
    policy_version_id: str | None = None
    processing_status: str | None = None
    audit_mode: str | None = None
    platforms: str | None = None
    file_hash: str | None = None
    model_version: str | None = None
    created_at: datetime
    violations: list[ViolationOut] = []


# ── SSE events ────────────────────────────────────────────────────────────────

class SSEStatusEvent(BaseModel):
    status: str
    progress: int  # 0-100


class SSECompleteEvent(BaseModel):
    audit: AuditDetail


class SSEErrorEvent(BaseModel):
    error: str


# ── Prompt generator ──────────────────────────────────────────────────────────

class PromptGenerateRequest(BaseModel):
    brief: str
    platform: str = "youtube"
    ai_tool: str = "cursor"
    output_format: str = "json"
    model: str = "gpt-4o"


class PromptGenerateResponse(BaseModel):
    prompt: str
    platform: str
    ai_tool: str
    policy_sources_used: int
    tools_recommended: list[str]
