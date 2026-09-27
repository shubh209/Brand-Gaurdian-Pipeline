"""
Policy indexing: fetch live policy pages, chunk, and upload to Azure AI Search.
Falls back to local PDFs if all live fetches fail (offline/dev mode).
"""
import glob
import json as _json
import logging
import os
import uuid
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from src.db.models import PolicyVersion
from src.services.policy_fetcher import fetch_policy_source
from src.services.policy_sources import POLICY_SOURCES
from src.services.policy_store import get_vector_store

logger = logging.getLogger("brand-guardian")


def _content_to_documents(content: str, source_meta: dict) -> list:
    """Convert fetched content (JSON or markdown) into Document chunks."""
    docs = []
    try:
        data = _json.loads(content)
        prohibited = data.get("what_is_prohibited", [])
        allowed = data.get("what_is_allowed", [])
        category = data.get("category", "general")
        all_rules = prohibited + allowed
        if all_rules:
            for rule in all_rules:
                if rule.strip():
                    docs.append(Document(
                        page_content=rule.strip(),
                        metadata={**source_meta, "category": category, "rule_type": "prohibited" if rule in prohibited else "allowed"},
                    ))
            return docs
    except (_json.JSONDecodeError, TypeError, AttributeError):
        pass
    # Fallback: treat as markdown, return as single doc for splitter
    return [Document(page_content=content, metadata=source_meta)]


def _load_fallback_pdfs() -> list[Document]:
    """Load local PDFs as fallback when live fetch fails entirely."""
    from langchain_community.document_loaders import PyPDFLoader
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(current_dir, "..", "..", "data")
    pdf_files = glob.glob(os.path.join(data_folder, "*.pdf"))
    docs = []
    for pdf_path in pdf_files:
        raw = PyPDFLoader(pdf_path).load()
        for doc in raw:
            doc.metadata["platform"] = "youtube"  # legacy PDFs are YouTube policy
            doc.metadata["source"] = os.path.basename(pdf_path)
        docs.extend(raw)
    return docs


def run_policy_index(
    db: Session | None = None,
    platforms: list[str] | None = None,
    sources: list[dict] | None = None,
) -> dict:
    """
    Fetch policy sources, chunk, and upload to Azure AI Search.

    Args:
        db: SQLAlchemy session for recording PolicyVersion. Optional.
        platforms: Optional list to limit re-indexing to specific platforms.
        sources: Optional explicit list of source dicts (overrides POLICY_SOURCES + platforms).
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    all_splits: list[Document] = []
    failed_sources: list[str] = []

    active_sources = sources if sources is not None else POLICY_SOURCES
    if platforms:
        active_sources = [s for s in active_sources if s["platform"] in platforms]

    for source in active_sources:
        try:
            content = fetch_policy_source(source)
            source_meta = {
                "source": source["name"],
                "policy_name": source["name"],
                "source_id": source["id"],
                "platform": source["platform"],
                "url": source["url"],
            }
            base_docs = _content_to_documents(content, source_meta)
            # JSON-derived docs are already rule-granular; only split markdown docs
            splits = []
            for doc in base_docs:
                if len(doc.page_content) > 1100:
                    doc_splits = splitter.split_documents([doc])
                else:
                    doc_splits = [doc]
                for split in doc_splits:
                    split.metadata["chunk_id"] = str(uuid.uuid4())
                splits.extend(doc_splits)
            all_splits.extend(splits)
            logger.info("Indexed %s: %d chunks", source["id"], len(splits))
        except Exception as exc:
            logger.error("Failed to index %s: %s", source["id"], exc)
            failed_sources.append(source["id"])

    if not all_splits:
        # ponytail: full fallback to local PDFs when all live fetches fail
        logger.warning("All live fetches failed — falling back to local PDFs")
        fallback_docs = _load_fallback_pdfs()
        if not fallback_docs:
            raise RuntimeError("No policy content available: live fetch failed and no local PDFs found")
        splits = splitter.split_documents(fallback_docs)
        for split in splits:
            split.metadata.setdefault("chunk_id", str(uuid.uuid4()))
        all_splits = splits
        logger.info("Fallback PDF indexing: %d chunks", len(all_splits))

    # ponytail: strip NUL (0x00) bytes — Postgres text columns reject them (pgvector
    # store). PDF extraction can emit them (e.g. "e\x00ective"). Azure AI Search tolerated
    # them; Postgres does not. One guard at the write choke point covers every source.
    for split in all_splits:
        if "\x00" in split.page_content:
            split.page_content = split.page_content.replace("\x00", "")

    store = get_vector_store()

    # ponytail: wipe-and-replace — delete all existing docs before adding new ones.
    # Prevents embedding space mismatch when the OpenAI endpoint changes.
    # Upgrade path: versioned index namespacing (see FS-6 in IMPLEMENTATION_PLAN.md)
    #   when index size > 50K or per-audit version traceability is required.
    try:
        existing = store.similarity_search("policy", k=1000)
        if existing:
            ids_to_delete = [
                doc.metadata.get("chunk_id") or doc.metadata.get("id")
                for doc in existing
                if doc.metadata.get("chunk_id") or doc.metadata.get("id")
            ]
            if ids_to_delete:
                store.delete(ids_to_delete)
                logger.info("Wiped %d existing chunks before reindex", len(ids_to_delete))
    except Exception as exc:
        logger.warning("Could not wipe existing chunks: %s — proceeding with append", exc)

    store.add_documents(documents=all_splits)

    version_label = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    result = {
        "version_label": version_label,
        "chunk_count": len(all_splits),
        "policy_version_id": None,
        "failed_sources": failed_sources,
    }

    if db is not None:
        db.query(PolicyVersion).filter(PolicyVersion.is_current.is_(True)).update({"is_current": False})
        policy_version = PolicyVersion(
            version_label=version_label,
            chunk_count=len(all_splits),
            is_current=True,
        )
        db.add(policy_version)
        db.commit()
        db.refresh(policy_version)
        result["policy_version_id"] = str(policy_version.id)

    return result
