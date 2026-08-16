import logging
import os
import threading
import uuid
from dataclasses import dataclass

from langchain_openai import AzureOpenAIEmbeddings
from langchain_community.vectorstores import AzureSearch
from sqlalchemy.orm import Session

from src.db.models import PolicyVersion
from src.db.repository import get_current_policy_version

logger = logging.getLogger("brand-guardian")

# ponytail: module-level singleton. Not safe across forked processes.
# Upgrade: use a connection pool if multi-process workers are added.
_store: AzureSearch | None = None
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


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _build_store() -> AzureSearch:
    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        azure_endpoint=_require_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_require_env("AZURE_OPENAI_API_KEY"),
        openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )
    return AzureSearch(
        azure_search_endpoint=_require_env("AZURE_SEARCH_ENDPOINT"),
        azure_search_key=_require_env("AZURE_SEARCH_API_KEY"),
        index_name=_require_env("AZURE_SEARCH_INDEX_NAME"),
        embedding_function=embeddings.embed_query,
    )


def get_vector_store() -> AzureSearch:
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

    filters = None
    if platform:
        filters = f"platform eq '{platform}' or platform eq 'generic'"

    # ponytail: try semantic hybrid search first; falls back if semantic ranker not configured
    try:
        results = store.semantic_hybrid_search_with_score(
            query_text, k=top_k, filters=filters
        )
    except Exception:
        try:
            results = store.similarity_search_with_score(query_text, k=top_k, filters=filters)
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
