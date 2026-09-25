"""
Embedding provider seam — returns a LangChain Embeddings object chosen by config.

The *specific* local model is a config value (`EMBEDDING_MODEL`), NOT hardcoded, so the
eval bake-off (#15) can swap candidates (all-MiniLM-L6-v2 384d, bge-small, gte-small,
all-mpnet 768d) without code changes.

ponytail: lazy module singleton per model name — loading a sentence-transformers model
costs seconds, so we cache it. Not safe across forked processes; fine for one worker.
RAM ceiling: bigger models (768d) use more memory on the Fly box (#6 findings, #15 bake-off).
"""
import logging
import threading

from langchain_core.embeddings import Embeddings

from src.config import config

logger = logging.getLogger("brand-guardian")

_embeddings: Embeddings | None = None
_lock = threading.Lock()
_loaded_key: str | None = None


def _build() -> Embeddings:
    provider = config.EMBEDDING_PROVIDER
    if provider == "local":
        # HuggingFaceEmbeddings wraps sentence-transformers; model chosen by config.
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)
    if provider == "openai":
        # Future paid option — reads OPENAI_API_KEY from env.
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=config.EMBEDDING_MODEL)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider!r} (expected 'local' or 'openai')")


def get_embeddings() -> Embeddings:
    """Return the configured embedder. Rebuilds if the provider/model config changed."""
    global _embeddings, _loaded_key
    key = f"{config.EMBEDDING_PROVIDER}:{config.EMBEDDING_MODEL}"
    if _embeddings is None or _loaded_key != key:
        with _lock:
            if _embeddings is None or _loaded_key != key:
                logger.info("Loading embeddings: %s", key)
                _embeddings = _build()
                _loaded_key = key
    return _embeddings
