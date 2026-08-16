"""
PolicyRetriever: unified retrieval module.
Interface: retrieve(claim, platforms, k=5) → list[PolicyChunk]

Handles query expansion (Phi-4-mini), embedding search (Azure AI Search),
platform filtering, and cross-encoder reranking behind one call.

Also provides retrieval_eval() for measuring retrieval quality independently.
"""
import logging
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

from src.config import config
from src.services.policy_store import RetrievedChunk, search_policy_chunks
from src.services.reranker import rerank
from src.tracing import observe, get_langchain_handler

logger = logging.getLogger("brand-guardian.retriever")


@dataclass
class PolicyChunk:
    """Unified chunk type returned by PolicyRetriever."""
    chunk_id: str
    source: str
    content: str
    score: float = 0.0
    platform: str | None = None


def _get_mini_llm():
    """Cheap model for query expansion. Phi-4-mini if configured, else GPT-4o."""
    phi_endpoint = config.PHI4_ENDPOINT
    phi_key = config.PHI4_API_KEY
    if phi_endpoint and phi_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="Phi-4-mini-instruct",
            base_url=phi_endpoint,
            api_key=phi_key,
            temperature=0.1,
            request_timeout=30,
        )
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        azure_deployment=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        openai_api_version=config.AZURE_OPENAI_API_VERSION,
        temperature=0.1,
        request_timeout=30,
    )


# ponytail: query expansion prompt — rewrite consumer language to policy terminology.
# Kept as a one-shot with 3 examples for pattern lock.
_EXPAND_PROMPT = (
    "Rewrite this advertising claim as regulatory/policy terminology for compliance search. "
    "Be concise, 1-2 phrases. Examples: "
    "'burns fat 3x faster' → 'unsubstantiated weight loss efficacy claim'; "
    "'only $29 today' → 'pricing claim urgency'; "
    "'#ad shown at end' → 'FTC disclosure placement'.\n"
    "Claim: {claim}"
)


_BATCH_EXPAND_PROMPT = (
    "Rewrite each advertising claim below into regulatory/policy terminology for compliance search. "
    "Be concise, 1-2 phrases per claim. Return a JSON array of expanded strings in the same order.\n"
    "Examples: 'burns fat 3x faster' → 'unsubstantiated weight loss efficacy claim'; "
    "'only $29 today' → 'pricing claim urgency'\n\n"
    "Claims:\n{claims_list}"
)


def _batch_expand_claims(claims: list[str]) -> dict[str, str]:
    """
    Expand all claims in one LLM call (instead of N sequential calls).
    ponytail: single round-trip. Falls back to original claims on any failure.
    """
    if not claims:
        return {}
    if len(claims) == 1:
        # Single claim — use the existing per-claim function
        return {claims[0]: _expand_claim(claims[0])}

    claims_list = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
    prompt = _BATCH_EXPAND_PROMPT.format(claims_list=claims_list)

    try:
        import json
        handler = get_langchain_handler()

        import signal
        def _timeout_handler(signum, frame):
            raise TimeoutError("batch_expand timed out")
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(30)  # 30s for batch (generous)
        try:
            response = _get_mini_llm().invoke(
                [HumanMessage(content=prompt)],
                config={"callbacks": [handler] if handler else []},
            )
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        # Parse JSON array response
        content = response.content.strip()
        if "```" in content:
            import re
            match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()
        expanded_list = json.loads(content)

        if isinstance(expanded_list, list) and len(expanded_list) == len(claims):
            return {claims[i]: expanded_list[i] for i in range(len(claims))}
        # Length mismatch — fallback
        return {c: c for c in claims}
    except Exception:
        # Fallback: use original claims without expansion
        return {c: c for c in claims}


@observe(name="expand_claim")
def _expand_claim(claim: str) -> str:
    """Rewrite consumer claim into policy terminology for better retrieval."""
    try:
        prompt = _EXPAND_PROMPT.format(claim=claim)
        handler = get_langchain_handler()
        # ponytail: 15s timeout per expansion call. If Phi-4-mini is cold, fallback to original claim.
        # Ceiling: loses query expansion on cold start. Upgrade path: batch all claims in one LLM call.
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("expand_claim timed out")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(15)
        try:
            result = _get_mini_llm().invoke(
                [HumanMessage(content=prompt)],
                config={"callbacks": [handler] if handler else []},
            ).content.strip()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return result
    except Exception:
        return claim  # fallback: use original


def _to_policy_chunk(rc: RetrievedChunk) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=rc.chunk_id,
        source=rc.source,
        content=rc.content,
        score=rc.score,
        platform=rc.platform,
    )


class PolicyRetriever:
    """
    Unified retrieval: expand → search → filter → rerank → return.
    """

    @observe(name="policy_retrieval")
    def retrieve(
        self,
        claim: str,
        platforms: list[str],
        k: int = 5,
    ) -> list[PolicyChunk]:
        """
        Retrieve policy chunks relevant to a claim, filtered by platforms.
        Returns up to k chunks after reranking.
        """
        if not claim.strip():
            return []

        expanded = _expand_claim(claim)
        logger.debug("Expanded '%s' → '%s'", claim[:60], expanded[:60])

        # Retrieve across all requested platforms, deduplicate
        seen: set[str] = set()
        all_chunks: list[RetrievedChunk] = []

        for platform in platforms:
            chunks = search_policy_chunks(expanded, platform=platform)
            for chunk in chunks:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    all_chunks.append(chunk)

        if not all_chunks:
            return []

        # Cross-encoder rerank
        reranked = rerank(claim, all_chunks, top_n=k)
        return [_to_policy_chunk(c) for c in reranked]

    def retrieve_batch(
        self,
        claims: list[str],
        platforms: list[str],
        k_per_claim: int = 5,
        skip_expansion: bool = False,
    ) -> dict[str, list[PolicyChunk]]:
        """
        Retrieve for multiple claims. Returns {claim: [chunks]}.
        Deduplicates across claims at the retrieval level.

        skip_expansion: if True, skip query expansion (faster, for eval --fast mode).
        """
        # Batch expand all claims in one LLM call (instead of N sequential calls)
        if skip_expansion:
            expanded_map = {c: c for c in claims}
        else:
            expanded_map = _batch_expand_claims(claims)

        results: dict[str, list[PolicyChunk]] = {}
        for claim in claims:
            expanded = expanded_map.get(claim, claim)
            results[claim] = self._retrieve_with_expanded(expanded, claim, platforms, k_per_claim)
        return results

    def _retrieve_with_expanded(
        self,
        expanded: str,
        original_claim: str,
        platforms: list[str],
        k: int,
    ) -> list[PolicyChunk]:
        """Retrieve using pre-expanded query."""
        if not expanded.strip():
            return []

        seen: set[str] = set()
        all_chunks: list[RetrievedChunk] = []

        for platform in platforms:
            chunks = search_policy_chunks(expanded, platform=platform)
            for chunk in chunks:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    all_chunks.append(chunk)

        if not all_chunks:
            return []

        reranked = rerank(original_claim, all_chunks, top_n=k)
        return [_to_policy_chunk(c) for c in reranked]

    def retrieval_eval(
        self,
        labeled_examples: list[dict],
    ) -> dict[str, float]:
        """
        Evaluate retrieval quality independently from reasoning.

        labeled_examples: [{"claim": str, "platforms": [str], "expected_chunk_ids": [str]}]

        Returns: {"recall": float, "precision": float}
        """
        total_recall = 0.0
        total_precision = 0.0
        n = len(labeled_examples)

        if n == 0:
            return {"recall": 0.0, "precision": 0.0}

        for example in labeled_examples:
            claim = example["claim"]
            platforms = example["platforms"]
            expected_ids = set(example["expected_chunk_ids"])

            retrieved = self.retrieve(claim, platforms, k=10)
            retrieved_ids = {c.chunk_id for c in retrieved}

            if expected_ids:
                recall = len(retrieved_ids & expected_ids) / len(expected_ids)
            else:
                recall = 1.0  # nothing to find

            if retrieved_ids:
                precision = len(retrieved_ids & expected_ids) / len(retrieved_ids)
            else:
                precision = 0.0 if expected_ids else 1.0

            total_recall += recall
            total_precision += precision

        return {
            "recall": total_recall / n,
            "precision": total_precision / n,
        }
