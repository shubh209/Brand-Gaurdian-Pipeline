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
