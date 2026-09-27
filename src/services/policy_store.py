import logging
import logging
import os
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.config import config
from src.db.models import PolicyVersion
from src.db.repository import get_current_policy_version

logger = logging.getLogger("brand-guardian")

# Collection name for the pgvector store (one logical index of policy chunks).
_PGVECTOR_COLLECTION = "brand_compliance_rules"

# ponytail: module-level singleton. Not safe across forked processes.
# Upgrade: use a connection pool if multi-process workers are added.
_store = None
_store_lock = threading.Lock()

_ALLOWED_PLATFORMS = {"youtube", "tiktok", "facebook", "meta", "generic", "x"}


@dataclass
class RetrievedChunk:
    chunk_id: str
    source: str
    content: str
    score: float = 0.0
    page: int | None = None
    platform: str | None = None


def _pgvector_connection() -> str:
    """DATABASE_URL as a psycopg (v3) URL, which langchain_postgres.PGVector requires."""
    url = config.DATABASE_URL
    # Normalize any psycopg2 / bare scheme to the psycopg v3 driver.
    for prefix in ("postgresql+psycopg2://", "postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _build_store():
    """Build the vector store selected by VECTOR_STORE. pgvector is the live backend."""
    if config.VECTOR_STORE == "pgvector":
        from langchain_postgres import PGVector
        from src.services.embeddings_factory import get_embeddings
        return PGVector(
            embeddings=get_embeddings(),
            collection_name=_PGVECTOR_COLLECTION,
            connection=_pgvector_connection(),
            use_jsonb=True,
        )
    raise ValueError(f"Unknown VECTOR_STORE: {config.VECTOR_STORE!r} (expected 'pgvector')")


def get_vector_store():
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = _build_store()
    return _store


def rag_top_k() -> int:
    return int(os.getenv("RAG_TOP_K", "20"))  # over-retrieve for reranking


def rag_min_score() -> float:
    # ponytail: Azure AI Search scores are BM25-based (typically 0.01-0.10),
    # not cosine similarity (0-1). Default 0.0 = no filtering; reranker handles quality.
    # Upgrade: tune this after measuring score distributions in Langfuse.
    return float(os.getenv("RAG_MIN_SCORE", "0.0"))


def search_policy_chunks(
    query_text: str,
    k: int | None = None,
    platform: str | None = None,
) -> list[RetrievedChunk]:
    if platform and platform not in _ALLOWED_PLATFORMS:
        raise ValueError(f"Unknown platform: {platform!r}. Allowed: {_ALLOWED_PLATFORMS}")

    # ponytail: normalize 'meta' to 'facebook' (indexed as 'facebook' in vector store)
    if platform == "meta":
        platform = "facebook"

    store = get_vector_store()
    top_k = k or rag_top_k()

    # pgvector metadata filter (dict), translated from the old Azure OData string.
    # Restrict to the requested platform plus 'generic' (cross-platform) rules.
    pg_filter = None
    if platform:
        pg_filter = {"platform": {"$in": [platform, "generic"]}}

    # ponytail: pgvector has no semantic-hybrid search (that was Azure-only); the
    # cross-encoder reranker downstream (policy_retriever) compensates for ranking quality.
    # Ceiling: pure vector similarity, no BM25 hybrid. Upgrade: add a pgvector full-text
    # hybrid query if recall proves insufficient after the #15 eval.
    # Note: PGVector scores are DISTANCES (lower = closer), unlike Azure relevance (higher
    # = better). rag_min_score defaults to 0.0 (off) and the reranker re-scores, so the
    # RetrievedChunk.score here is only a coarse ordering signal.
    try:
        results = store.similarity_search_with_score(query_text, k=top_k, filter=pg_filter)
    except Exception:
        results = store.similarity_search_with_score(query_text, k=top_k)

    chunks: list[RetrievedChunk] = []
    for doc, score in results:
        meta = doc.metadata or {}
        chunk_id = str(meta.get("chunk_id") or meta.get("id") or uuid.uuid4())
        chunks.append(RetrievedChunk(
            chunk_id=chunk_id,
            source=str(meta.get("source", "unknown")),
            content=doc.page_content,
            score=float(score),
            page=meta.get("page"),
            platform=meta.get("platform"),
        ))

    # ponytail: apply min_score filter after collection (same as before hybrid upgrade)
    min_score = rag_min_score()
    if min_score > 0.0:
        chunks = [c for c in chunks if c.score >= min_score]

    if not chunks and results:
        logger.warning("All %d chunks filtered for query: %.80s", len(results), query_text)

    return chunks


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            f"[CHUNK_ID: {chunk.chunk_id} | SOURCE: {chunk.source}]\n{chunk.content}"
        )
    return "\n\n".join(parts)


def resolve_current_policy_version(db: Session | None) -> PolicyVersion | None:
    if db is None:
        return None
    return get_current_policy_version(db)
