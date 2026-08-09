/**
 * API client for Brand Guardian backend.
 * ponytail: plain fetch wrapper. No axios, no react-query yet. Add when needed.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: { message: res.statusText } }));
    throw new Error(err.error?.message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Types (mirror backend schemas) ───────────────────────────────────────────

export interface DashboardStats {
  total_audits: number;
  pass_rate: number;
  violation_count: number;
  avg_time_seconds: number;
  audits_this_week: number;
}

export interface AuditSummary {
  id: string;
  session_id: string;
  video_url: string;
  final_status: string;
  violation_count: number;
  platforms: string | null;
  processing_status: string | null;
  created_at: string;
}

export interface PaginatedAudits {
  data: AuditSummary[];
  total: number;
  page: number;
  per_page: number;
}

export interface PresignResponse {
  upload_url: string;
  blob_name: string;
  audit_id: string;
}

export interface AuditStartResponse {
  audit_id: string;
  status: string;
}

export interface ViolationOut {
  category: string;
  severity: string;
  description: string;
  citation_source: string | null;
  citation_excerpt: string | null;
  chunk_id: string | null;
}

export interface AuditDetail {
  id: string;
  session_id: string;
  video_url: string;
  video_id: string;
  ai_status: string;
  final_status: string;
  final_report: string;
  ingestion_source: string | null;
  policy_version_id: string | null;
  processing_status: string | null;
  audit_mode: string | null;
  platforms: string | null;
  file_hash: string | null;
  model_version: string | null;
  created_at: string;
  violations: ViolationOut[];
}

export interface PromptGenerateResponse {
  prompt: string;
  platform: string;
  ai_tool: string;
  policy_sources_used: number;
  tools_recommended: string[];
}

// ── Endpoints ────────────────────────────────────────────────────────────────

export function getDashboardStats(): Promise<DashboardStats> {
  return fetchAPI("/dashboard/stats");
}

export function getAudits(page = 1, perPage = 20, status?: string, platform?: string): Promise<PaginatedAudits> {
  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (status) params.set("status", status);
  if (platform) params.set("platform", platform);
  return fetchAPI(`/audits?${params}`);
}

export function getAuditDetail(id: string): Promise<AuditDetail> {
  return fetchAPI(`/audits/${id}`);
}

export function presignUpload(filename: string, contentType: string): Promise<PresignResponse> {
  return fetchAPI("/uploads/presign", {
    method: "POST",
    body: JSON.stringify({ filename, content_type: contentType }),
  });
}

export function startAudit(auditId: string, platforms: string[]): Promise<AuditStartResponse> {
  return fetchAPI(`/uploads/${auditId}/start`, {
    method: "POST",
    body: JSON.stringify({ platforms }),
  });
}

export function generatePrompt(brief: string, platform: string, aiTool: string, outputFormat: string, model: string): Promise<PromptGenerateResponse> {
  return fetchAPI("/prompt/generate", {
    method: "POST",
    body: JSON.stringify({ brief, platform, ai_tool: aiTool, output_format: outputFormat, model }),
  });
}

export function createAuditFromUrl(videoUrl: string, platforms: string[], email?: string): Promise<{ audit_id: string }> {
  return fetchAPI("/audit", {
    method: "POST",
    body: JSON.stringify({ video_url: videoUrl, platforms, email: email || undefined }),
  });
}

/** Returns the full URL for SSE streaming of audit progress */
export function getAuditStreamUrl(auditId: string): string {
  return `${API_BASE}/audits/${auditId}/stream`;
}

/** Returns the full URL for exporting an audit report */
export function getExportUrl(auditId: string, format: "pdf" | "csv"): string {
  return `${API_BASE}/audits/${auditId}/export?format=${format}`;
}
