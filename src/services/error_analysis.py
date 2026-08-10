"""
Operational error learning: detect patterns in pipeline failures, quality issues,
and retrieval gaps. Surfaces actionable insights for human decision-making.

Usage:
    from src.services.error_analysis import run_error_analysis
    report = run_error_analysis(db, days=30)
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Audit, AuditViolation, DeadLetterJob

logger = logging.getLogger("brand-guardian.error-analysis")

# ponytail: thresholds for flagging anomalies. Hardcoded for now.
# Upgrade path: make configurable via env vars or DB.
OVER_FLAGGING_THRESHOLD = 0.85  # category fails > 85% of the time → suspicious
LOW_CONFIDENCE_THRESHOLD = 0.5  # violations below this are uncertain
RETRIEVAL_LOW_COVERAGE_THRESHOLD = 5  # avg chunks below this → thin index


def run_error_analysis(db: Session, days: int = 30) -> dict:
    """
    Run full error analysis on recent audits.
    Returns structured report with pipeline failures, quality patterns, retrieval gaps.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    pipeline = _analyze_pipeline_failures(db, cutoff)
    quality = _analyze_quality_patterns(db, cutoff)
    retrieval = _analyze_retrieval_gaps(db, cutoff)

    total_audits = db.query(Audit).filter(Audit.created_at >= cutoff).count()

    return {
        "period": f"last_{days}_days",
        "total_audits": total_audits,
        "pipeline_failures": pipeline,
        "quality_patterns": quality,
        "retrieval_gaps": retrieval,
    }


def _analyze_pipeline_failures(db: Session, cutoff: datetime) -> dict:
    """Analyze dead-lettered jobs and failed audits."""
    dead_letters = (
        db.query(DeadLetterJob)
        .filter(DeadLetterJob.failed_at >= cutoff)
        .all()
    )

    total_audits = db.query(Audit).filter(Audit.created_at >= cutoff).count()
    failed_audits = (
        db.query(Audit)
        .filter(Audit.created_at >= cutoff, Audit.processing_status == "failed")
        .count()
    )

    # Categorize errors
    error_types: Counter = Counter()
    stage_failures: Counter = Counter()

    for dl in dead_letters:
        msg = dl.error_message.lower()
        if "timeout" in msg or "retryable" in msg:
            error_types["RetryableError"] += 1
        elif "permanent" in msg or "validation" in msg:
            error_types["PermanentError"] += 1
        else:
            error_types["UnexpectedError"] += 1

        # Try to identify which stage failed from the error message
        if "transcrib" in msg or "whisper" in msg:
            stage_failures["transcribing"] += 1
        elif "audit" in msg or "reasoning" in msg or "gpt" in msg:
            stage_failures["auditing"] += 1
        elif "retriev" in msg or "search" in msg:
            stage_failures["retrieval"] += 1
        else:
            stage_failures["unknown"] += 1

    rate = round(failed_audits / total_audits, 3) if total_audits > 0 else 0.0

    # Generate insights
    insights = []
    if rate > 0.1:
        insights.append(f"Failure rate is {rate*100:.1f}% — above 10% threshold")
    if stage_failures:
        top_stage = stage_failures.most_common(1)[0]
        if top_stage[1] > 1:
            insights.append(
                f"{top_stage[1]}/{len(dead_letters)} failures in '{top_stage[0]}' stage"
            )
    if error_types.get("RetryableError", 0) > error_types.get("PermanentError", 0):
        insights.append("Most failures are transient — may improve with longer timeouts or retry config")

    return {
        "total": failed_audits,
        "dead_lettered": len(dead_letters),
        "rate": rate,
        "by_error_type": dict(error_types),
        "by_stage": dict(stage_failures),
        "insights": insights,
    }


def _analyze_quality_patterns(db: Session, cutoff: datetime) -> dict:
    """Detect over-flagging, under-flagging, and low-confidence violations."""
    # Get all completed audits with their violations
    audits = (
        db.query(Audit)
        .filter(Audit.created_at >= cutoff, Audit.processing_status == "completed")
        .all()
    )

    if not audits:
        return {
            "category_fail_rates": {},
            "suspected_over_flagging": [],
            "suspected_under_flagging": [],
            "low_confidence_violations": {"count": 0, "pct": 0.0},
            "insights": ["No completed audits in period"],
        }

    # Category fail rates: how often does each violation category appear?
    all_violations = (
        db.query(AuditViolation)
        .join(Audit)
        .filter(Audit.created_at >= cutoff, Audit.processing_status == "completed")
        .all()
    )

    category_counts: Counter = Counter()
    total_violations = len(all_violations)

    for v in all_violations:
        category_counts[v.category] += 1

    # Fail rate per category: what % of audits trigger this category?
    completed_count = len(audits)
    category_fail_rates = {}
    for cat, count in category_counts.items():
        # How many unique audits have this category?
        audits_with_cat = (
            db.query(func.count(func.distinct(AuditViolation.audit_id)))
            .join(Audit)
            .filter(
                Audit.created_at >= cutoff,
                Audit.processing_status == "completed",
                AuditViolation.category == cat,
            )
            .scalar()
        )
        category_fail_rates[cat] = round(audits_with_cat / completed_count, 2) if completed_count else 0

    # Detect over-flagging (category appears in > THRESHOLD of all audits)
    suspected_over_flagging = [
        cat for cat, rate in category_fail_rates.items()
        if rate >= OVER_FLAGGING_THRESHOLD and category_counts[cat] >= 3
    ]

    # Detect under-flagging (platforms with 0 violations when others have many)
    platform_violation_counts: Counter = Counter()
    for audit in audits:
        platforms = (audit.platforms or "youtube").split(",")
        for p in platforms:
            p = p.strip()
            has_violations = audit.final_status == "FAIL"
            if has_violations:
                platform_violation_counts[p] += 1

    suspected_under_flagging = []
    if platform_violation_counts:
        max_count = max(platform_violation_counts.values())
        for p in ["youtube", "meta", "tiktok", "x"]:
            if platform_violation_counts.get(p, 0) == 0 and max_count > 3:
                suspected_under_flagging.append(p)

    # Low confidence violations (using severity as proxy since confidence isn't in DB)
    # ponytail: DB doesn't store confidence score. Use citation_excerpt being empty as proxy
    # for low-quality violations (no supporting evidence found).
    low_quality_violations = [v for v in all_violations if not v.citation_source]
    low_confidence_count = len(low_quality_violations)
    low_confidence_pct = round(low_confidence_count / total_violations, 2) if total_violations else 0.0

    # Insights
    insights = []
    if suspected_over_flagging:
        insights.append(
            f"Categories {suspected_over_flagging} appear in >{OVER_FLAGGING_THRESHOLD*100:.0f}% of audits — possible over-flagging"
        )
    if suspected_under_flagging:
        insights.append(
            f"Platforms {suspected_under_flagging} have 0 violations while others have many — possible under-flagging or thin policy index"
        )
    if low_confidence_pct > 0.3:
        insights.append(
            f"{low_confidence_pct*100:.0f}% of violations have no citation source — quality concern"
        )

    return {
        "category_fail_rates": category_fail_rates,
        "suspected_over_flagging": suspected_over_flagging,
        "suspected_under_flagging": suspected_under_flagging,
        "low_confidence_violations": {"count": low_confidence_count, "pct": low_confidence_pct},
        "insights": insights,
    }


def _analyze_retrieval_gaps(db: Session, cutoff: datetime) -> dict:
    """Detect audits where retrieval found zero or few policy chunks."""
    # ponytail: chunk_count isn't stored per-audit in DB.
    # Use violation.chunk_id presence as proxy: if violations exist but chunk_id is null,
    # the retrieval didn't ground them properly.
    completed_audits = (
        db.query(Audit)
        .filter(Audit.created_at >= cutoff, Audit.processing_status == "completed")
        .all()
    )

    all_violations = (
        db.query(AuditViolation)
        .join(Audit)
        .filter(Audit.created_at >= cutoff, Audit.processing_status == "completed")
        .all()
    )

    # Audits with PASS + 0 violations might indicate retrieval miss (nothing found to check against)
    zero_violation_fails = [
        a for a in completed_audits
        if a.final_status == "FAIL" and len(a.violations) == 0
    ]

    # Violations without chunk_id → retrieval didn't ground them
    ungrounded_violations = [v for v in all_violations if not v.chunk_id]
    ungrounded_pct = round(len(ungrounded_violations) / len(all_violations), 2) if all_violations else 0.0

    # Platform coverage: count violations per platform
    platform_chunks: Counter = Counter()
    platform_total: Counter = Counter()
    for v in all_violations:
        # Infer platform from the audit
        audit = v.audit
        platforms = (audit.platforms or "youtube").split(",")
        for p in platforms:
            p = p.strip()
            platform_total[p] += 1
            if v.chunk_id:
                platform_chunks[p] += 1

    platforms_with_low_coverage = []
    for p, total in platform_total.items():
        grounded = platform_chunks.get(p, 0)
        if total >= 3 and grounded / total < 0.5:
            platforms_with_low_coverage.append(p)

    # Insights
    insights = []
    if zero_violation_fails:
        insights.append(
            f"{len(zero_violation_fails)} audits marked FAIL but have 0 violations in DB — possible serialization gap"
        )
    if ungrounded_pct > 0.3:
        insights.append(
            f"{ungrounded_pct*100:.0f}% of violations have no chunk_id — retrieval may not be grounding them"
        )
    if platforms_with_low_coverage:
        insights.append(
            f"Platforms {platforms_with_low_coverage} have <50% grounded violations — index may be thin"
        )

    return {
        "zero_violation_fail_audits": len(zero_violation_fails),
        "ungrounded_violations": {"count": len(ungrounded_violations), "pct": ungrounded_pct},
        "platforms_with_low_coverage": platforms_with_low_coverage,
        "insights": insights,
    }


def push_to_langfuse(report: dict) -> None:
    """Push error analysis scores to Langfuse for time-series tracking."""
    try:
        from langfuse import Langfuse
        from src.config import config

        if not config.LANGFUSE_PUBLIC_KEY or not config.LANGFUSE_SECRET_KEY:
            return

        client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
        )

        # Push aggregate scores as a trace with scores
        trace = client.trace(
            name="error_analysis",
            metadata={
                "period": report["period"],
                "total_audits": report["total_audits"],
            },
            tags=["error-analysis", "operational"],
        )

        trace.score(name="pipeline_failure_rate", value=report["pipeline_failures"]["rate"])
        trace.score(
            name="low_confidence_pct",
            value=report["quality_patterns"]["low_confidence_violations"]["pct"],
        )
        trace.score(
            name="ungrounded_violation_pct",
            value=report["retrieval_gaps"]["ungrounded_violations"]["pct"],
        )
        trace.score(
            name="over_flagging_categories",
            value=len(report["quality_patterns"]["suspected_over_flagging"]),
        )

        client.flush()
        logger.info("Pushed error analysis scores to Langfuse")

    except Exception as exc:
        logger.warning("Failed to push to Langfuse: %s", exc)
