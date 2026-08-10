import json
import logging
import os
import re
from typing import Any, Dict

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.pipeline.state import VideoAuditState
from src.services.ingestion import HybridIngestionService
from src.services.policy_store import format_chunks_for_prompt, search_policy_chunks
from src.services.reranker import rerank
from src.services.video_indexer import YouTubeTranscriptService

logger = logging.getLogger("brand-guardian")
logging.basicConfig(level=logging.INFO)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"Missing required environment variable: {var_name}")
    return value


def _llm(temperature: float = 0.1) -> AzureChatOpenAI:
    # ponytail: new instance per call — cheap models are fast enough.
    # Upgrade to module singleton if latency becomes measurable.
    return AzureChatOpenAI(
        azure_deployment=_require_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        azure_endpoint=_require_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_require_env("AZURE_OPENAI_API_KEY"),
        openai_api_version=_require_env("AZURE_OPENAI_API_VERSION"),
        temperature=temperature,
        request_timeout=60,
    )


def _mini_llm(temperature: float = 0.1):
    """Return a cheap/fast model for extraction tasks.
    ponytail: uses Phi-4-mini on Azure AI Foundry if configured, falls back to GPT-4o.
    """
    phi_endpoint = os.getenv("PHI4_ENDPOINT")
    phi_key = os.getenv("PHI4_API_KEY")
    if phi_endpoint and phi_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="Phi-4-mini-instruct",
            base_url=phi_endpoint,
            api_key=phi_key,
            temperature=temperature,
            request_timeout=60,
        )
    deployment = os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT", "gpt-4o")
    return AzureChatOpenAI(
        azure_deployment=deployment,
        azure_endpoint=_require_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_require_env("AZURE_OPENAI_API_KEY"),
        openai_api_version=_require_env("AZURE_OPENAI_API_VERSION"),
        temperature=temperature,
        request_timeout=60,
    )


def _expand_claim(claim: str) -> str:
    """Rewrite consumer claim into policy terminology for better retrieval.
    ponytail: single mini LLM call per claim. No caching — claims are unique per video.
    """
    prompt = (
        "Rewrite this advertising claim as regulatory/policy terminology for compliance search. "
        "Be concise, 1-2 phrases. Examples: "
        "'burns fat 3x faster' → 'unsubstantiated weight loss efficacy claim'; "
        "'only $29 today' → 'pricing claim urgency'; "
        "'#ad shown at end' → 'FTC disclosure placement'.\n"
        f"Claim: {claim}"
    )
    try:
        return _mini_llm().invoke([HumanMessage(content=prompt)]).content.strip()
    except Exception:
        return claim  # fallback: use original claim


def _parse_json(content: str) -> dict:
    content = content.strip()
    if "```" in content:
        match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
        if match:
            content = match.group(1).strip()
    return json.loads(content)


# ── Stage 1: Claim extraction ────────────────────────────────────────────────

def _extract_claims(transcript: str, ocr_text: list[str]) -> list[dict]:
    """Extract discrete checkable claims from transcript + OCR via gpt-4o-mini."""
    prompt = (
        "Extract every distinct checkable claim from the transcript and on-screen text below.\n"
        "Return a JSON array of objects: [{\"claim\": str, \"type\": str, \"timestamp\": str|null}]\n"
        "Types: health_claim, pricing_claim, disclosure, product_claim, general\n"
        "Include disclosures (present or absent). Be exhaustive. No markdown fences.\n\n"
        f"TRANSCRIPT:\n{transcript}\n\nON-SCREEN TEXT:\n{' | '.join(ocr_text)}"
    )
    try:
        response = _mini_llm().invoke([HumanMessage(content=prompt)])
        return _parse_json(response.content)
    except Exception as exc:
        logger.warning("Claim extraction failed, using full transcript: %s", exc)
        return [{"claim": transcript[:500], "type": "general", "timestamp": None}]


# ── Stage 2: Per-claim retrieval + rerank ────────────────────────────────────

def _retrieve_for_claims(claims: list[dict], platforms: list[str]) -> list:
    """Retrieve and rerank policy chunks per claim, deduplicated across claims."""
    seen: set[str] = set()
    all_chunks = []

    # ponytail: sequential per-claim retrieval. Parallelise with asyncio.gather
    # if retrieval latency becomes the bottleneck at higher claim counts.
    for claim_obj in claims:
        claim_text = claim_obj.get("claim", "")
        if not claim_text:
            continue
        for platform in platforms:
            expanded = _expand_claim(claim_text)
            chunks = search_policy_chunks(expanded, platform=platform)
            reranked = rerank(claim_text, chunks, top_n=5)
            for chunk in reranked:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    all_chunks.append(chunk)

    return all_chunks


# ── Stage 3: Policy reasoning ─────────────────────────────────────────────────

def _reason_violations(
    claims: list[dict],
    chunks: list,
    metadata: dict,
    transcript: str,
    ocr_text: list[str],
    ingestion_source: str,
    platforms: list[str],
) -> dict:
    """Check claims against retrieved rules via gpt-4o. Returns raw audit_data dict."""
    retrieved_rules = format_chunks_for_prompt(chunks)
    confidence_note = ""
    if chunks:
        top_score = max(c.score for c in chunks)
        confidence_note = f"\nRetrieval confidence (top chunk): {top_score:.2f}"

    system_prompt = f"""You are a Senior Brand Compliance Auditor.

OFFICIAL REGULATORY RULES (CHUNK_ID | SOURCE | platform):
{retrieved_rules}{confidence_note}

TARGET PLATFORMS: {', '.join(platforms)}

INSTRUCTIONS:
Think step by step before producing JSON:
1. For each claim, identify the claim TYPE (health, pricing, disclosure, product, general).
2. Find the most relevant rule from the policy chunks above.
3. Determine if the claim violates that rule. Be specific about WHY.
4. Only flag a violation if you can name the exact rule that prohibits it.
5. After reasoning, produce the JSON output below. Do not include your reasoning in the JSON.

{{
    "compliance_results": [
        {{
            "category": str,
            "severity": "CRITICAL|WARNING|INFO",
            "description": str,
            "chunk_id": str,
            "citation_source": str,
            "citation_excerpt": str,
            "confidence": "high|medium|low",
            "platform": str,
            "timestamp": str|null
        }}
    ],
    "status": "PASS|FAIL",
    "final_report": str
}}

severity CRITICAL = must fix before publishing.
If no violations: status=PASS, compliance_results=[].
Do not include markdown fences or text outside the JSON.""".strip()

    user_message = (
        f"VIDEO TITLE: {metadata.get('title', 'Unknown')}\n"
        f"METADATA: {metadata}\n"
        f"TRANSCRIPT: {transcript}\n"
        f"ON-SCREEN TEXT: {ocr_text}\n"
        f"INGESTION SOURCE: {ingestion_source}\n\n"
        f"EXTRACTED CLAIMS:\n{json.dumps(claims, indent=2)}"
    )

    try:
        response = _llm(temperature=0.1).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])
        return _parse_json(response.content)
    except json.JSONDecodeError as exc:
        logger.error("Policy reasoning returned malformed JSON: %s", exc)
        return {"compliance_results": [], "status": "FAIL", "final_report": "Malformed LLM response."}
    except Exception:
        raise


# ── Stage 4: Report synthesis ─────────────────────────────────────────────────

def _synthesize_report(violations: list[dict], status: str) -> str:
    """Produce human-readable summary via gpt-4o-mini."""
    if not violations:
        return "No policy violations detected. The ad content passed all compliance checks."
    prompt = (
        f"Write a 2-3 sentence compliance summary for an ad reviewer.\n"
        f"Status: {status}. Violations: {json.dumps(violations[:10])}\n"
        "Be specific about the most critical issues. Plain text, no markdown."
    )
    try:
        response = _mini_llm().invoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as exc:
        logger.warning("Report synthesis failed: %s", exc)
        return f"{status}: {len(violations)} violation(s) detected."


# ── Citation attachment ───────────────────────────────────────────────────────

def _attach_citations(results: list[dict], chunks: list) -> list[dict]:
    chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
    enriched = []
    for item in results:
        row = dict(item)
        chunk_id = row.get("chunk_id")
        if chunk_id:
            if chunk_id in chunk_map:
                chunk = chunk_map[chunk_id]
                row.setdefault("citation_source", chunk.source)
                row.setdefault("citation_excerpt", chunk.content[:500])
            else:
                logger.warning("LLM cited non-existent chunk_id=%s — stripped", chunk_id)
                row["chunk_id"] = None
                row["citation_source"] = None
        # Derive risk_level from severity + retrieval confidence
        sev = row.get("severity", "INFO")
        score = chunk_map[row.get("chunk_id", "")].score if row.get("chunk_id") in chunk_map else 0.0
        row["risk_level"] = "HIGH" if sev == "CRITICAL" else "MEDIUM" if sev == "WARNING" and score > 0.02 else "LOW"
        enriched.append(row)
    return enriched


# ── LangGraph nodes ───────────────────────────────────────────────────────────

def index_video_node(state: VideoAuditState) -> Dict[str, Any]:
    video_url = state.get("video_url")
    logger.info("--- [Node: Indexer] Processing: %s ---", video_url)

    # ponytail: if transcript is pre-provided (upload/worker path), skip YouTube extraction
    if state.get("transcript"):
        logger.info("--- [Node: Indexer] Transcript pre-provided, skipping extraction ---")
        return {"ingestion_source": "upload"}

    try:
        if not video_url:
            raise ValueError("No video_url provided in state.")
        yt_service = YouTubeTranscriptService()
        clean_data = yt_service.extract_data(video_url)
        clean_data["ingestion_source"] = "metadata"
        return clean_data
    except Exception as exc:
        logger.error("Video Indexer Failed: %s", exc)
        return {
            "errors": [str(exc)],
            "final_status": "FAIL",
            "final_report": f"Video indexing failed: {exc}",
            "transcript": "",
            "ocr_text": [],
            "compliance_results": [],
        }


def enrich_content_node(state: VideoAuditState) -> Dict[str, Any]:
    video_url = state.get("video_url", "")
    base_transcript = state.get("transcript", "") or ""
    logger.info("--- [Node: Enrich] Hybrid ingestion for %s ---", video_url)
    if not video_url or not base_transcript:
        return {"ingestion_source": "none"}
    try:
        service = HybridIngestionService()
        enriched = service.enrich(video_url, base_transcript)
        logger.info("--- [Node: Enrich] Source=%s ---", enriched.get("ingestion_source"))
        return enriched
    except Exception as exc:
        logger.warning("Enrichment failed, using metadata only: %s", exc)
        return {"ingestion_source": "metadata"}


def audit_content_node(state: VideoAuditState) -> Dict[str, Any]:
    logger.info("--- [Node: Auditor] 4-stage pipeline ---")

    transcript = state.get("transcript", "")
    if not transcript:
        return {
            "final_status": "FAIL",
            "final_report": "Audit skipped: no content extracted from video.",
            "compliance_results": [],
        }

    ocr_text = state.get("ocr_text", [])
    metadata = state.get("video_metadata", {})
    ingestion_source = state.get("ingestion_source", "unknown")
    platforms = state.get("platforms") or ["youtube"]

    try:
        # Stage 1: extract claims
        logger.info("--- [Auditor] Stage 1: claim extraction ---")
        claims = _extract_claims(transcript, ocr_text)
        logger.info("--- [Auditor] Extracted %d claims ---", len(claims))
        logger.info("claims_extracted=%d", len(claims))

        # Stage 2: retrieve + rerank
        logger.info("--- [Auditor] Stage 2: retrieval + rerank ---")
        chunks = _retrieve_for_claims(claims, platforms)
        logger.info("--- [Auditor] %d unique chunks after dedup ---", len(chunks))
        logger.info("chunks_retrieved=%d retrieval_confidence_max=%.3f",
            len(chunks),
            max((c.score for c in chunks), default=0.0))

        if not chunks:
            return {
                "final_status": "PASS",
                "final_report": "No matching policy rules found for the extracted claims.",
                "compliance_results": [],
            }

        # Stage 3: reason
        logger.info("--- [Auditor] Stage 3: policy reasoning ---")
        audit_data = _reason_violations(
            claims, chunks, metadata, transcript, ocr_text, ingestion_source, platforms
        )

        violations = _attach_citations(audit_data.get("compliance_results", []), chunks)
        status = audit_data.get("status", "FAIL")

        # Stage 4: synthesize report
        final_report = _synthesize_report(violations, status)

        return {
            "compliance_results": violations,
            "final_status": status,
            "final_report": final_report,
        }

    except Exception as exc:
        logger.error("Auditor node failed: %s", exc)
        return {
            "errors": [str(exc)],
            "final_status": "FAIL",
            "final_report": f"Auditor node failed: {exc}",
            "compliance_results": [],
        }
