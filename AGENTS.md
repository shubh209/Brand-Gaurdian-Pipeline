# Brand Guardian AI — Agent Context

Read this file first. Do not make any changes until you understand the current state and have confirmed the task with the user.

---

## What this project is

A pre-publication video ad compliance scanner. Users submit a YouTube URL or upload a video file. The system extracts transcript and on-screen text, checks it against live-fetched platform policies (YouTube, Meta, TikTok, Facebook, X, FTC), and returns a structured violation report with exact policy citations before the ad is submitted to any platform.

The core product insight: existing tools check ad copy text. No tool checks the actual video content (spoken claims + on-screen text) before submission. That gap is what this solves.

---

## Current state (as of last session)

**Pipeline status: E2E WORKING — Upload path confirmed, eval baseline established**

- Health endpoint: responding at `https://brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io/health`
- Upload path (primary): User uploads MP4 → blob storage → queue → worker transcribes with Whisper → 4-stage audit → result stored in Postgres → polling returns violations. Confirmed working.
- URL path (secondary): Metadata-only on deployed server (YouTube bot-detects Azure IPs). Works locally via youtube-transcript-api. Useful for quick title/description screening but not full transcript.
- GPT-4o quota: raised to 50K TPM. No longer a bottleneck.
- Multi-model: Phi-4-mini-instruct on Azure AI Foundry handles claim extraction + report synthesis. GPT-4o handles policy reasoning only. Reduces token cost significantly.
- Golden eval: 8/10 (80%) baseline established. Two failures: personal attributes (retrieval gap) and before/after (insufficient violation count). Both improve after reindex.
- Worker Container App: `brand-guardian-worker` deployed, running, picks up jobs from Azure Storage Queue.
- Whisper deployment: `whisper` on brand-guardian-openai (eastus2), rate limit 1 req/60s.

**What is working:**
- 4-stage audit pipeline (Phi-4-mini claim extraction → per-claim retrieval + rerank → GPT-4o reasoning → Phi-4-mini synthesis)
- Per-claim retrieval with query expansion (`_expand_claim` rewrites to policy terminology)
- Cross-encoder reranking (ms-marco-MiniLM-L-6-v2)
- Chain-of-thought system prompt on GPT-4o
- Risk level output (HIGH/MEDIUM/LOW) per violation
- Azure Container Apps deployment: API + Worker (GHCR images, CI/CD on push to main)
- Neon PostgreSQL with all migrations applied (003_new_architecture)
- Azure AI Search index `brand-compliance-rules` — 122 chunks, retrieval confirmed working
- Policy sources: 35 leaf-level URLs across YouTube (15), Meta (8), TikTok (5), X (5), FTC (2)
- Async admin reindex endpoint (returns 202, runs in background)
- Firecrawl structured extraction with blob cache fallback
- Video upload → Whisper transcription → async audit via worker
- Golden evaluation dataset (10 synthetic cases, run via `evals/run_eval.py`)
- Phi-4-mini-instruct integrated for cheap extraction tasks
- youtube-transcript-api for caption fetching (works locally, blocked on Azure IPs)

**V2 Architecture foundation (tickets 01-06 complete):**
- `src/config.py` — centralized config with fail-fast validation on missing env vars
- `src/errors.py` — typed error hierarchy: RetryableError, PermanentError, ValidationError
- `src/security/sanitizer.py` — InputSanitizer: MIME check (python-magic), audio track check (ffprobe), prompt injection stripping, unicode control char removal, tiktoken token truncation
- `src/services/video_analyzer.py` — VideoAnalyzer module: `analyze(video_path, options) → AnalysisResult` with Whisper segments, Tesseract OCR, optional GPT-4o Vision
- `src/services/policy_retriever.py` — PolicyRetriever: `retrieve(claim, platforms, k) → list[PolicyChunk]` with query expansion (Phi-4-mini), platform filtering, cross-encoder reranking, and `retrieval_eval()` for measuring recall/precision independently
- `src/services/compliance_auditor.py` — ComplianceAuditor: `audit(analysis, platforms) → AuditReport` with per-timestamp claim extraction, greedy batching by shared chunks, GPT-4o reasoning with logprobs confidence, suggested rewrites, per-platform PASS/FAIL
- `src/services/report_generator.py` — ReportGenerator: `generate(audit_report, formats) → dict[str, bytes]` with JSON, PDF (text), CSV output; timestamps as MM:SS, per-platform sections
- Dockerfile.worker updated with `tesseract-ocr` apt package
- Dependencies added: python-magic, pytesseract

**What is NOT working / not yet built:**
- Violations list not serialized to polling endpoint (report text is there, structured list isn't)
- Worker has no retry logic — job lost if processing fails mid-audit
- Live reindex with structured extraction not yet run (costs ~1,050 Firecrawl credits)
- Test suite hangs on Neon DB cold start (need connection timeout on DATABASE_URL)
- Email delivery (code exists, Azure Communication Services resource not created)
- Frontend auth flow (no MSAL / API key entry UI)
- Enrich node still tries yt-dlp/Video Indexer on upload path (wasted 5s latency on failed calls)
- Containers run as root (no USER directive in Dockerfiles)
- In-memory rate limiter resets on every deploy (Redis planned)
- AUTH_DISABLED=TRUE in production Container App
- V2 modules not yet wired into worker/nodes.py (old pipeline still runs in production)
- Worker retry + dead-letter not yet built (ticket 07)
- Rate limiter Postgres-backed not yet built (ticket 08)
- Idempotency + versioning not yet built (ticket 09)

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
