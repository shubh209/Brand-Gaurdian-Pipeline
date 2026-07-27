"""
Langfuse tracing for LLM calls.
Provides a shared callback handler that V2 modules pass to LangChain .invoke() calls.

Usage:
    from src.tracing import get_langfuse_callbacks
    llm.invoke(messages, config={"callbacks": get_langfuse_callbacks(trace_name="audit")})
"""
import logging

from src.config import config

logger = logging.getLogger("brand-guardian.tracing")

_handler = None
_initialized = False


def _init_handler():
    global _handler, _initialized
    if _initialized:
        return
    _initialized = True

    if not config.LANGFUSE_PUBLIC_KEY or not config.LANGFUSE_SECRET_KEY:
        logger.info("Langfuse tracing disabled (keys not set)")
        return

    try:
        from langfuse.langchain import CallbackHandler
        # ponytail: langfuse v4+ reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
        # from env vars automatically. No constructor args needed.
        _handler = CallbackHandler()
        logger.info("Langfuse tracing enabled")
    except Exception as exc:
        logger.warning("Langfuse init failed: %s", exc)


def get_langfuse_callbacks() -> list:
    """Return Langfuse callback list for LangChain .invoke() calls.
    Returns empty list if Langfuse is not configured — safe to always pass.
    """
    _init_handler()
    return [_handler] if _handler else []
