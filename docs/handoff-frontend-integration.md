# Handoff: Frontend-Backend Integration

## What happened this session

1. Implemented all 13 V2 architecture tickets (config, errors, sanitizer, video analyzer, policy retriever, compliance auditor, report generator, worker retry, rate limiter, idempotency, observability, frontend prototype, integration tests)
2. Integrated V2 modules into worker (VideoAnalyzer → ComplianceAuditor → ReportGenerator)
3. Wired Langfuse tracing (fixed blocking issue, confirmed traces appear in dashboard)
4. Fixed Phi-4 endpoint (Azure domain migration: .services.ai.azure.com → .cognitiveservices.azure.com)
5. Switched transcription from Azure Whisper to Groq Whisper (whisper-large-v3-turbo)
6. Ran successful E2E test: Neutrogena ad → PASS, 2.9s total
7. Built frontend prototype (Newsprint design system, Tailwind CSS, 9 sections)
8. Planned frontend-backend integration architecture

## Decisions locked

- **Monorepo** — frontend lives in `frontend/` folder of the same repo
- **Hosting** — Vercel or Cloudflare Pages (not decided which, both work)
- **Framework** — Next.js 14+ with App Router + Tailwind CSS
- **Design system** — Newsprint (see `Newsprint.md` for full spec)
- **API contract** — Auto-generated OpenAPI from FastAPI + Pydantic response models
- **Real-time updates** — SSE (Server-Sent Events) for audit status
- **File upload** — Presigned URL flow (frontend → blob direct, then notify API)
- **Error schema** — `{"error": {"code": str, "message": str, "details": dict|null, "trace_id": str}}`
- **Dashboard stats** — Separate `GET /dashboard/stats` endpoint
- **Auth** — Skipped for now (AUTH_DISABLED=true), add later

## Backend changes needed BEFORE frontend build

These are the tickets for the next session. Order matters — blocking edges noted.

### Ticket 1: Pydantic response models + standardized schemas
- Add response models to all endpoints
- Standardize error response with `trace_id` field
- `/audit/upload` uses `Form` fields because file upload requires `multipart/form-data` — keep multipart for the file, but move options (platforms, email) to query params or a JSON part
- **Blocked by:** nothing

### Ticket 2: `GET /dashboard/stats` endpoint
- Returns: `{total_audits: int, pass_rate: float, violation_count: int, avg_time_seconds: float, audits_this_week: int}`
- Queries the audits table with aggregation
- **Blocked by:** Ticket 1 (needs response model)

### Ticket 3: `GET /audits` list endpoint (paginated)
- Returns: `{data: [AuditSummary], total: int, page: int, per_page: int}`
- AuditSummary: `{id, session_id, video_url, status, violation_count, platforms, created_at}`
- Filter params: `?status=PASS|FAIL&platform=youtube&page=1&per_page=20`
- **Blocked by:** Ticket 1

### Ticket 4: Presigned upload URL flow
- `POST /uploads/presign` → returns `{upload_url: str, blob_name: str, audit_id: str}`
- `POST /audits/{audit_id}/start` → tells backend "file is uploaded, start processing"
- Remove old `/audit/upload` direct-upload flow (or keep as fallback)
- **Blocked by:** Ticket 1

### Ticket 5: SSE endpoint for audit status
- `GET /audits/{id}/stream` — returns `text/event-stream`
- Events: `status` (with processing_status + progress %), `complete` (with full result), `error`
- Worker updates processing_status in DB; SSE endpoint polls DB every 2s and pushes changes
- Close stream on complete/error
- **Blocked by:** Ticket 4

### Ticket 6: Compliance Prompt Generator endpoint
- `POST /prompt/generate` — body: `{brief: str, platform: str, ai_tool: str}`
- Returns: `{prompt: str, policy_sources_used: int, forbidden_words: [str]}`
- Uses Phi-4 to generate the compliance-aware prompt based on indexed policies
- **Blocked by:** Ticket 1

### Ticket 7: Next.js project scaffold + Dashboard page
- `frontend/` directory with Next.js 14, TypeScript, Tailwind
- Design tokens from Newsprint.md configured in tailwind.config.ts
- Dashboard page calling `GET /dashboard/stats` + `GET /audits`
- **Blocked by:** Tickets 2, 3

## Key files

- `frontend/prototype.html` — visual design reference (finalized layout)
- `Newsprint.md` — full design system spec (colors, typography, components, animations)
- `src/api/server.py` — current endpoints
- `src/api/error_handlers.py` — current error schema
- `docs/ENGINEERING_AUDIT.md` — engineering evidence audit
- `evals/e2e_result.json` — last successful E2E run

## Current state

- Backend: All V2 modules working, E2E verified (2.9s)
- Frontend: Static prototype only (no JS framework, no API calls)
- Tests: 48 passing
- Deploy: CI/CD to Azure Container Apps on push to main
- Langfuse: Traces flowing to https://us.cloud.langfuse.com
- Groq Whisper: Working (GROQ_API_KEY in .env)
- Phi-4: Working (cognitiveservices.azure.com endpoint)
- GPT-4o: Working (50K TPM)

## Suggested skills for next session

- `/implement` — pick up tickets 1-7 in order
- `ponytail` — ALWAYS active for coding (minimum code, no over-engineering, deletion over addition)
- `prompt-master` — MANDATORY for ticket 6 (compliance prompt generator — writing the LLM prompt that generates compliance-aware prompts)
- `/tdd` — for tickets 2, 3, 5 (new endpoints — write test first, then implement)
- `/diagnose` — if SSE (ticket 5) doesn't work on first try
- `caveman` — use if context window is getting large (compress responses)

### Per-ticket skill notes

| Ticket | Skills | Why |
|--------|--------|-----|
| 1 (Pydantic models) | `ponytail` | Pure typing work — no abstractions, just add response models |
| 2 (Dashboard stats) | `ponytail`, `/tdd` | Simple DB aggregation — test-first |
| 3 (Audits list) | `ponytail`, `/tdd` | Pagination + filters — test-first |
| 4 (Presigned upload) | `ponytail` | Azure SDK call — one function, no framework |
| 5 (SSE endpoint) | `ponytail`, `/diagnose` | SSE is fiddly — may need debugging |
| 6 (Prompt generator) | `ponytail`, `prompt-master` | The LLM prompt is the core logic — must be crafted carefully |
| 7 (Next.js scaffold) | `ponytail` | Framework setup — follow defaults, don't customize |

### Cost awareness

- Ticket 6 makes a Phi-4 call per request — cheap (~$0.001/call) but should still have a token budget guard
- No ticket adds new GPT-4o calls (expensive model stays in the worker only)
- SSE endpoint (ticket 5) polls Postgres, not an LLM — zero LLM cost
- Presigned URLs (ticket 4) avoid proxying 500MB files through the API — saves compute, not LLM cost

## Env vars (redacted)

All in `.env`:
- AZURE_OPENAI_* (GPT-4o, embeddings)
- PHI4_ENDPOINT + PHI4_API_KEY (cognitiveservices.azure.com)
- GROQ_API_KEY (whisper-large-v3-turbo)
- LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY + LANGFUSE_BASE_URL
- DATABASE_URL (Neon Postgres)
- AZURE_STORAGE_CONNECTION_STRING
- AZURE_SEARCH_* (AI Search)
