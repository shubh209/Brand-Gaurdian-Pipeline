# Spec: Testing Phase

## Decisions

- All tests are mocked (no real Azure/Groq calls) — fast, deterministic, CI-ready
- Flat file organization in `tests/`
- TDD approach: write one test, make it pass, repeat
- Log results and learn from failures (fix bugs found)

## Test Files to Create

### 1. `tests/test_failure_paths.py`

Tests that exercise error handling when things go wrong.

**Behaviors to test:**
- VideoAnalyzer with empty/corrupt video file → should not crash, should return empty AnalysisResult or raise a clear error
- ComplianceAuditor with empty transcript (0 segments) → should return PASS with 0 violations (nothing to check)
- ComplianceAuditor when LLM returns malformed JSON → should handle gracefully, not crash
- Worker processing when Azure OpenAI times out → should raise RetryableError (triggers retry)
- Duplicate upload (same file hash) → should return existing audit_id without reprocessing
- API request with missing required fields → should return 422 with structured error
- GET /audits/{non-existent-uuid} → should return 404

### 2. `tests/test_api_contracts.py`

Tests that verify API response schemas match what the frontend expects.

**Behaviors to test:**
- GET /audits/{id} response has all fields from frontend AuditDetail interface
- POST /uploads/presign response has {upload_url, blob_name, audit_id}
- POST /prompt/generate response has {prompt, platform, ai_tool, policy_sources_used, tools_recommended}
- GET /audits?page=1 response has {data: [...], total, page, per_page}

### 3. `tests/test_eval_synthetic.py`

Synthetic transcript fixtures through ComplianceAuditor to test quality.

**Fixtures (3-5 synthetic transcripts):**
- Clear violation: "I lost 30 pounds in 2 weeks with no exercise" → should flag CRITICAL
- Borderline: "Many customers report feeling more energetic" → should flag WARNING or pass (hedged language)
- Clean ad: "Try our new moisturizer, dermatologist tested" → should PASS
- Multiple platforms: Same claim tested against YouTube + FTC → should cite platform-specific rules

**Note:** These require real LLM calls (Groq/Azure). They run as a separate eval, not in fast CI. Output saved to `evals/synthetic_results.json`.

### 4. `tests/test_rate_limiter.py`

**Behaviors to test:**
- POST to /audit N times → request N+1 returns 429
- Response includes X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After headers
- GET requests are not rate limited
- Different endpoints have different limits

## Blocking edges

```
test_failure_paths → depends on nothing
test_api_contracts → depends on nothing
test_eval_synthetic → depends on nothing (but requires LLM env vars to run)
test_rate_limiter → depends on nothing
```

All independent. Implement in order listed (failure paths first — highest bug-finding probability).
