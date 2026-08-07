"""
Centralized configuration. Validates required env vars at import time — app refuses to start
if anything critical is missing.

Usage:
    from src.config import config
    config.AZURE_OPENAI_ENDPOINT  # validated str
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)


def _require(name: str) -> str:
    """Return env var value or raise immediately with a clear message."""
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Config:
    """Immutable app config. All required vars validated at construction time."""

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = field(default_factory=lambda: _require("AZURE_OPENAI_ENDPOINT"))
    AZURE_OPENAI_API_KEY: str = field(default_factory=lambda: _require("AZURE_OPENAI_API_KEY"))
    AZURE_OPENAI_API_VERSION: str = field(default_factory=lambda: _optional("AZURE_OPENAI_API_VERSION", "2024-02-01"))
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = field(default_factory=lambda: _require("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = field(default_factory=lambda: _require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"))
    AZURE_OPENAI_WHISPER_DEPLOYMENT: str = field(default_factory=lambda: _optional("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper"))

    # Azure AI Search
    AZURE_SEARCH_ENDPOINT: str = field(default_factory=lambda: _require("AZURE_SEARCH_ENDPOINT"))
    AZURE_SEARCH_API_KEY: str = field(default_factory=lambda: _require("AZURE_SEARCH_API_KEY"))
    AZURE_SEARCH_INDEX_NAME: str = field(default_factory=lambda: _optional("AZURE_SEARCH_INDEX_NAME", "brand-compliance-rules"))

    # Azure Storage
    AZURE_STORAGE_CONNECTION_STRING: str = field(default_factory=lambda: _require("AZURE_STORAGE_CONNECTION_STRING"))
    AZURE_STORAGE_CONTAINER: str = field(default_factory=lambda: _optional("AZURE_STORAGE_CONTAINER", "uploads"))
    AZURE_STORAGE_QUEUE_NAME: str = field(default_factory=lambda: _optional("AZURE_STORAGE_QUEUE_NAME", "audit-jobs"))

    # Phi-4 (Azure AI Foundry)
    PHI4_ENDPOINT: str = field(default_factory=lambda: _optional("PHI4_ENDPOINT", ""))
    PHI4_API_KEY: str = field(default_factory=lambda: _optional("PHI4_API_KEY", ""))

    # Database
    DATABASE_URL: str = field(default_factory=lambda: _require("DATABASE_URL"))

    # Optional services
    FIRECRAWL_API_KEY: str = field(default_factory=lambda: _optional("FIRECRAWL_API_KEY", ""))
    YOUTUBE_API_KEY: str = field(default_factory=lambda: _optional("YOUTUBE_API_KEY", ""))
    LOG_LEVEL: str = field(default_factory=lambda: _optional("LOG_LEVEL", "INFO"))

    # Sanitizer defaults
    MAX_TRANSCRIPT_TOKENS: int = field(default_factory=lambda: int(_optional("MAX_TRANSCRIPT_TOKENS", "4000")))

    # Groq (Whisper transcription)
    GROQ_API_KEY: str = field(default_factory=lambda: _optional("GROQ_API_KEY", ""))

    # Langfuse observability
    LANGFUSE_PUBLIC_KEY: str = field(default_factory=lambda: _optional("LANGFUSE_PUBLIC_KEY", ""))
    LANGFUSE_SECRET_KEY: str = field(default_factory=lambda: _optional("LANGFUSE_SECRET_KEY", ""))
    LANGFUSE_HOST: str = field(default_factory=lambda: _optional("LANGFUSE_HOST", "") or _optional("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))


# ponytail: single module-level instance. Import `config` — not the class.
config = Config()
