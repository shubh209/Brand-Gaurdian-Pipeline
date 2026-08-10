# Spec: Brand Guardian V2 — Production-Grade Compliance Pipeline

## Problem Statement

A user uploads a 30-40 second video ad and selects which advertising platforms (YouTube, Meta, TikTok, X) to audit against. The current pipeline only extracts spoken transcript and returns a text-blob report with no timestamps, no visual analysis, no confidence scores, no suggested rewrites, and no per-platform breakdown. Security is nonexistent (no input sanitization, no retry logic, no rate limiting that survives deploys). The system crashes silently on failures with no user-facing feedback.

## Solution

Deepen the pipeline into five production-grade modules that extract all available signals from the video (speech, on-screen text, visual context), reason about each signal against platform-specific policy rules with timestamps and confidence scores, suggest compliant rewrites for violations, and return a structured report with per-platform breakdowns. Implement actual security defenses (prompt sanitization, Postgres-backed rate limiting, dead-letter queue, input validation). Make every failure visible and recoverable.

## User Stories

1. As a marketer, I want to upload my video ad and select multiple platforms to audit against, so that I know whether my ad is compliant before I spend money running it.
2. As a marketer, I want each violation to reference the exact timestamp in my video where it occurs, so that I can find and fix the specific moment.
3. As a marketer, I want a confidence score on each violation, so that I can prioritize which issues to address first.
4. As a marketer, I want a suggested compliant rewrite for each violation, so that I know how to fix it without starting from scratch.
5. As a marketer, I want to see which on-screen text violates policy, so that I can fix visual overlays and not just spoken claims.
6. As a marketer, I want the report broken down by platform (YouTube: PASS, Meta: FAIL), so that I know which platforms I can publish to immediately.
7. As a marketer, I want an overall combined PASS/FAIL status across all selected platforms, so that I get one quick answer.
8. As a marketer, I want to optionally enable visual background analysis, so that imagery like lab coats, pills, or before/after shots gets flagged.
9. As a marketer, I want to download the report as PDF or CSV, so that I can share it with my team or legal department.
10. As a reviewer, I want to see the exact policy rule cited for each violation with the source document excerpt, so that I can verify the flag is legitimate.
11. As a user, I want clear error messages when something fails (unsupported format, audio missing, service unavailable), so that I know what to fix or when to retry.
12. As a user, I want my upload to be deduplicated (same video = same result, no reprocessing), so that I don't waste resources.
13. As an admin, I want rate limiting that persists across deploys, so that the system is protected from abuse.
14. As an admin, I want failed jobs to be retried automatically and dead-lettered after exhausting retries, so that no work is silently lost.
15. As an admin, I want every audit to record which model version, prompt version, and policy version produced it, so that results are reproducible.
16. As a security engineer, I want transcript text sanitized before reaching the LLM, so that prompt injection attacks from malicious video audio cannot manipulate the audit result.

## Implementation Decisions

### Module 1: VideoAnalyzer
- Interface: `analyze(video_path: str, options: AnalysisOptions) → AnalysisResult`
- `AnalysisOptions`: `{enable_visual: bool, frame_interval: float}`
- `AnalysisResult`: `{transcript_segments: [{text, start, end}], ocr_frames: [{text, timestamp}], visual_context: [{description, timestamp}], metadata: dict}`
- Internals: Whisper (with segment timestamps preserved) → Tesseract on key frames (every 5s) → GPT-4o Vision on same frames (optional toggle)
- Replaces: `video_processor.py` + `video_indexer.py` + enrich node inline logic
- Tesseract installed via `apt-get install tesseract-ocr` in Dockerfile.worker
- Frame extraction via ffmpeg (already in worker image)

### Module 2: ComplianceAuditor
- Interface: `audit(analysis: AnalysisResult, platforms: list[str]) → AuditReport`
- `AuditReport`: `{overall_status, per_platform: {platform: status}, violations: list[Violation]}`
- `Violation`: `{claim, timestamp, severity, confidence, citation: {source, excerpt, chunk_id}, suggested_rewrite, platform}`
- Claim extraction: Phi-4-mini, extracts claims WITH timestamps by mapping claim text back to transcript segments
- Batching optimization: group claims sharing same retrieved policy chunks into one GPT-4o reasoning call
- Confidence: from GPT-4o logprobs on the severity token
- Rewrites: one GPT-4o call per violation (batched with reasoning when possible)
- Per-platform: retrieval filters by platform metadata, each platform gets its own PASS/FAIL

### Module 3: PolicyRetriever
- Interface: `retrieve(claim: str, platforms: list[str], k: int) → list[PolicyChunk]`
- Internals: query expansion (Phi-4-mini) → embedding search (Azure AI Search) → platform filter → cross-encoder rerank
- Independently testable: `retrieval_eval()` method that scores recall against labeled examples

### Module 4: Security
- `InputSanitizer.sanitize(text: str) → str` — strips unicode control chars, known injection patterns, truncates at token limit
- `RateLimiter` (Postgres-backed): `check(key: str, limit: int, window_seconds: int) → bool`
- Worker retry: 3 attempts with exponential backoff on transient errors (429, timeout, connection error), dead-letter on permanent errors (bad format, invalid input)
- Input validation: MIME type check with python-magic, audio track existence check via ffprobe, file size limit

### Module 5: ReportGenerator
- Interface: `generate(audit_report: AuditReport, formats: list[str]) → dict[str, bytes]`
- Formats: JSON (API response), PDF (download), CSV (export)
- Per-platform sections + overall combined status in all formats
- Timestamps rendered as `MM:SS` in human-readable formats

### Operational improvements
- Idempotency: SHA-256 hash of uploaded file, check before processing
- Versioning: store prompt hash + policy_version_id + model deployment name on each audit record
- Structured logging: JSON format, audit_id as correlation ID on every log line
- Config: single `config.py` that validates all env vars at startup, fails fast on missing required vars
- Blob lifecycle: delete uploads after successful processing (keep transcript, discard video)
- API errors: proper HTTP status codes (400/413/422/429/503), consistent error schema
- Integration test: one smoke test in CI after deploy

## Testing Decisions

- Test through module interfaces, not internal implementation
- Each module gets its own test file: `test_video_analyzer.py`, `test_compliance_auditor.py`, `test_policy_retriever.py`, `test_security.py`, `test_report_generator.py`
- Golden eval (`evals/run_eval.py`) remains the end-to-end quality gate — re-run after each module is deepened
- Mock external services (GPT-4o, Phi-4, Azure AI Search) in unit tests, but have one integration test that hits real services
- Prior art: existing `tests/test_phase2_retrieval.py` pattern (patches `_mini_llm`, `_llm`)

## Out of Scope

- Horizontal scaling (Kubernetes, multi-worker)
- Multi-region deployment
- React/TypeScript frontend rewrite
- Real-time streaming results (websocket)
- Video forensics beyond key-frame sampling (every-frame analysis)
- Custom model fine-tuning
- Multi-tenant billing system
- Headroom AI integration (deferred — batching achieves 80% of benefit)

## Further Notes

- Budget: ~$5-10 Azure credits for implementation + testing. 1,050 Firecrawl credits for reindex (1,500 available).
- Per-audit cost after V2: ~$0.05 (GPT-4o reasoning + optional vision + Whisper + Phi-4 extraction)
- Every ticket must read AGENTS.md first, use skills per the implementation process rules, and update AGENTS.md at completion.
- Ponytail skill for coding ONLY. prompt-master for LLM prompts. code-review before every commit.
