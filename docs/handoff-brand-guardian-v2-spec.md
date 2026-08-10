# Handoff: Brand Guardian AI — Architecture V2 Spec & Tickets

## What happened this session

1. Fixed the zero-retrieval bug (wrong index name in .env)
2. Fixed GPT-4o 429 (user raised quota to 50K TPM)
3. Implemented Phase 10 subtasks 10.1–10.4 (policy sources, structured extraction, fetcher switch, indexing)
4. Created worker Container App on Azure
5. Fixed 5 deployment bugs (ffmpeg, azure-storage-queue, blob public access, session_id lookup, indexer overwriting transcript)
6. Confirmed e2e upload path works (video → Whisper → audit → result)
7. Integrated Phi-4-mini-instruct for claim extraction (cost reduction)
8. Built golden evaluation dataset (10 cases, 80% baseline)
9. Fixed gpt-4o-mini reference (404 → fall back to gpt-4o)
10. Created skill-router hook for enforcing skill activation
11. Updated PROJECT.md with locked resume bullets
12. Updated AGENTS.md + KIRO.md with current state + future scope
13. Performed full architecture audit (5 deepening candidates + 10 operational gaps)

## Decisions locked (do not re-litigate)

- **Upload path is primary** — URL path is secondary/metadata-only on server
- **Multi-model:** GPT-4o (reasoning) + Phi-4-mini (extraction/synthesis)
- **Visual analysis:** GPT-4o Vision on sampled frames, TOGGLE mode (user opts in)
- **OCR:** Tesseract (free, open-source), not Azure AI Vision
- **Rate limiting:** Postgres-based, not Redis (no caching needs in this project)
- **Suggested rewrites:** Yes, extra GPT-4o call per violation
- **Report format:** Per-platform breakdown + combined overall status + both options shown
- **Confidence scores:** Logprobs from GPT-4o (free, no extra call)
- **Timestamps:** Whisper segment-level timestamps preserved through pipeline, violations reference specific seconds
- **Platform selection:** Filters which policy chunks are retrieved, nothing else changes
- **Security:** Actually implement defenses (prompt sanitization, rate limiting, retry, dead-letter)
- **Budget:** ~$5-10 Azure credits + 1,050 Firecrawl credits for reindex (1,500 available)
- **No Redis, no new paid services**
- **Batch claims with shared policy chunks into fewer GPT-4o calls** — group claims that retrieved the same policy chunks into one reasoning call to reduce total LLM calls from N to ~2-3 per audit
- **Stay on Azure (student credits)**
- **Postgres for state: Neon free tier**

## Architecture V2 — Five deepening candidates

### 1. VideoAnalyzer module
- Interface: `analyze(video_path, options) → AnalysisResult`
- AnalysisResult: `{transcript_segments: [{text, start, end}], ocr_frames: [{text, timestamp}], visual_context: [{description, timestamp}], metadata: dict}`
- Internals: Whisper + Tesseract + frame sampling + GPT-4o Vision (optional)
- Replaces: scattered video_processor.py + video_indexer.py + inline enrich logic

### 2. ComplianceAuditor module
- Interface: `audit(analysis: AnalysisResult, platforms: list[str]) → AuditReport`
- AuditReport: `{overall_status, per_platform: {platform: status}, violations: [{claim, timestamp, severity, confidence, citation, suggested_rewrite, platform}]}`
- Internals: claim extraction WITH timestamps → per-claim retrieval + rerank → GPT-4o reasoning with logprobs → rewrite generation → synthesis
- Replaces: audit_content_node monolith in nodes.py

### 3. PolicyRetriever module
- Interface: `retrieve(claim: str, platforms: list[str], k: int) → list[PolicyChunk]`
- Internals: query expansion + embedding search + platform filter + cross-encoder rerank
- Adds: `retrieval_eval()` for measuring retrieval accuracy independently

### 4. Security modules
- InputSanitizer: `sanitize(text: str) → str` — strips prompt injection patterns
- RateLimiter (Postgres-backed): `check(key, limit, window) → bool`
- Worker retry: 3 attempts on transient errors, dead-letter on permanent

### 5. ReportGenerator module
- Interface: `generate(audit_result: AuditReport, formats: list[str]) → Report`
- Formats: JSON (API), PDF (download), CSV (export)
- Per-platform sections + overall combined status

## 10 Operational gaps to close

1. Typed error handling (RetryableError/PermanentError)
2. Observability (correlation ID, structured logging, latency tracking)
3. Idempotency (SHA-256 hash dedup)
4. Graceful degradation (fallback chains, explicit "insufficient data" responses)
5. Input validation (MIME type, audio track check, token limit, prompt injection)
6. Versioning (store prompt hash + policy_version_id + model version per audit)
7. Data lifecycle (blob TTL, upload cleanup after processing)
8. API contract (proper HTTP status codes, error schema, rate limit headers)
9. Integration tests (smoke test in CI, golden eval as scheduled job)
10. Config management (single config.py, fail-fast on startup)

## Key files to read first

- `AGENTS.md` — current state + future scope (prioritized P0-P5)
- `KIRO.md` — coding rules + known issues
- `PROJECT.md` — locked resume bullets + verified metrics
- `src/pipeline/nodes.py` — current audit logic (to be deepened)
- `src/worker/main.py` — worker orchestration (to be deepened)
- `src/worker/video_processor.py` — Whisper + OCR (to be replaced by VideoAnalyzer)
- `src/services/policy_store.py` — retrieval (to be wrapped in PolicyRetriever)
- `evals/golden_dataset.json` — 10 test cases
- `evals/run_eval.py` — evaluation runner

## Suggested skills for next session

- `/to-tickets` — break this spec into tracer-bullet tickets with blocking edges
- `/implement` — pick up tickets one at a time
- `/tdd` — each module deepening should be test-first
- `/codebase-design` — vocabulary for interface decisions during implementation
- `ponytail` — ONLY during coding (minimum code, deletion over addition)
- `prompt-master` — MANDATORY when writing or modifying any LLM prompt/system prompt
- `code-review` — run on every diff before committing (Standards + Spec axes)
- `diagnose` — for workflow testing, dependency testing, and finding bugs before release
- `ask-matt` — always called first (enforced by hook)

## Implementation process rules (MANDATORY)

Every ticket must follow this sequence:
1. Call `ask-matt` to route to correct skill
2. Read `AGENTS.md` to understand project rules and current state before touching any code
3. Activate `ponytail` before writing code
4. Activate `prompt-master` before writing or modifying any LLM prompt
5. Write tests first (`/tdd`) for non-trivial logic
6. After implementation: run `code-review` on the diff
7. After code-review passes: run tests, then commit
8. Test the workflow end-to-end after each ticket (not just unit tests)
9. Check for vulnerabilities: prompt injection in new prompts, input validation at trust boundaries
10. Update AGENTS.md with: what changed, what's now working, what's still broken — so the next ticket has accurate current state
11. Never commit with known failures — fix or ask before proceeding

## Env vars (redacted)

- Azure OpenAI: brand-guardian-openai (eastus2) — GPT-4o, embeddings, Whisper
- Azure AI Foundry: shubh-llm-api-project — Phi-4-mini-instruct (base_url ends in /openai/v1)
- Azure AI Search: shubh-llm-ai-search (free tier) — index: brand-compliance-rules
- Neon Postgres: free tier, serverless
- Container Apps: brand-guardian-api + brand-guardian-worker
- Firecrawl: 1,500 credits available (~1,050 needed for reindex)
