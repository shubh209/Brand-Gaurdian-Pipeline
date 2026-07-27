"""Phase 8: Langfuse observability tests."""
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _get_setup_langfuse():
    # Re-import to get fresh module state each time
    import src.api.server as srv
    return srv._setup_langfuse


def test_langfuse_setup_skips_when_no_keys():
    with patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}, clear=False):
        fn = _get_setup_langfuse()
        result = fn()
    assert result is None


def test_langfuse_setup_returns_handler_when_keys_set():
    fake_handler = MagicMock()
    fake_cls = MagicMock(return_value=fake_handler)
    fake_module = MagicMock()
    fake_module.CallbackHandler = fake_cls

    env = {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"}
    with patch.dict("os.environ", env, clear=False):
        with patch.dict("sys.modules", {"langfuse.langchain": fake_module}):
            fn = _get_setup_langfuse()
            result = fn()

    assert result is fake_handler


def test_audit_node_logs_claims_extracted(caplog):
    import logging
    from unittest.mock import patch as _patch

    fake_claims = [
        {"claim": "Buy now!", "type": "pricing_claim", "timestamp": None},
        {"claim": "Best price!", "type": "general", "timestamp": None},
        {"claim": "Cure guaranteed", "type": "health_claim", "timestamp": None},
    ]
    fake_chunk = MagicMock()
    fake_chunk.chunk_id = "c1"
    fake_chunk.score = 0.9
    fake_chunk.source = "yt-policy"
    fake_chunk.content = "no misleading claims"

    with _patch("src.pipeline.nodes._extract_claims", return_value=fake_claims), \
         _patch("src.pipeline.nodes._retrieve_for_claims", return_value=[]), \
         caplog.at_level(logging.INFO, logger="brand-guardian"):

        from src.pipeline.nodes import audit_content_node
        audit_content_node({
            "transcript": "Buy now! Best price! Cure guaranteed.",
            "ocr_text": [],
            "video_metadata": {},
            "ingestion_source": "metadata",
            "platforms": ["youtube"],
        })

    assert any("claims_extracted=3" in r.message for r in caplog.records)


def test_langfuse_public_key_in_env_example():
    content = Path("env.example").read_text()
    assert "LANGFUSE_PUBLIC_KEY" in content


def test_langfuse_secret_key_in_env_example():
    content = Path("env.example").read_text()
    assert "LANGFUSE_SECRET_KEY" in content
