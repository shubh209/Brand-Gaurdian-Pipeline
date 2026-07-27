"""
Input sanitizer: validates uploads and cleans text before it reaches any LLM.
Every path that sends text to GPT-4o or Phi-4 must go through sanitize_text().
"""
import re
import subprocess
import logging

import magic
import tiktoken

from src.config import config
from src.errors import ValidationError

logger = logging.getLogger("brand-guardian.sanitizer")

# ponytail: compile once at module level
_INJECTION_PATTERNS = re.compile(
    r"|".join([
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?above\s+instructions",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now\s+a",
        r"new\s+instructions:",
        r"system\s*prompt:",
        r"<\s*/?\s*system\s*>",
        r"\[INST\]",
        r"\[/INST\]",
        r"<<\s*SYS\s*>>",
    ]),
    re.IGNORECASE,
)

# Unicode control characters that can confuse tokenizers / hide injection
_CONTROL_CHARS = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff\x00-\x08\x0b\x0c\x0e-\x1f]"
)

_ALLOWED_MIME_PREFIXES = ("video/",)

# ponytail: reuse one encoder instance
_tokenizer = tiktoken.get_encoding("cl100k_base")


def sanitize_text(text: str) -> str:
    """
    Clean text before sending to any LLM.
    Strips unicode control chars, prompt injection patterns, and truncates to token limit.
    """
    if not text:
        return ""

    # Strip unicode control characters
    text = _CONTROL_CHARS.sub("", text)

    # Strip known prompt injection patterns
    text = _INJECTION_PATTERNS.sub("[REDACTED]", text)

    # Truncate to token limit
    max_tokens = config.MAX_TRANSCRIPT_TOKENS
    tokens = _tokenizer.encode(text)
    if len(tokens) > max_tokens:
        text = _tokenizer.decode(tokens[:max_tokens])
        # ponytail: ceiling is token-boundary truncation — could split mid-word.
        # Upgrade path: find last sentence boundary within limit.

    return text.strip()


def validate_upload(file_path: str) -> None:
    """
    Validate an uploaded video file. Raises ValidationError if:
    - Not a video MIME type
    - No audio track (nothing to transcribe)

    Returns None on success.
    """
    # MIME type check
    mime = magic.from_file(file_path, mime=True)
    if not mime or not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise ValidationError(
            f"Invalid file type: {mime}. Only video files are accepted."
        )

    # Audio track check via ffprobe
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if not result.stdout.strip():
        raise ValidationError(
            "Video has no audio track. Cannot transcribe a silent video."
        )
