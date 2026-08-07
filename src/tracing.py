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


def _ensure_langfuse_env():
    """Ensure Langfuse SDK reads the correct env vars.
    ponytail: SDK v4 reads LANGFUSE_HOST but .env may have LANGFUSE_BASE_URL.
    """
    import os
    if not os.environ.get("LANGFUSE_HOST"):
        base_url = os.environ.get("LANGFUSE_BASE_URL", "")
        if base_url:
            os.environ["LANGFUSE_HOST"] = base_url


_ensure_langfuse_env()


# ── Re-export the @observe decorator ─────────────────────────────────────────
# ponytail: Langfuse v4 @observe uses OpenTelemetry and can block on span export
# if the host is unreachable or keys are invalid. Use the no-op decorator for now
# and rely on CallbackHandler (fire-and-forget) for LLM tracing.
# Ceiling: no automatic span hierarchy. Upgrade path: fix Langfuse auth, re-enable @observe.

logger.info("Langfuse: using CallbackHandler approach (non-blocking)")


def observe(func=None, *, name=None, **kwargs):
    """No-op decorator — avoids @observe blocking on span export."""
    if func is not None:
        return func

    def wrapper(fn):
        return fn
    return wrapper


def get_langchain_handler():
    """
    Get a LangChain callback handler for tracing LLM calls.
    ponytail: Langfuse CallbackHandler v4 blocks on init when host is unreachable.
    Disabled until auth/host issue resolved. Returns None (no tracing).
    Ceiling: no LLM call tracing. Upgrade path: fix LANGFUSE_HOST, re-enable.
    """
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
