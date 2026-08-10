# Spec: Production Hardening

## Context

Frontend deployed on Vercel. Backend API + Worker running on Azure Container Apps. Pipeline is E2E functional. This spec covers the security, reliability, and correctness fixes needed to move from "demo works" to "production-grade."

## What exists

- Backend: FastAPI + Worker on Azure Container Apps
- CORS: configurable via `ALLOWED_ORIGINS` env var (needs Vercel URL added)
- Worker: retry logic (3x exponential backoff) + dead-letter already implemented
- LLM calls: no timeout on GPT-4o or Phi-4-mini `invoke()` calls
- Rate limiting: in-memory dict (resets on deploy)
- Containers: run as root
- Database: Neon PostgreSQL, no `connect_timeout` configured
- Violations: backend `GET /audits/{id}` returns violations via `AuditDetail.violations` list
- Auth: `AUTH_DISABLED=TRUE` in production

## Decisions locked

- No Redis yet (skip for now — current scale doesn't justify $15/month)
- No auth in this pass (AUTH_DISABLED stays true — demo mode is intentional)
- CORS: add Vercel origin to `ALLOWED_ORIGINS` env var on Azure (not a code change — just config)
- Worker retry: already working — no changes needed

## Work to do (code changes only)

### 1. Non-root containers

Both `Dockerfile` and `Dockerfile.worker` run as root. Add a non-root user.

**Changes:**
- Add `RUN adduser --disabled-password --no-create-home nonroot` + `USER nonroot` to both Dockerfiles
- Ensure `/app` directory ownership is correct before `USER` switch

### 2. LLM call timeouts

The `_llm()` and `_mini_llm()` functions in `src/pipeline/nodes.py` create LangChain LLM instances without `request_timeout`. If Azure OpenAI hangs, the worker hangs forever.

**Changes:**
- Add `request_timeout=60` to `AzureChatOpenAI(...)` in `_llm()`
- Add `request_timeout=60` to both `ChatOpenAI(...)` and `AzureChatOpenAI(...)` in `_mini_llm()`
- Add `timeout=60` to the `client.chat.completions.create()` call in `video_analyzer.py` OCR function

### 3. Database connect_timeout

Neon PostgreSQL cold starts cause 30s+ hangs. Add `connect_timeout=10` to the connection string.

**Changes:**
- In `src/db/session.py`, append `?connect_timeout=10` to DATABASE_URL if not already present (or pass via `connect_args` to `create_engine`)

### 4. Verify violations serialization

The worker saves violations to `audit_violations` table and `GET /audits/{id}` maps them to `ViolationOut`. Code inspection shows this is wired correctly. Write a test to confirm.

**Changes:**
- Add one integration test: create an audit with violations in DB, call `GET /audits/{id}`, assert `violations` list is populated

## Non-goals

- Redis (deferred — in-memory rate limit is acceptable at current scale)
- Auth (staying disabled for demo)
- CORS config (env var change on Azure, not a code change)
- Worker retry (already implemented)
- Email delivery (no resource created yet)

## Blocking edges

```
Ticket 1 (Non-root containers) → depends on nothing
Ticket 2 (LLM timeouts) → depends on nothing
Ticket 3 (DB connect_timeout) → depends on nothing
Ticket 4 (Violations fix) → depends on nothing
```

All tickets are independent. Can be done in any order.

## Testing strategy

- Tickets 1-3: verify via `docker build` (non-root), running pipeline with a test video (timeouts don't break happy path), and running `pytest` (DB timeout doesn't break test connections)
- Ticket 4: write a test that creates an audit with violations and verifies `GET /audits/{id}` returns them in the `violations` list
