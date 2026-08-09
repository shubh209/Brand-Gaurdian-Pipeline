# Brand Guardian AI — Agent Context

Read this file first. Do not make any changes until you understand the current state and have confirmed the task with the user.

---

## What this project is

A pre-publication video ad compliance scanner. Users submit a YouTube URL or upload a video file. The system extracts transcript and on-screen text, checks it against live-fetched platform policies (YouTube, Meta, TikTok, Facebook, X, FTC), and returns a structured violation report with exact policy citations before the ad is submitted to any platform.

The core product insight: existing tools check ad copy text. No tool checks the actual video content (spoken claims + on-screen text) before submission. That gap is what this solves.

---

## Current state (as of last session)

**Pipeline status: E2E WORKING + FRONTEND CONNECTED**

- Health endpoint: responding at `https://brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io/health`
- Upload path (primary): User uploads MP4 → blob storage → queue → worker (V2 modules: VideoAnalyzer → ComplianceAuditor → ReportGenerator) → result stored in Postgres. Confirmed working (2.9s E2E).
- URL path (secondary): Metadata-only on deployed server. Has a known variable-scoping bug in old LangGraph nodes.py — V2 upload path bypasses it.
- Transcription: **Groq Whisper** (whisper-large-v3-turbo) — fast, free-tier. Azure Whisper is a fallback.
- LLM endpoints: GPT-4o (50K TPM, Azure OpenAI), Phi-4-mini-instruct (Azure AI Foundry at `.cognitiveservices.azure.com`)
- Langfuse: Traces flowing to `https://us.cloud.langfuse.com` (CallbackHandler, non-blocking)
- Frontend: Next.js 14 scaffold in `frontend-app/` — Dashboard page working, calls real API
- CI/CD: GitHub Actions → tests → build → deploy to Azure Container Apps on push to main
- Database: Neon PostgreSQL with migration 004 applied
- Golden eval: 8/10 (80%) baseline. E2E eval on real video: PASS (Neutrogena ad, 2.9s)

**What is working:**
- V2 pipeline: VideoAnalyzer (Groq Whisper + OCR) → ComplianceAuditor (claim extraction + batched reasoning) → ReportGenerator (JSON/PDF/CSV)
- Worker retry (3x exponential backoff, dead-letter on permanent failure)
- Postgres-backed rate limiter with rate limit headers
- SHA-256 file hash dedup (no reprocessing on duplicate upload)
- Observability middleware (correlation ID + latency per request)
- Global error handlers with trace_id in every error response
- Cross-encoder reranking (ms-marco-MiniLM-L-6-v2)
- Prompt injection sanitization at all LLM trust boundaries
- 48 backend tests passing
- CI/CD: test → build → deploy on push to main
- Next.js frontend scaffold (Dashboard page with stats + audit list)

**API endpoints (all typed with Pydantic response models in `src/api/schemas.py`):**
- `GET /health` — liveness
- `GET /dashboard/stats` — aggregated stats
- `GET /audits` — paginated list with status/platform filters
- `GET /audits/{id}` — full detail with violations
- `GET /audits/{id}/stream` — SSE (5s poll, 5min timeout)
- `POST /uploads/presign` — presigned Azure Blob URL (5-min SAS token)
- `POST /uploads/{id}/start` — enqueue processing after direct upload
- `POST /prompt/generate` — compliance-aware agent prompt with MCP tools
- `POST /audit` — URL-mode audit (old LangGraph pipeline)
- `POST /audit/upload` — legacy direct upload (kept as fallback)

**Frontend (`frontend-app/`):**
- Next.js 14 + TypeScript + Tailwind CSS (Newsprint design system)
- Dashboard page: stats row + recent audits table
- API client at `src/lib/api.ts` (typed fetch wrapper)
- Design reference: `frontend/prototype.html` (9 sections, finalized layout)
- Spec for remaining pages: `docs/SPEC-frontend-pages.md`

**What is NOT working / not yet built:**
- Frontend pages: New Audit, Audit Result, History, Prompt Generator (spec ready)
- Frontend deployment to Vercel/Cloudflare (not yet configured)
- Live reindex (costs ~1,050 Firecrawl credits — needs user confirmation)
- Email delivery (code exists, resource not created)
- URL-mode audit variable-scoping bug in nodes.py
- Containers run as root (no USER directive)
- AUTH_DISABLED=TRUE in production

**Next task:** Read `docs/SPEC-frontend-pages.md` and implement pages 1-5 (New Audit, Audit Result, History, Prompt Generator, Deploy).

---

## Before you do anything

1. **Read the task the user gave you.** Identify which category it falls into (see Task Categories below).
2. **Check current state.** Run `git status` and `PYTHONPATH=. uv run pytest tests/ -q` before touching code.
3. **Ask before building.** If the task is ambiguous, ask one focused question. Do not assume.
4. **Use relevant skills.** Check available skills before writing code from scratch.
5. **If you find yourself doing the same thing repeatedly**, stop and suggest creating a skill for it.

---

## Task categories

When the user gives you a task, identify its category first. Each category has a preferred approach.

**Category: Bug fix / pipeline not working**
→ Diagnose root cause before touching code. Use `/diagnose` skill. State the problem, why it exists, how important it is to fix. Get confirmation before fixing.

**Category: New feature / implementation**
→ Check `IMPLEMENTATION_PLAN.md` first. If the feature is already planned, follow the subtask structure. Run `python3 scripts/gate.py <phase>` to verify. Write tests alongside code. No new abstractions unless asked.

**Category: Architecture / design decision**
→ Do not implement immediately. Present options with tradeoffs. Ask the questions listed in `IMPLEMENTATION_PLAN.md` → "Assumptions to clear" pattern. Add decisions to plan before coding.

**Category: Configuration / deployment**
→ Check Azure resources first with `az` CLI before making changes. State what you are about to change and get confirmation. Never update production env vars without user confirmation.

**Category: Research / analysis**
→ Use internet search tools. Cite sources. Distinguish what exists in the codebase from what you're inferring.

**Category: Writing / documentation**
→ Match the style of existing docs. No markdown headers unless explicitly asked. No em dashes. No AI fluff.

---

## Available skills

Skills are in `~/.kiro/skills/`. Use them — they are there for a reason.

**Active by default (check session):**
- `ponytail` — lazy senior dev mode. Minimum code. No unrequested abstractions. Deletion over addition. Always active on this project unless user says "stop ponytail".
- `production-audit` — scan shipped code for production-readiness gaps. Run after completing a phase.

**Engineering:**
- `diagnose` — structured debugging loop for hard bugs. Use before touching broken code.
- `tdd` — red-green-refactor. Use when adding new features with tests.
- `zoom-out` — get broader context when unfamiliar with a section.
- `improve-codebase-architecture` — find deepening opportunities. Use before architecture decisions.
- `grill-with-docs` — stress-test a plan against existing domain model.
- `grill-me` — interview the user to clarify a plan before building.
- `to-issues` — break a plan into independently-grabbable issues.
- `prototype` — build throwaway prototype to flesh out design before committing.
- `triage` — triage issues through a state machine.

**Productivity:**
- `caveman` — ultra-compressed responses. Use when user wants short answers.
- `handoff` — compact session into handoff doc for next agent.
- `grill-me` — relentlessly question the user's plan until clear.

**Misc:**
- `setup-pre-commit` — add Husky/lint-staged hooks.
- `git-guardrails-claude-code` — block dangerous git commands.
- `prompt-master` — generate optimized prompts for any AI tool (LLMs, Cursor, Midjourney, coding agents). Use when asked to write, fix, or improve a prompt for a specific tool.

**When to suggest a new skill:** if you catch yourself writing the same prompt pattern, debugging loop, or boilerplate sequence more than twice in a session, stop and suggest `/write-a-skill` to the user.

---

## Key files and their purpose

| File/Folder | Purpose |
|---|---|
| `IMPLEMENTATION_PLAN.md` | Full phase-by-phase build plan with task checklists, gate checks, and future scope |
| `INTERVIEW_QA.md` | Technical Q&A about every decision in this project — grounded in real code |
| `CONTEXT.md` | Domain glossary, entity relationships, terminology |
| `scripts/gate.py` | Quality gate runner. Run `python3 scripts/gate.py <phase>` after completing a phase |
| `src/pipeline/nodes.py` | Core 4-stage audit pipeline: claim extraction → retrieval → reasoning → synthesis |
| `src/services/policy_store.py` | Vector store singleton, retrieval, score filtering |
| `src/services/policy_fetcher.py` | Firecrawl structured extract with blob cache fallback |
| `src/services/policy_sources.py` | Registry of 35 leaf-level policy URLs (YT=15, Meta=8, TikTok=5, X=5, FTC=2) |
| `src/services/policy_indexing.py` | Chunking, wipe-and-replace reindex logic |
| `src/api/server.py` | FastAPI app, /audit and /audit/upload endpoints |
| `src/api/routes/admin.py` | Async reindex endpoint, API key management |
| `src/worker/` | Async video processing worker (queue polling, Whisper, OCR) |
| `data/` | Fallback policy PDFs (used if all Firecrawl fetches fail) |
| `tests/` | 57 tests. Must pass before any commit. |
| `docs/adr/` | Architecture decision records for major choices |

---

## Decisions already made — do not re-propose these

- **No Redis** for rate limiting yet (in-memory is sufficient at current scale; Redis planned for distributed state)
- **No Kafka / RabbitMQ / Service Bus** (Azure Storage Queue is sufficient)
- **No headroom-ai in production** (local dev tool only, removed from pyproject.toml)
- **No streamlit** (replaced by index.html frontend)
- **No Docker Compose** (single Container App per service)
- **No microservices** (monolith deployed twice: API + Worker)
- **No binary quantization / ONNX** until scale justifies it
- **No Graph RAG** until golden dataset exists to measure improvement
- **Multi-model: GPT-4o (reasoning) + Phi-4-mini (extraction/synthesis)** via Azure AI Foundry OpenAI-compatible endpoint
- **Wipe-and-replace** on reindex (not versioned namespacing — see FS-6 in plan for future upgrade path)
- **Firecrawl /extract not /scrape** (switched in Phase 10 — extract returns structured JSON with `what_is_prohibited` items; costs ~30 credits/URL vs 1 for scrape; upgrade path: batch_scrape + Phi-4-mini extraction if credit cost is prohibitive)
- **GPT-4o at temperature 0.1** with chain-of-thought reasoning
- **Upload path is primary, URL path is secondary** — YouTube bot-detects Azure IPs; upload with Whisper gives full transcript
- **Azure AI Search Free tier** — zero cost, supports 1 index (sufficient for current 122 chunks)
- **No OCR yet** — Tesseract planned (zero-cost, ~50MB in Docker image); Azure AI Vision skipped (paid service)

---

## Azure resources

| Resource | Type | Purpose |
|---|---|---|
| `brand-guardian-openai` (eastus2) | Azure OpenAI | GPT-4o (50K TPM) + text-embedding-3-small + Whisper |
| `shubh-llm-api-project` (eastus) | Azure AI Foundry | Phi-4-mini-instruct (claim extraction + synthesis) |
| `shubh-llm-ai-search` (centralus) | Azure AI Search Free | Vector store, index: `brand-compliance-rules` (122 chunks) |
| `shubhllmproject` | Storage Account | Blob cache (policy-cache/), uploads, queue (audit-jobs) |
| `brand-guardian-api` | Container App | API server, scale-to-zero |
| `brand-guardian-worker` | Container App | Async video processing (Whisper + audit) |
| `managedEnvironment-LLMyt-a71c` | Container Apps env | Shared environment |
| Neon PostgreSQL | Serverless Postgres | Audit history, users, teams, violations |

Container App URLs:
- API: `https://brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io`
- Worker: no ingress (queue-triggered only)

---

## Coding constraints

- `PYTHONPATH=.` required for all local test and script runs
- After every `fs_write` or `str_replace`, verify with `grep` before moving on
- Never use heredocs in `execute_bash` (they hang)
- Run `PYTHONPATH=. uv run pytest tests/ -q` before every commit
- Max retries on any task: 4. If stuck after 4 attempts, stop and explain the problem to the user.

---

## Future scope — pick up from here

Priority order for the next agent/session. Each item is independent unless noted.

**P0 — Bugs blocking demo quality:**
1. Fix violations list not serialized to polling endpoint (report text works, structured `compliance_results` list doesn't show in `GET /audits/{id}`)
2. Add worker retry logic with dead-letter (currently job is lost on any failure)
3. Add `connect_timeout=10` to DATABASE_URL so tests don't hang on Neon cold start
4. Skip enrich node yt-dlp/Video Indexer calls when `audit_mode == "file"` (saves 5s wasted latency)

**P1 — Eval improvements (raise 80% → 90%+):**
5. Run live reindex with structured extraction (costs ~1,050 Firecrawl credits — ask user before running)
6. Add personal attributes policy chunks (Meta transparency center) to index — fixes gold-005
7. Add before/after + "results are typical" FTC chunks — fixes gold-008
8. Re-run `evals/run_eval.py` after reindex to measure improvement

**P2 — Security & hardening:**
9. Add `USER nonroot` to both Dockerfiles
10. Set AUTH_DISABLED=false on Container App + configure Entra or API key auth for demo
11. Add timeout parameter to all GPT-4o / Phi-4 calls (prevent indefinite hangs)
12. Redis for rate limiting (replace in-memory dict that resets on deploy)

**P3 — Features:**
13. OCR via Tesseract on video frames (code exists in video_processor.py, needs tesseract in worker Dockerfile + Azure AI Vision env vars removed)
14. Blob cleanup job (delete uploads older than 7 days)
15. Frontend: show individual violations with severity badges (currently only shows report text)
16. Email delivery after audit completes (Azure Communication Services)

**P4 — Cost & observability:**
17. Token counting before GPT-4o calls (reject if over budget)
18. Langfuse or Application Insights tracing end-to-end
19. Cost model: calculate per-audit cost and surface to user

**P5 — Architecture (only if needed):**
20. Versioned index namespacing (FS-6) when index > 50K chunks
21. Foundry IQ Knowledge Base migration (requires Basic or Serverless tier Azure AI Search)
22. Residential proxy for URL-path full transcript (if URL scanning becomes primary use case again)
