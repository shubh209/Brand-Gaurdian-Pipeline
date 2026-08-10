# Brand Guardian AI — Interview Q&A

> Grounded in real source code. Every answer cites the actual file that proves it.

---

## SECTION 1 — PROJECT OVERVIEW

### Q: Walk me through what this project does.

**Short answer:** It's an internal compliance tool that takes a YouTube ad URL and tells you whether it violates YouTube's ad policies or FTC influencer guidelines — with exact citations to the rule that was broken.

- A reviewer submits a URL to `POST /audit`.
- A three-node LangGraph pipeline runs: `indexer` fetches metadata from YouTube Data API v3, `enrich` tries to pull captions via three progressively heavier methods, `auditor` does RAG against indexed compliance PDFs then calls GPT-4o to flag violations.
- The result (PASS/FAIL + severity-graded violations) is saved to Postgres and returned immediately.
- A human reviewer can optionally override the AI's decision, which sets the `final_status` separately from the `ai_status`.

Evidence: `backend/src/graph/workflow.py`, `backend/src/api/server.py`

---

## SECTION 2 — LANGGRAPH / AGENTIC PIPELINE

### Q: What is LangGraph and why did you use it?

**In one line:** LangGraph is a graph execution framework built on LangChain that lets you define multi-step LLM workflows as a directed state machine.

- How it works: You define nodes (Python functions), add directed edges between them, and a shared `TypedDict` state flows through each node. Each node reads from state, does work, and returns a dict that merges back in.
- In this codebase: `workflow.py` defines three nodes — `indexer → enrich → auditor` — each in its own file (`nodes.py`). The compiled graph is called with `compliance_graph.ainvoke(initial_inputs)` inside the `/audit` endpoint.
- When I'd reach for it: any multi-step LLM workflow where you need clear node separation, shared state, and async execution. When not: a single LLM call doesn't need a state machine.

Evidence: `backend/src/graph/workflow.py`, `backend/src/api/server.py`

---

### Q: Is this actually agentic? What makes it a pipeline vs an agent?

Honest answer: this is a **linear pipeline**, not a true agent. The graph has three nodes with hardcoded edges: indexer → enrich → auditor → END. There are no conditional branches, no routing decisions, no tool calls the LLM makes itself, and no retry loops. It's agentic in the sense that it uses an LLM to reason over retrieved context, but the flow is deterministic and sequential.

If you said "agentic workflow" on your resume, clarify it as: "a multi-step LLM pipeline orchestrated with LangGraph."

Evidence: `backend/src/graph/workflow.py` — only `add_edge` calls, no `add_conditional_edges`

---

### Q: Walk me through each node.

**`index_video_node`:** Calls `YouTubeTranscriptService.extract_data(video_url)` which uses YouTube Data API v3 to pull title, description, tags, and any captions available through the API. Sets `ingestion_source = "metadata"`. If it fails, it returns early with `final_status = "FAIL"` so downstream nodes can skip gracefully.

**`enrich_content_node`:** Tries three progressively heavier caption sources: (1) YouTube's `timedtext` endpoint (direct, no auth, supports `en`/`en-US`/`en-GB`), (2) `yt-dlp` subtitle extraction, (3) Azure Video Indexer for full speech transcription + OCR on-screen text. Updates `transcript` and `ocr_text` in state. If all three fail it falls back to the metadata already in state.

**`audit_content_node`:** Concatenates transcript + OCR text, calls `search_policy_chunks()` (RAG, top-k = 8 by default), formats them with CHUNK_ID + SOURCE labels, constructs a system prompt embedding those rules, sends to GPT-4o at `temperature=0.0`, parses the JSON response, and calls `_attach_citations()` to enrich each violation with the source PDF name and excerpt.

Evidence: `backend/src/graph/nodes.py`

---

### Q: What is the VideoAuditState and why use TypedDict?

**In one line:** It's the shared data contract that all three nodes read from and write to as the graph executes.

- `VideoAuditState` is a `TypedDict` with fields like `video_url`, `transcript`, `ocr_text`, `compliance_results`, `final_status`, `errors`. Two fields — `compliance_results` and `errors` — use `Annotated[List, operator.add]` which tells LangGraph to *append* rather than replace when multiple nodes write to them.
- TypedDict over a dataclass: zero overhead, type-safe, and LangGraph's `StateGraph` constructor takes it directly.

Evidence: `backend/src/graph/state.py`

---

## SECTION 3 — RAG (RETRIEVAL AUGMENTED GENERATION)

### Q: What is RAG and where did you use it?

**In one line:** RAG means you retrieve relevant chunks from a knowledge base at query time and inject them into the LLM prompt, so the model reasons against real documents instead of its training data.

- How it works: At index time, PDFs are split into chunks (1000 chars, 200 overlap), each chunk gets a UUID, embedded with `text-embedding-3-small`, and uploaded to Azure AI Search. At query time, `search_policy_chunks(query_text, k=8)` embeds the query and does cosine similarity search to return the 8 most relevant chunks. Those chunks — with CHUNK_ID and SOURCE labels — are injected directly into the GPT-4o system prompt.
- In this codebase: the query text is `transcript + OCR text` concatenated. The model is explicitly told to set `chunk_id` in each violation to the CHUNK_ID it relied on. After the response, `_attach_citations()` resolves each `chunk_id` back to the full source and excerpt.
- When not RAG: if the model just gets a static policy text pasted in the prompt every time, that's prompt injection, not RAG.

Evidence: `backend/src/services/policy_store.py`, `backend/src/services/policy_indexing.py`, `backend/src/graph/nodes.py`

---

### Q: Why Azure AI Search for the vector store, not Pinecone or ChromaDB?

**Verdict:** Azure AI Search because the whole stack is Azure and it avoids an extra service + API key to manage.

- Why it fits here: the project already uses Azure OpenAI, Azure Container Apps, and Azure Monitor. Using Azure AI Search keeps IAM, networking, and billing in one place.
- What Pinecone is genuinely better at: dedicated vector search with more index tuning options (HNSW params, namespaces, metadata filtering). If you needed sub-10ms retrieval at massive scale, Pinecone wins.
- ChromaDB is better for: local development / prototyping with zero infra. No cloud dependency.
- Trade-off I accepted: Azure AI Search's free tier has limited index capacity. The `similarity_search` call is a round-trip HTTP request per audit, no connection pooling.

Evidence: `backend/src/services/policy_store.py` — `AzureSearch(...)` from `langchain_community.vectorstores`

---

### Q: What is RAG_TOP_K and what value did you use?

`RAG_TOP_K` is the number of policy chunks retrieved per audit. It defaults to `8` (set via `int(os.getenv("RAG_TOP_K", "8"))`). You can override it per environment. 8 is a reasonable balance — enough context for the model to catch multi-rule violations without blowing the context window.

Evidence: `backend/src/services/policy_store.py` — `rag_top_k()` function

---

### Q: How are citations attached to violations?

The model is instructed in the system prompt to set `chunk_id` in each violation JSON to the `CHUNK_ID` it cited. After parsing the response, `_attach_citations()` builds a lookup dict (`chunk_map`) from the retrieved chunks, then for each violation, resolves `chunk_id → source filename + first 500 chars of content`. The `setdefault` calls mean the model's own excerpt wins if it provided one. If a `chunk_id` is missing or not in the map, the row is returned as-is without crashing.

Evidence: `backend/src/graph/nodes.py` — `_attach_citations()` function; `tests/test_citations.py` validates both the happy path and the missing-chunk-id graceful fallback

---

### Q: What embedding model did you use and why?

`text-embedding-3-small` from Azure OpenAI. It's the default in `policy_store.py` (`azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")`). It's OpenAI's cost-efficient embedding model, accurate enough for compliance text retrieval, and runs in the same Azure resource as GPT-4o — no extra service to manage.

Evidence: `backend/src/services/policy_store.py`

---

### Q: What chunk size and overlap did you use for indexing?

Chunk size: **1000 characters**, overlap: **200 characters**, using LangChain's `RecursiveCharacterTextSplitter`. The overlap ensures that a rule spanning a paragraph boundary isn't split mid-sentence and lost to retrieval.

Evidence: `backend/src/services/policy_indexing.py`

---

## SECTION 4 — HYBRID INGESTION

### Q: What is the hybrid ingestion service and why three methods?

**Short answer:** Getting accurate captions out of YouTube is unreliable. No single method works for all videos, so I implemented a fallback chain.

- Method 1 — `timedtext` endpoint: Direct call to `youtube.com/api/timedtext?v=VIDEO_ID&lang=en`. No auth, fast, works for videos with official captions. First tried for `en`, `en-US`, `en-GB` in order.
- Method 2 — `yt-dlp`: A well-maintained open source library that can extract auto-generated subtitles. Slower, downloads caption track URL from video info, fetches the raw track. Catches videos where the timedtext endpoint is blocked or returns nothing.
- Method 3 — Azure Video Indexer: The heavy fallback. Uploads the video URL to Azure VI, polls until `state == "Processed"` (up to 30 polls × 5s), then pulls both speech transcript AND `ocr` (on-screen text). This is the only source of OCR data.
- If all fail: the pipeline continues with just the metadata from the indexer node — it degrades gracefully rather than crashing.

Evidence: `backend/src/services/ingestion.py` — `HybridIngestionService.enrich()`

---

### Q: Why did you keep all three instead of just using Azure Video Indexer?

Cost and latency. Azure Video Indexer uploads and processes the full video — that's minutes of wait time and non-trivial cost per audit. The `timedtext` endpoint is free and instantaneous. yt-dlp is free and takes a few seconds. The expensive path only runs when both cheaper paths return nothing. You also need `AZURE_VI_ACCOUNT_ID` and `AZURE_VI_LOCATION` to be configured; the code checks for those before attempting it.

Evidence: `backend/src/services/ingestion.py` — `if all([VideoIndexerService().account_id, ...])`

---

### Q: What is the `ingestion_source` field for?

It records which method actually provided the content: `"metadata"`, `"captions"`, `"captions_ytdlp"`, or `"video_indexer"`. This is stored on the `Audit` DB row and returned in the API response. A reviewer looking at a FAIL result can see whether the audit was based on full captions or just metadata — which matters for confidence in the finding.

Evidence: `backend/src/db/models.py` (`ingestion_source` column on `Audit`), `backend/src/api/server.py`

---

## SECTION 5 — FASTAPI & SERVER DESIGN

### Q: Why FastAPI over Flask or Django?

**Verdict:** FastAPI, because this is a pure API with async I/O and I need automatic OpenAPI docs.

- Why it fits here: the `/audit` endpoint calls `compliance_graph.ainvoke()` which is async — FastAPI handles that natively. Flask is WSGI-only, Django is overkill for a JSON API.
- What Django is genuinely better at: built-in admin, ORM, session management — a full web app. Not needed here.
- Trade-off I accepted: FastAPI has no built-in background task queue. If audit volume got high I'd need to add a queue (Celery, ARQ). Right now it runs synchronously per request.

Evidence: `backend/src/api/server.py` — `FastAPI()`, `async def audit_video(...)`

---

### Q: How does the lifespan work?

FastAPI's `lifespan` context manager runs code at server startup (before the first request) and shutdown. In this project it bootstraps a default `Team` record in the DB when `AUTH_DISABLED=true`. This ensures the dev path has a team to attach users to without manual setup. In production (`AUTH_DISABLED=false`) this block doesn't run.

Evidence: `backend/src/api/server.py` — `@asynccontextmanager async def lifespan(app)`

---

### Q: What CORS setup did you use?

Origins are read from `ALLOWED_ORIGINS` env var as a comma-separated list (`_parse_allowed_origins()`), falling back to `http://localhost:8000`. The README explicitly warns against wildcard origins in production. `allow_credentials=True` is set, which is needed if the frontend sends cookies or auth headers.

Evidence: `backend/src/api/server.py`

---

## SECTION 6 — AUTHENTICATION & AUTHORIZATION

### Q: Explain the auth system.

**Short answer:** Dual-path auth — Microsoft Entra ID (JWT Bearer) for human users, SHA-256 hashed API keys for programmatic access — with three RBAC roles.

- **Entra ID path:** `GET /auth/me` and `POST /audit` check for a Bearer token. `decode_entra_token()` uses `PyJWKClient` to fetch Microsoft's public signing keys from the JWKS endpoint, validates the RS256 JWT (checking `exp`, `iss`, `aud`, `sub`), extracts the `oid` claim as the stable user ID, and maps `roles` claims to one of `admin`, `reviewer`, `read_only`.
- **API key path:** If `X-API-Key` header is present, `authenticate_api_key()` SHA-256 hashes the raw key, looks up the hash in `team_api_keys`, and synthesizes a `User` record scoped to that team.
- **Roles:** `admin` can reindex policies and manage API keys. `reviewer` can submit audits and override AI decisions. `read_only` can only list audit history — `require_audit_submitter` blocks them with 403.

Evidence: `backend/src/auth/dependencies.py`, `backend/src/auth/entra.py`, `backend/src/auth/api_keys.py`

---

### Q: Why PyJWT over python-jose or authlib?

`PyJWT` is the most widely maintained pure-Python JWT library. `python-jose` has had CVEs and slow maintenance. `authlib` is heavier and aimed at OAuth server implementation. For this use case — only token validation, not issuance — `PyJWT[crypto]` with its `PyJWKClient` is the minimal, correct choice.

Evidence: `pyproject.toml` — `"pyjwt[crypto]>=2.10.0"`

---

### Q: How does the JWKS client cache work?

The module-level `_jwks_client` is reused for 1 hour (`_JWKS_TTL_SECONDS = 3600`). `_get_jwks_client()` checks `time.time() - _jwks_client_created_at > 3600` and recreates the client if stale. This avoids a JWKS HTTP call on every request while not caching keys forever (Microsoft rotates keys periodically).

Evidence: `backend/src/auth/entra.py`

---

### Q: Why SHA-256 for API key hashing, not bcrypt?

API keys are long random secrets (32 bytes from `secrets.token_urlsafe`), so brute-force is impractical. bcrypt is designed for low-entropy passwords. SHA-256 is fast enough for a 256-bit random key lookup and doesn't add bcrypt's CPU cost per request. The `bg_` prefix allows fast rejection of non-API-key strings before hashing.

Evidence: `backend/src/auth/api_keys.py` — `hash_api_key()`, `raw_key = f"bg_{secrets.token_urlsafe(32)}"`

---

### Q: What is `AUTH_DISABLED` and why does it exist?

It's a dev escape hatch (`AUTH_DISABLED=true` in `.env`) that bypasses all token validation and returns a hardcoded admin `UserContext` via `_dev_user_context()`. Without it, local development requires a real Entra ID tenant, which is friction. The README explicitly says never set this in production. The code checks it with `os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes")` to prevent accidental activation.

Evidence: `backend/src/auth/dependencies.py`, `backend/src/auth/entra.py`

---

## SECTION 7 — DATABASE & ORM

### Q: Why SQLAlchemy + PostgreSQL? Why not a NoSQL store?

**Verdict:** SQLAlchemy + PostgreSQL because the data has a clear relational shape and I needed audit history queries scoped by team.

- The schema has explicit FK relationships: `Team → User → Audit → AuditViolation`, `Audit → ReviewDecision`, `Audit → PolicyVersion`. These are naturally relational.
- Team-scoped queries (`list_audits_for_team`) benefit from indexed FK columns and the composite index `ix_audits_team_created` on `(team_id, created_at)`.
- `raw_response` is stored as JSONB — so the structured fields are normalized and queryable, but the full LLM response is also preserved for debugging.
- Alembic handles schema migrations with two versions: `001_initial_schema.py` (all core tables) and `002_team_api_keys.py` (adds `team_api_keys`). That's a real incremental migration history.

Evidence: `backend/src/db/models.py`, `alembic/versions/`

---

### Q: What is the `ai_status` vs `final_status` distinction?

`ai_status` is what the LLM returned (PASS/FAIL). `final_status` is the effective status after a human reviewer potentially overrides it. When no review exists, `final_status == ai_status`. When a reviewer calls `POST /reviews/{audit_id}` with `approved` or `rejected`, the `final_status` is updated. This separation is the core of the human-in-the-loop design — you can always see what the AI said versus what a human decided.

Evidence: `backend/src/db/models.py` — `Audit` model

---

### Q: Why store `raw_response` as JSONB?

Compliance is an audit trail domain. If the LLM output format changes, or if a team disputes a finding, you want the original response to be reconstructable. JSONB lets you store the full unmodified response without a schema migration every time the `compliance_results` format evolves, while still being queryable in PostgreSQL if needed.

Evidence: `backend/src/db/models.py` — `raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)`

---

### Q: Why is `policy_version_id` on the Audit row?

So you can always know exactly which version of the compliance documents was in the vector store when this audit ran. If you re-index with updated PDFs, old audits still reference the previous policy version. This is important for compliance traceability: "this ad was audited against policy v20250601-143022."

Evidence: `backend/src/db/models.py`, `backend/src/api/server.py` — `policy_version = get_current_policy_version(db)`

---

## SECTION 8 — RATE LIMITING

### Q: How does the rate limiter work?

**In one line:** In-memory sliding window per IP address, 30 requests per minute, applies only to `POST /audit`.

- It's a `BaseHTTPMiddleware` subclass. Each IP gets a `deque[float]` of request timestamps. On each request, stale entries (older than 60s) are popped from the left. If `len(bucket) >= 30`, it returns 429.
- Only `POST /audit` is rate-limited — all other routes pass through immediately.
- The limit is configurable via `RATE_LIMIT_PER_MINUTE` env var.

Evidence: `backend/src/middleware/rate_limit.py`

---

### Q: Redis is in your dependencies but you don't use it. Why?

`redis>=7.1.0` is installed but the rate limiter uses an in-memory `defaultdict(deque)`. The comment in the code says "Simple in memory rate limiter for pilot deployments." This is a deliberate ceiling for a single-instance deployment — the kind you get on Azure Container Apps' free tier with one replica.

The known ceiling: if you scale to multiple replicas, each instance has its own counter and the limit effectively multiplies. The upgrade path is to swap the deque for a Redis sorted set (ZRANGEBYSCORE + ZADD + EXPIRE) — Redis is already in the dependency so that migration is a one-file change.

Evidence: `backend/src/middleware/rate_limit.py` — docstring "Simple in memory rate limiter for pilot deployments", `pyproject.toml` — `"redis>=7.1.0"`

---

## SECTION 9 — OBSERVABILITY

### Q: How did you instrument this for observability?

Azure Monitor OpenTelemetry. `setup_telemetry()` in `telemetry.py` is called at server startup. It wires `azure-monitor-opentelemetry` into the FastAPI app via the `opentelemetry-instrumentation-fastapi` package. Traces flow into Azure Application Insights automatically (request spans, dependency spans for outbound HTTP calls to Azure OpenAI and Azure Search). LangSmith is also configured for optional LLM-level tracing (`LANGCHAIN_TRACING_V2=true`).

Evidence: `backend/src/api/telemetry.py`, `backend/src/api/server.py` — `setup_telemetry()`, `pyproject.toml` — `azure-monitor-opentelemetry`, `opentelemetry-instrumentation-fastapi`

---

## SECTION 10 — CI/CD & DEPLOYMENT

### Q: How does deployment work?

GitHub Actions pipeline in `.github/workflows/deploy.yml` triggers on every push to `main`. It builds a Docker image, pushes it to Azure Container Registry, and updates the Azure Container Apps revision. Container Apps is serverless — it scales to zero when there's no traffic, so there's no cost on idle. The `Dockerfile` packages the full Python app with `uvicorn` as the ASGI server.

Evidence: `.github/workflows/deploy.yml`, `Dockerfile`

---

### Q: Why Azure Container Apps over a VM or Kubernetes?

**Verdict:** Container Apps because it removes infra management at this scale.

- For a pilot internal tool, I don't need cluster management, node pools, or manual scaling rules. Container Apps handles that with a managed Kubernetes layer.
- Scale-to-zero means the free tier essentially runs for free when reviewers aren't active.
- What Kubernetes is genuinely better at: fine-grained scheduling, multi-service mesh, stateful workloads. Overkill here.
- Trade-off: Container Apps' concurrency model is simpler — can't tune pod scheduling, no sidecar containers without a workaround.

Evidence: `README.md` architecture table, `.github/workflows/deploy.yml`

---

## SECTION 11 — LLM DESIGN CHOICES

### Q: Why GPT-4o at temperature 0.0?

Temperature 0.0 makes the model deterministic — it always picks the highest probability token. For compliance auditing, you don't want creative variation. Two audits of the same video should return the same findings. The alternative — a higher temperature — might randomly include or exclude a violation between runs, which is unacceptable for a legal/compliance use case.

Evidence: `backend/src/graph/nodes.py` — `AzureChatOpenAI(..., temperature=0.0)`

---

### Q: Why structure the prompt to return JSON instead of free text?

The response is parsed with `json.loads()` and each violation is mapped into a typed `ComplianceIssue` object. Free text would require regex parsing to extract severity, category, and chunk_id — fragile and hard to version. The prompt includes a guard for markdown fences (`if "```" in content`) because GPT-4o sometimes wraps JSON in code blocks even when told not to.

Evidence: `backend/src/graph/nodes.py` — system prompt and `re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)`

---

### Q: Why did you use `SystemMessage + HumanMessage` instead of a single message?

The system prompt contains the retrieved policy rules and the auditor persona — things that should be treated as ground truth. The human message contains the video content to analyze. This split is both idiomatic for chat models and functionally important: system messages get higher attention weight and are less likely to be ignored when the model has to balance a long context.

Evidence: `backend/src/graph/nodes.py` — `llm.invoke([SystemMessage(...), HumanMessage(...)])`

---

## SECTION 12 — TESTING

### Q: What did you test?

Three test files, no framework beyond pytest:

- `tests/test_auth.py` — confirms `/health` is public (no auth), that the debug env routes were removed, that no token returns 401, and that a read-only user gets 403 on `POST /audit`.
- `tests/test_citations.py` — unit tests for `_attach_citations()`: happy path (chunk_id resolves to source + excerpt) and graceful handling of a missing chunk_id (row passes through unchanged).
- `tests/test_ingestion_hybrid.py` — tests the hybrid ingestion service: captions path sets `ingestion_source = "captions"`, and the metadata-only fallback path when captions return nothing.

Evidence: `tests/` directory

---

## SECTION 13 — TRADE-OFFS YOU ACCEPTED

### Q: What would you change if this went to production at scale?

1. **Rate limiter:** swap in-memory deque for Redis sorted set. Redis is already installed, it's a one-file change. Current limiter is per-replica, not per-cluster.
2. **Sync audit endpoint:** `/audit` blocks until the full LangGraph pipeline completes (several seconds). At scale, move to async job queue (Celery, ARQ) — submit returns a job ID, poll or webhook for result.
3. **API key auth defaults to `reviewer` role:** every API key gets `reviewer` — no finer-grained key-level permissions. For multi-tenant SaaS this needs per-key role scoping.
4. **No connection pooling on vector store:** `get_vector_store()` creates a new `AzureSearch` object on every audit. Under load this means repeated HTTP connection setup. Add a module-level singleton.
5. **Azure Video Indexer polls with `time.sleep(5)` 30 times:** that's a 150s max wait on the same thread. Move to proper async polling or a background task.

---

## SECTION 14 — GAPS (What the repo does NOT demonstrate)

| Claim | What's actually here |
|---|---|
| "Used Redis" | Redis is installed but not used — rate limiter is in-memory |
| "Built a queue / async job system" | No queue — synchronous request/response only |
| "Multi-tenant SaaS" | Team isolation exists but it's a single-tenant internal tool |
| "Fine-tuned a model" | No fine-tuning — prompt engineering only |
| "Real-time streaming" | No SSE or WebSocket — batch JSON response |
| "Docker Compose" | No docker-compose.yml — single container only |

Be precise about these if asked. Don't overclaim.

---

## QUICK CHEAT SHEET — Key Numbers

| Value | Source |
|---|---|
| RAG_TOP_K default | 8 (`policy_store.py`) |
| Chunk size / overlap | 1000 / 200 chars (`policy_indexing.py`) |
| LLM model | GPT-4o at temperature 0.0 (`nodes.py`) |
| Embedding model | text-embedding-3-small (`policy_store.py`) |
| Rate limit | 30 POST /audit per IP per minute (`rate_limit.py`) |
| JWKS cache TTL | 1 hour / 3600s (`entra.py`) |
| API key prefix | `bg_` + 32-byte urlsafe token (`api_keys.py`) |
| API key hashing | SHA-256 (`api_keys.py`) |
| Ingestion fallback chain | timedtext → yt-dlp → Azure Video Indexer (`ingestion.py`) |
| DB | PostgreSQL via SQLAlchemy 2.0 + Alembic (`pyproject.toml`) |
| Deployment | Azure Container Apps via GitHub Actions (`deploy.yml`) |
| Python version | 3.12+ (`pyproject.toml`) |
