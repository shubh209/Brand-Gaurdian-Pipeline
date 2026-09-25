"""
LLM provider seam — one place that hands out chat + mini LLM clients.

Built on LiteLLM (via LangChain's ChatLiteLLM) so the vendor is a config value:
`LLM_PROVIDER` + LiteLLM-style model IDs (`groq/openai/gpt-oss-120b`, `openai/gpt-4o`,
`gemini/gemini-2.0-flash`, `openrouter/...`). Callers use the returned object exactly
like the old `AzureChatOpenAI`: `.invoke([messages], config={...}).content`.

ponytail: SDK-level seam only. No routing/fallback/proxy — if multi-model routing is
ever needed, add a LiteLLM Proxy or OpenRouter behind this same seam (see epic #23).

Verified in preflight (#2/#3): LiteLLM normalizes the gpt-oss empty-content quirk that
the raw OpenAI client tripped on. `logprobs` is NOT supported on gpt-oss and must not be
passed when LLM_PROVIDER=groq (see supports_logprobs()).
"""
import os

from langchain_community.chat_models import ChatLiteLLM

from src.config import config


def _ensure_provider_key() -> None:
    """LiteLLM reads provider credentials from env vars. Bridge our config into them."""
    if config.LLM_PROVIDER == "groq" and config.GROQ_API_KEY:
        os.environ.setdefault("GROQ_API_KEY", config.GROQ_API_KEY)
    elif config.LLM_PROVIDER in ("openai", "azure") and config.AZURE_OPENAI_API_KEY:
        # OpenAI-compatible fallbacks read OPENAI_API_KEY; wired if/when those providers are used.
        os.environ.setdefault("OPENAI_API_KEY", config.AZURE_OPENAI_API_KEY)


def supports_logprobs() -> bool:
    """gpt-oss on Groq rejects `logprobs` with a 400. Call sites gate on this."""
    return config.LLM_PROVIDER not in ("groq",)


def chat(temperature: float = 0.1) -> ChatLiteLLM:
    """Reasoning model. Replaces the old per-module `_llm()` factories."""
    _ensure_provider_key()
    return ChatLiteLLM(
        model=config.LLM_CHAT_MODEL,
        temperature=temperature,
        max_tokens=2048,
        request_timeout=60,
    )


def mini(temperature: float = 0.1) -> ChatLiteLLM:
    """Cheap/fast model for extraction + query expansion. Replaces `_mini_llm()`."""
    _ensure_provider_key()
    return ChatLiteLLM(
        model=config.LLM_MINI_MODEL,
        temperature=temperature,
        max_tokens=2048,
        request_timeout=30,
    )
