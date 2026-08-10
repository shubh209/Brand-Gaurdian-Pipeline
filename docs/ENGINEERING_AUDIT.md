# Engineering Evidence Audit — Youtube Ads Compliance Pipeline

## Audit Scope

- **Project status:** Deployed demo on Azure Container Apps (API + Worker). CI/CD pipeline pushes to GHCR and deploys on every push to main. Free-tier Azure student credits. Not a production system serving paying users — it is a deployed personal/portfolio project with real infrastructure.
- **Directories and files consulted:**
  - `AGENTS.md`, `KIRO.md`, `README.md`
  - `src/config.py`, `src/errors.py`, `src/tracing.py`
  - `src/security/sanitizer.py`
  - `src/services/compliance_auditor.py`, `src/services/policy_retriever.py`, `src/services/report_generator.py`, `src/services/reranker.py`
  - `src/worker/main.py`
  - `src/middleware/rate_limit.py`, `src/middleware/observability.py`
  - `src/api/server.py`, `src/api/error_handlers.py`
  - `src/db/models.py`
  - `evals/golden_dataset.json`, `evals/run_eval.py`
  - `tests/test_integration.py`
  - `.github/workflows/deploy.yml`
  - `Dockerfile.worker`
  - `alembic/versions/004_v2_architecture.py`
  - Git history (20 commits)
- **Directories intentionally not inspected:** `.kiro/`, `.venv/`, `node_modules/`, `.scratch/` (planning docs only), `data/` (fallback PDFs)
- **Contradictions or missing evidence:**
  - AGENTS.md states "AUTH_DISABLED=TRUE in production Container App" — auth is not enforcing in deployed state, contradicting security claims.
  - Documentation claims 80% eval baseline but `evals/eval_results.json` is not committed to the repository. The eval score cannot be independently verified from source alone.
  - No evidence of real user traffic or production workload. This is a deployed demo, not a production system.

---

## Strong Evidence Candidates

| Candidate | Problem or requirement | Engineering decision | Constraint | Validation | Evidence status | Production context | Why an employer may care | Source |
|---|---|---|---|---|---|---|---|---|
| Typed error classification driving retry policy | Worker processes video audit jobs from a queue. Transient failures (rate limits, timeouts) must be retried; permanent failures (bad input, auth) must not. | Created `RetryableError` / `PermanentError` hierarchy. Worker dispatches: retry with exponential backoff (3 attempts, 2/4/8s) for retryable, dead-letter immediately for permanent, dead-letter after exhausting retries for retryable. | Azure OpenAI has strict rate limits (1 req/60s for Whisper). Jobs cannot be lost silently. No message broker with built-in retry (Azure Storage Queue is simple FIFO). | Code path verified: `src/worker/main.py` lines 166-216, `src/errors.py`. Dead-letter persistence via `DeadLetterJob` model. | VERIFIED | Deployed demo. The engineering pattern (typed errors controlling retry behavior) is directly transferable to any queue-based system. Not tested under real load. | Shows understanding of failure classification — the key decision in any async processing system is which failures to retry and which to give up on. This is a common interview topic. | `src/errors.py`, `src/worker/main.py:166-216`, `src/db/models.py:DeadLetterJob` |
| LLM output evaluation against labeled dataset | Need to measure whether the compliance audit pipeline correctly identifies violations (or correctly passes clean ads). Measuring after retrieval+reasoning changes. | Created a 10-case golden evaluation dataset with expected PASS/FAIL status and minimum violation counts. Evaluation runner scores precision of status and recall of violations. | LLM outputs are non-deterministic. Cannot unit-test correctness — need statistical evaluation. No real ads available for labeling. | `evals/golden_dataset.json` (10 cases with explicit expected_status, expected_violations, min_violations), `evals/run_eval.py` (scoring logic at lines 36-50). Dataset covers edge cases: clean ads (gold-002, 006, 009), health claims, financial scams, disclosure issues, platform-specific rules. | VERIFIED | Evaluation is on synthetic transcripts, not real video ads. Documented baseline of 80% is claimed but results file not committed. The evaluation design (labeled dataset + precision/recall scoring) is the transferable skill. | AI systems need evaluation frameworks separate from unit tests. This shows awareness that LLM correctness is a measurement problem, not a pass/fail test — a real gap in most AI project portfolios. | `evals/golden_dataset.json`, `evals/run_eval.py:36-50` |
| Prompt injection sanitization at trust boundary | User-uploaded video transcripts are processed by LLMs. Transcripts could contain text designed to manipulate the LLM (prompt injection via spoken words or on-screen text). | All text passes through `sanitize_text()` before any LLM call. Strips unicode control chars, known injection patterns (10 regex patterns), and truncates at configurable token limit. Validated at upload with MIME + audio track checks. | User input flows through Whisper transcription → LLM reasoning. A malicious ad could embed "ignore previous instructions" in its spoken content. Input is untrusted. | Code verified: `src/security/sanitizer.py` lines 19-39 (injection patterns), 42-44 (control chars), 63-72 (token truncation), 80-98 (upload validation). Sanitizer is called in `VideoAnalyzer._transcribe()` and `_ocr_frames()`. | VERIFIED | Deployed demo. The sanitization logic itself is a real security control that would function identically in any LLM-backed system. Not penetration tested. | Input sanitization at LLM trust boundaries is a current industry concern. This demonstrates awareness of the problem and a concrete mitigation — beyond just mentioning prompt injection as a risk. | `src/security/sanitizer.py:19-98`, `src/services/video_analyzer.py` (sanitize_text calls in _transcribe and _ocr_frames) |
| Claim batching to reduce LLM call count | Per-claim policy reasoning would require N separate GPT-4o calls (one per claim). At $0.005/1K input tokens on GPT-4o, this is expensive and slow for videos with many claims. | Group claims that retrieved the same policy chunks into batches. Send one GPT-4o reasoning call per batch instead of per claim. | Azure OpenAI rate limits (50K TPM). Each GPT-4o call includes the full policy context. Claims sharing chunks have redundant context. Reducing from N calls to ~2-3 per audit. | Code verified: `src/services/compliance_auditor.py:264-303` (`_group_by_chunks` — greedy grouping by chunk overlap; if ≤8 claims, all in one batch). | VERIFIED | Deployed demo. The optimization logic is real and verifiable. Actual cost reduction unverifiable (no billing data committed). The engineering tradeoff (batch size vs. reasoning accuracy) is clearly annotated. | Shows ability to identify and implement cost optimization in LLM pipelines — a common problem at companies paying for API calls. The decision to batch by shared context (not arbitrary grouping) shows understanding of why it works. | `src/services/compliance_auditor.py:264-303` |
| SHA-256 idempotency on file upload | Same video file uploaded twice should not re-trigger the full pipeline (Whisper + GPT-4o). This wastes money and returns duplicate audit records. | Compute SHA-256 hash of uploaded content. Query DB for existing audit with same hash + team. Return existing result immediately with `deduplicated: true`. | Upload is the primary path. Users may retry on timeout. Blob storage + queue + Whisper + GPT-4o would run again on every upload without dedup. | Code verified: `src/api/server.py:288-292` (hash computation, DB query, early return). DB column with index: `alembic/versions/004_v2_architecture.py` (ix_audits_file_hash). Verified working via curl test in session (same file returned existing audit_id). | VERIFIED | Deployed demo. Idempotency is a standard requirement in any system with expensive downstream processing. The pattern (content hash → DB lookup → early return) is directly transferable. | Idempotency is a common interview topic and real-world requirement. This is a clean implementation of the pattern — hash at ingestion, indexed lookup, short-circuit before expensive work. | `src/api/server.py:286-292`, `alembic/versions/004_v2_architecture.py` |
| Fail-fast configuration validation | Application starts with 10+ required environment variables (API keys, connection strings, endpoints). Missing any one causes cryptic runtime failures deep in the pipeline. | Single `Config` dataclass validated at import time. `_require()` raises `EnvironmentError` immediately with a clear message naming the missing variable. App refuses to start if any required var is absent. | Deployed to Azure Container Apps where env var misconfiguration is the #1 cause of post-deploy failures. Neon DB cold starts make DB-dependent failures look like config issues. | Code verified: `src/config.py:16-20` (_require function), lines 31-67 (all fields with _require or _optional). Frozen dataclass prevents mutation. | VERIFIED | Deployed demo. Fail-fast config validation is a standard operational requirement. The engineering value is preventing silent failures in deployed containers where debugging is expensive. | Shows operational thinking — fail at deploy time with a clear error, not 5 minutes into processing a user request. This is a basic but frequently absent pattern in deployed services. | `src/config.py:16-20, 31-67` |
| CI/CD pipeline with test gate before deploy | Push to main triggers deploy to Azure Container Apps. Without a test gate, broken code deploys automatically. | GitHub Actions workflow: `test` job runs pytest, `build-and-deploy` jobs have `needs: test` — deploy only proceeds if tests pass. Separate container images for API and Worker. | Single-branch workflow (main). No staging environment on free-tier Azure. Tests are the only automated quality gate before production deploy. | `.github/workflows/deploy.yml` — full workflow: test job (lines 12-24), `needs: test` on both deploy jobs (lines 26, 68). | VERIFIED | Deployed demo. The CI/CD pattern is standard but complete: test → build → push to registry → update container app. It actually deploys to running Azure infrastructure. | CI/CD with test gates is table-stakes for professional work, but many portfolio projects skip it. This one actually deploys containers to a cloud platform from CI, not just runs tests. | `.github/workflows/deploy.yml:12-24, 26, 68` |
| Cross-encoder reranking after vector retrieval | Vector search returns semantically similar chunks but ordering by embedding distance alone misses relevance nuances. A claim about "disclosure timing" might match "disclosure" chunks but not the most relevant timing rule. | Two-stage retrieval: Azure AI Search (embedding similarity) → cross-encoder reranking (ms-marco-MiniLM-L-6-v2). Graceful fallback to score-sorted truncation if model unavailable. | Free-tier Azure AI Search has limited semantic ranking capability. Embeddings capture topic but not precise claim-rule relevance. Cross-encoder runs locally (no API cost). | Code verified: `src/services/reranker.py:24` (rerank function), `src/services/policy_retriever.py:95` (rerank called after search). Thread-safe lazy loading of model (`_model_lock`). | VERIFIED | Deployed demo. The two-stage pattern (cheap recall → expensive precision) is standard in information retrieval and directly applicable to any RAG system. Model runs in worker container. | Shows understanding of retrieval quality beyond naive vector search. The pattern (recall with embeddings, precision with cross-encoder) is the standard approach in production RAG systems. | `src/services/reranker.py:1-30`, `src/services/policy_retriever.py:90-95` |

---

## Weak or Rejected Evidence

- **Claim:** "Multi-model cost optimization (GPT-4o for reasoning, Phi-4-mini for extraction)"
  - **Reason rejected:** No billing data or token usage logs committed. The code uses two models, but the actual cost reduction is unverifiable. The decision exists but its impact is a claim without evidence.
  - **What would be needed:** Committed token usage logs or billing comparison showing before/after cost per audit.

- **Claim:** "48 tests passing"
  - **Reason rejected:** A test count without describing what behaviors they verify is weak evidence. Many are mocked and test contract shape rather than correctness.
  - **What would be needed:** Specific tests that verify non-trivial business logic (e.g., "test that a claim with no matching policy chunk returns PASS, not an empty FAIL").

- **Claim:** "Postgres-backed rate limiter persists across deploys"
  - **Reason rejected:** The code is verified, but the "fails open" design means it provides no actual protection during the most likely failure mode (DB cold start on Neon free tier). The rate limiter has a known bypass under the constraint it was built for.
  - **What would be needed:** Evidence it was tested under load or that the fail-open tradeoff was explicitly evaluated against alternatives.

- **Claim:** "Azure Container Apps scale-to-zero deployment"
  - **Reason rejected:** This is a platform feature, not an engineering decision. Choosing Azure Container Apps is a vendor selection, not a transferable skill.
  - **What would be needed:** Evidence of a scaling decision (e.g., tuning min/max replicas under measured load).

- **Claim:** "Langfuse tracing wired into all LLM calls"
  - **Reason rejected:** Code is verified, but tracing with no evidence of being used to diagnose an issue or improve the system is just configuration. Adding a callback is not an engineering decision.
  - **What would be needed:** Evidence that trace data was used to identify and fix a latency or quality issue.

---

## Missing Evidence

1. **Actual eval run results** — `evals/eval_results.json` is not committed. The 80% baseline claim cannot be verified from source. If this file were committed, it would upgrade the eval candidate from "evaluation design" to "measured AI system performance."

2. **Any evidence of real users** — No access logs, user feedback, or usage metrics. This clearly separates it from production experience.

3. **Auth actually enforced** — AGENTS.md explicitly states AUTH_DISABLED=TRUE in the deployed Container App. Any security-related claims must note this context.

---

## Recommended Follow-up

**Commit `evals/eval_results.json`** from an actual evaluation run. This is the single artifact that would upgrade the eval candidate from "designed an evaluation framework" to "measured and tracked AI pipeline accuracy at 80% with specific failure modes identified" — a materially stronger claim for AI/ML engineering roles.
