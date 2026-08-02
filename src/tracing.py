"""
Langfuse observability for the Brand Guardian pipeline.

Best practices (Langfuse v4):
- Use @observe() decorator on pipeline functions to create automatic trace hierarchy
- Use langfuse_context inside decorated functions to get nested LangChain callbacks
- Attach session_id (audit_id) to group traces per audit
- Attach metadata (platforms, audit_mode) for filtering in dashboard

Usage in V2 modules:
    from src.tracing import observe, get_langchain_handler

    @observe(name="claim_extraction")
    def extract_claims(...):
        handler = get_langchain_handler()
        response = llm.invoke(messages, config={"callbacks": [handler] if handler else []})

Usage for top-level audit trace:
    from src.tracing import observe, update_trace

    @observe(name="compliance_audit")
    def run_audit(audit_id, ...):
        update_trace(session_id=audit_id, metadata={"platforms": platforms})
        ...
"""
import logging
import os

from src.config import config

logger = logging.getLogger("brand-guardian.tracing")


def _langfuse_enabled() -> bool:
    return bool(config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY)


# ── Re-export the @observe decorator ─────────────────────────────────────────
# If Langfuse is not configured, provide a no-op decorator so callers don't need guards.

if _langfuse_enabled():
    from langfuse import observe  # noqa: F401
    logger.info("Langfuse tracing enabled (@observe active)")
else:
    logger.info("Langfuse tracing disabled (keys not set) — @observe is no-op")

    def observe(func=None, *, name=None, **kwargs):
        """No-op decorator when Langfuse is not configured."""
        if func is not None:
            return func

        def wrapper(fn):
            return fn
        return wrapper


def get_langchain_handler():
    """
    Get a LangChain callback handler nested under the current @observe span.
    Returns None if Langfuse is not configured or not in an active trace.

    Usage:
        handler = get_langchain_handler()
        llm.invoke(messages, config={"callbacks": [handler] if handler else []})
    """
    if not _langfuse_enabled():
        return None
    try:
        from langfuse import get_client
        client = get_client()
        handler = client.get_current_langchain_handler()
        return handler
    except Exception:
        # Not inside an @observe context or client not initialized
        return None


def update_trace(
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> None:
    """
    Update the current trace with session/user/metadata.
    Call inside an @observe-decorated function to enrich the active trace.

    - session_id: groups traces (use audit_id to see all LLM calls for one audit)
    - user_id: the team or user who triggered the audit
    - metadata: arbitrary dict (platforms, audit_mode, file_hash, etc.)
    - tags: for filtering in Langfuse UI (e.g., ["upload", "youtube"])
    """
    if not _langfuse_enabled():
        return
    try:
        from langfuse import get_client
        client = get_client()
        update_kwargs = {}
        if session_id:
            update_kwargs["session_id"] = session_id
        if user_id:
            update_kwargs["user_id"] = user_id
        if metadata:
            update_kwargs["metadata"] = metadata
        if tags:
            update_kwargs["tags"] = tags
        if update_kwargs:
            client.update_current_trace(**update_kwargs)
    except Exception as exc:
        logger.debug("update_trace failed (not in active trace?): %s", exc)


# ── Legacy compatibility ─────────────────────────────────────────────────────

def get_langfuse_callbacks() -> list:
    """Legacy helper. Prefer get_langchain_handler() inside @observe functions.
    Returns a list with one handler or empty list. Safe to always spread into callbacks.
    """
    handler = get_langchain_handler()
    return [handler] if handler else []
