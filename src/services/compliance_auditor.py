"""
ComplianceAuditor: per-timestamp reasoning with batching.
Interface: audit(analysis: AnalysisResult, platforms: list[str]) → AuditReport

Replaces audit_content_node monolith in nodes.py.
Pipeline: claim extraction WITH timestamps → per-claim retrieval → batched reasoning
with logprob confidence → rewrite generation → per-platform status.
"""
import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from src.config import config
from src.errors import RetryableError, PermanentError
from src.services.policy_retriever import PolicyRetriever, PolicyChunk
from src.services.video_analyzer import AnalysisResult
from src.tracing import get_langfuse_callbacks

logger = logging.getLogger("brand-guardian.auditor")


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Violation:
    claim: str
    timestamp: float | None
    severity: str  # CRITICAL, WARNING, INFO
    confidence: float  # 0.0-1.0 from logprobs
    citation: str
    suggested_rewrite: str
    platform: str
    chunk_id: str | None = None
    category: str = "general"
    description: str = ""


@dataclass
class AuditReport:
    overall_status: str  # PASS or FAIL
    per_platform: dict[str, str] = field(default_factory=dict)  # {platform: PASS|FAIL}
    violations: list[Violation] = field(default_factory=list)
    claim_count: int = 0
    chunk_count: int = 0


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _llm(temperature: float = 0.1) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        openai_api_version=config.AZURE_OPENAI_API_VERSION,
        temperature=temperature,
    )


def _mini_llm():
    """Cheap model for claim extraction."""
    phi_endpoint = config.PHI4_ENDPOINT
    phi_key = config.PHI4_API_KEY
    if phi_endpoint and phi_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="Phi-4-mini-instruct",
            base_url=phi_endpoint,
            api_key=phi_key,
            temperature=0.1,
        )
    return _llm(temperature=0.1)


def _parse_json(content: str) -> dict | list:
    content = content.strip()
    if "```" in content:
        match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
        if match:
            content = match.group(1).strip()
    return json.loads(content)


# ── Prompts (crafted per prompt-master: factual, concise, role-assigned) ──────

_CLAIM_EXTRACTION_PROMPT = """Extract every distinct checkable claim from this ad transcript.
For each claim, identify which transcript segment it came from by matching the text.

Return JSON array: [{{"claim": str, "type": str, "start": float|null, "end": float|null}}]
Types: health_claim, pricing_claim, disclosure, product_claim, testimonial, before_after, general
Include disclosures (present or absent). Be exhaustive.

TRANSCRIPT SEGMENTS:
{segments}

ON-SCREEN TEXT:
{ocr_text}"""

_REASONING_SYSTEM_PROMPT = """You are a Senior Brand Compliance Auditor at a Fortune 500 advertising firm.

POLICY RULES (authoritative — these are the actual platform rules):
{rules}

TARGET PLATFORMS: {platforms}

INSTRUCTIONS:
For each claim below, determine if it violates any of the policy rules above.
Think step by step:
1. Identify the claim TYPE (health, pricing, disclosure, product, testimonial, before_after, general).
2. Find the most relevant rule from the policy chunks.
3. Determine if the claim violates that rule. Be specific about WHY.
4. Only flag a violation if you can name the exact rule chunk that prohibits it.
5. For each violation, suggest a compliant rewrite of the original claim.

Return JSON (no markdown fences):
{{
  "violations": [
    {{
      "claim": str,
      "category": str,
      "severity": "CRITICAL|WARNING|INFO",
      "description": str,
      "chunk_id": str,
      "citation_excerpt": str,
      "suggested_rewrite": str,
      "platform": str
    }}
  ]
}}

severity CRITICAL = must fix before publishing. WARNING = should fix. INFO = best practice.
If no violations for these claims: {{"violations": []}}"""

_REASONING_USER_PROMPT = """CLAIMS TO EVALUATE:
{claims_json}

TIMESTAMPS: Claims include start/end times from the original video.
Reference these in your reasoning if relevant (e.g. disclosure timing)."""


# ── Core class ────────────────────────────────────────────────────────────────

class ComplianceAuditor:
    """
    Full audit pipeline: extract claims → retrieve policy → batch reasoning → report.
    """

    def __init__(self):
        self._retriever = PolicyRetriever()

    def audit(self, analysis: AnalysisResult, platforms: list[str]) -> AuditReport:
        """
        Run the full compliance audit on analyzed video content.
        Returns AuditReport with per-platform status and violations.
        """
        if not platforms:
            platforms = ["youtube"]

        # Stage 1: Extract claims with timestamps
        claims = self._extract_claims(analysis)
        logger.info("auditor_claims_extracted count=%d", len(claims))

        if not claims:
            return AuditReport(
                overall_status="PASS",
                per_platform={p: "PASS" for p in platforms},
                claim_count=0,
            )

        # Stage 2: Retrieve policy chunks per claim
        claim_texts = [c["claim"] for c in claims]
        retrieval_map = self._retriever.retrieve_batch(claim_texts, platforms)
        total_chunks = len({
            chunk.chunk_id
            for chunks in retrieval_map.values()
            for chunk in chunks
        })
        logger.info("auditor_chunks_retrieved total_unique=%d", total_chunks)

        if total_chunks == 0:
            return AuditReport(
                overall_status="PASS",
                per_platform={p: "PASS" for p in platforms},
                claim_count=len(claims),
                chunk_count=0,
            )

        # Stage 3: Batch claims by shared chunks and reason
        violations = self._batched_reasoning(claims, retrieval_map, platforms)
        logger.info("auditor_violations_found count=%d", len(violations))

        # Stage 4: Compute per-platform status
        per_platform = self._compute_platform_status(violations, platforms)
        overall = "FAIL" if any(s == "FAIL" for s in per_platform.values()) else "PASS"

        return AuditReport(
            overall_status=overall,
            per_platform=per_platform,
            violations=violations,
            claim_count=len(claims),
            chunk_count=total_chunks,
        )

    def _extract_claims(self, analysis: AnalysisResult) -> list[dict]:
        """Extract claims with timestamps from analysis result."""
        # Build segment text with timestamps for the LLM
        segments_text = "\n".join(
            f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}"
            for s in analysis.transcript_segments
        )
        ocr_text = " | ".join(f.text for f in analysis.ocr_frames) if analysis.ocr_frames else "(none)"

        if not segments_text and not ocr_text:
            return []

        prompt = _CLAIM_EXTRACTION_PROMPT.format(
            segments=segments_text or "(no transcript)",
            ocr_text=ocr_text,
        )

        try:
            response = _mini_llm().invoke(
                [HumanMessage(content=prompt)],
                config={"callbacks": get_langfuse_callbacks()},
            )
            claims = _parse_json(response.content)
            if isinstance(claims, list):
                return claims
            return claims.get("claims", [])
        except Exception as exc:
            logger.warning("Claim extraction failed: %s", exc)
            # Fallback: treat full transcript as one claim
            full_text = " ".join(s.text for s in analysis.transcript_segments)
            if full_text:
                return [{"claim": full_text[:500], "type": "general", "start": None, "end": None}]
            return []

    def _batched_reasoning(
        self,
        claims: list[dict],
        retrieval_map: dict[str, list[PolicyChunk]],
        platforms: list[str],
    ) -> list[Violation]:
        """
        Batch claims that share the same policy chunks into fewer GPT-4o calls.
        ponytail: O(n²) grouping by chunk overlap. Ceiling: >50 claims per video.
        Upgrade path: hash-based grouping or just send all claims in one call if <20.
        """
        # Group claims by their chunk set (claims sharing chunks go together)
        batches = self._group_by_chunks(claims, retrieval_map)
        all_violations: list[Violation] = []

        for batch_claims, batch_chunks in batches:
            violations = self._reason_batch(batch_claims, batch_chunks, platforms)
            all_violations.extend(violations)

        return all_violations

    def _group_by_chunks(
        self,
        claims: list[dict],
        retrieval_map: dict[str, list[PolicyChunk]],
    ) -> list[tuple[list[dict], list[PolicyChunk]]]:
        """
        Group claims that share retrieved chunks into batches.
        ponytail: simple greedy grouping — if any chunk overlaps, merge into same batch.
        """
        # If few claims, just send them all in one batch
        if len(claims) <= 8:
            all_chunks_deduped: dict[str, PolicyChunk] = {}
            for claim in claims:
                for chunk in retrieval_map.get(claim["claim"], []):
                    all_chunks_deduped[chunk.chunk_id] = chunk
            return [(claims, list(all_chunks_deduped.values()))]

        # For larger sets, group by chunk overlap
        # ponytail: greedy merge — assign each claim to first batch that shares a chunk
        batches: list[tuple[list[dict], dict[str, PolicyChunk]]] = []

        for claim in claims:
            claim_chunks = retrieval_map.get(claim["claim"], [])
            claim_chunk_ids = {c.chunk_id for c in claim_chunks}

            merged = False
            for batch_claims, batch_chunk_map in batches:
                batch_ids = set(batch_chunk_map.keys())
                if batch_ids & claim_chunk_ids:
                    batch_claims.append(claim)
                    for c in claim_chunks:
                        batch_chunk_map[c.chunk_id] = c
                    merged = True
                    break

            if not merged:
                chunk_map = {c.chunk_id: c for c in claim_chunks}
                batches.append(([claim], chunk_map))

        return [(bc, list(cm.values())) for bc, cm in batches]

    def _reason_batch(
        self,
        claims: list[dict],
        chunks: list[PolicyChunk],
        platforms: list[str],
    ) -> list[Violation]:
        """Run GPT-4o reasoning on a batch of claims against shared policy chunks."""
        rules_text = "\n\n".join(
            f"[CHUNK_ID: {c.chunk_id} | SOURCE: {c.source} | PLATFORM: {c.platform or 'generic'}]\n{c.content}"
            for c in chunks
        )

        system = _REASONING_SYSTEM_PROMPT.format(
            rules=rules_text,
            platforms=", ".join(platforms),
        )
        user = _REASONING_USER_PROMPT.format(
            claims_json=json.dumps(claims, indent=2),
        )

        try:
            response = _llm(temperature=0.1).invoke(
                [SystemMessage(content=system), HumanMessage(content=user)],
                logprobs=True,
                top_logprobs=5,
                config={"callbacks": get_langfuse_callbacks()},
            )

            # Extract confidence from logprobs
            confidence = self._extract_confidence(response)

            result = _parse_json(response.content)
            raw_violations = result.get("violations", []) if isinstance(result, dict) else result

        except json.JSONDecodeError as exc:
            logger.error("Reasoning returned malformed JSON: %s", exc)
            return []
        except Exception as exc:
            if "429" in str(exc) or "timeout" in str(exc).lower():
                raise RetryableError(f"GPT-4o reasoning failed (transient): {exc}") from exc
            logger.error("Reasoning failed: %s", exc)
            return []

        # Map violations back to claims with timestamps
        violations = []
        for v in raw_violations:
            # Find matching claim to get timestamp
            timestamp = self._match_timestamp(v.get("claim", ""), claims)

            violations.append(Violation(
                claim=v.get("claim", ""),
                timestamp=timestamp,
                severity=v.get("severity", "INFO"),
                confidence=confidence,
                citation=v.get("citation_excerpt", ""),
                suggested_rewrite=v.get("suggested_rewrite", ""),
                platform=v.get("platform", platforms[0] if platforms else "youtube"),
                chunk_id=v.get("chunk_id"),
                category=v.get("category", "general"),
                description=v.get("description", ""),
            ))

        return violations

    def _extract_confidence(self, response) -> float:
        """
        Extract confidence from logprobs on severity tokens.
        ponytail: uses average token probability across the response as a proxy.
        Ceiling: per-violation confidence requires parsing logprobs by position.
        Upgrade path: map each severity token position to its violation.
        """
        try:
            # LangChain response may have logprobs in response_metadata
            metadata = getattr(response, "response_metadata", {})
            logprobs_data = metadata.get("logprobs", {})
            content_logprobs = logprobs_data.get("content", [])

            if not content_logprobs:
                return 0.7  # default medium confidence

            # Average probability of tokens (exp of logprob)
            probs = []
            for token_info in content_logprobs:
                lp = token_info.get("logprob", 0)
                if lp is not None:
                    probs.append(math.exp(lp))

            if probs:
                return round(sum(probs) / len(probs), 3)
            return 0.7
        except Exception:
            return 0.7  # fallback

    def _match_timestamp(self, violation_claim: str, claims: list[dict]) -> float | None:
        """Match a violation back to its source claim to get the timestamp."""
        violation_lower = violation_claim.lower()
        for claim in claims:
            if claim.get("claim", "").lower() in violation_lower or violation_lower in claim.get("claim", "").lower():
                return claim.get("start")
        return None

    def _compute_platform_status(
        self,
        violations: list[Violation],
        platforms: list[str],
    ) -> dict[str, str]:
        """Each platform gets independent PASS/FAIL based on its violations."""
        status: dict[str, str] = {p: "PASS" for p in platforms}
        for v in violations:
            if v.severity in ("CRITICAL", "WARNING"):
                status[v.platform] = "FAIL"
        return status
