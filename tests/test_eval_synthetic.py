"""
Synthetic transcript eval: run crafted transcripts through ComplianceAuditor.
These tests require real LLM calls (Azure OpenAI / Phi-4-mini) and are NOT for CI.
Run manually: PYTHONPATH=. uv run pytest tests/test_eval_synthetic.py -v -s

ponytail: 4 synthetic fixtures. Output saved to evals/synthetic_results.json.
"""
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from src.services.video_analyzer import AnalysisResult, TranscriptSegment
from src.services.compliance_auditor import ComplianceAuditor, AuditReport

# Skip if LLM env vars not configured (CI-safe)
pytestmark = pytest.mark.skipif(
    not os.getenv("AZURE_OPENAI_API_KEY"),
    reason="LLM env vars not configured (skip in CI)",
)

OUTPUT_PATH = "evals/synthetic_results.json"
RESULTS: list[dict] = []


def _make_analysis(transcript_text: str) -> AnalysisResult:
    """Create an AnalysisResult from a single transcript string."""
    # Split by sentences, assign timestamps 5s apart
    sentences = [s.strip() for s in transcript_text.split(".") if s.strip()]
    segments = []
    for i, sentence in enumerate(sentences):
        segments.append(TranscriptSegment(
            text=sentence + ".",
            start=float(i * 5),
            end=float(i * 5 + 4),
        ))
    return AnalysisResult(
        transcript_segments=segments,
        ocr_frames=[],
        visual_context=[],
        metadata={"source": "synthetic"},
    )


def _run_audit(name: str, transcript: str, platforms: list[str], expected_status: str, min_violations: int = 0):
    """Run a synthetic transcript through the auditor and record results."""
    analysis = _make_analysis(transcript)
    auditor = ComplianceAuditor()

    start = time.time()
    report = auditor.audit(analysis, platforms)
    elapsed = time.time() - start

    result = {
        "name": name,
        "expected_status": expected_status,
        "actual_status": report.overall_status,
        "match": report.overall_status == expected_status,
        "violation_count": len(report.violations),
        "min_violations_expected": min_violations,
        "violations_met": len(report.violations) >= min_violations,
        "elapsed_seconds": round(elapsed, 1),
        "violations": [
            {
                "severity": v.severity,
                "category": v.category,
                "claim": v.claim[:80],
                "confidence": v.confidence,
            }
            for v in report.violations
        ],
    }
    RESULTS.append(result)
    return report, result


# ── Fixture 1: Clear violation (unsubstantiated health claim) ────────────────

def test_clear_violation_health_claim():
    """Obvious FTC violation — should be flagged as FAIL with CRITICAL severity."""
    transcript = (
        "Hi everyone. I lost 30 pounds in just 2 weeks using SlimFit Pro. "
        "It literally melts fat while you sleep. No exercise needed, no diet changes. "
        "Just take two pills before bed and watch the weight disappear. "
        "Use code SLIM50 for 50 percent off today only."
    )
    report, result = _run_audit(
        name="clear_violation_health_claim",
        transcript=transcript,
        platforms=["youtube"],
        expected_status="FAIL",
        min_violations=2,
    )
    assert result["match"], f"Expected FAIL, got {report.overall_status}"
    assert result["violations_met"], f"Expected ≥2 violations, got {len(report.violations)}"


# ── Fixture 2: Borderline (hedged language) ──────────────────────────────────

def test_borderline_hedged_language():
    """Hedged claims — system may flag as WARNING or pass. Either is acceptable."""
    transcript = (
        "Many of our customers report feeling more energetic after using EnergyPlus. "
        "Individual results may vary. This product is not intended to diagnose, treat, "
        "cure or prevent any disease. Consult your doctor before starting any supplement. "
        "Join thousands who have already tried it."
    )
    report, result = _run_audit(
        name="borderline_hedged_language",
        transcript=transcript,
        platforms=["youtube"],
        expected_status="PASS",  # hedged enough to pass
    )
    # Borderline — we accept both PASS and FAIL with WARNING-only violations
    if report.overall_status == "FAIL":
        # If it fails, should only be warnings, not criticals
        criticals = [v for v in report.violations if v.severity == "CRITICAL"]
        assert len(criticals) == 0, f"Hedged language shouldn't trigger CRITICAL, got {len(criticals)}"
        result["match"] = True  # acceptable outcome


# ── Fixture 3: Clean ad (no violations) ──────────────────────────────────────

def test_clean_ad_no_violations():
    """Clearly compliant ad — should PASS with 0 violations."""
    transcript = (
        "Introducing our new daily moisturizer, developed with dermatologists. "
        "Clinically tested for sensitive skin. Available at major retailers nationwide. "
        "Visit our website for more information. Neutrogena, recommended by dermatologists."
    )
    report, result = _run_audit(
        name="clean_ad_no_violations",
        transcript=transcript,
        platforms=["youtube"],
        expected_status="PASS",
    )
    assert result["match"], f"Expected PASS for clean ad, got {report.overall_status}"


# ── Fixture 4: Multi-platform (financial claim) ──────────────────────────────

def test_financial_claim_multi_platform():
    """Guaranteed returns claim — should fail on both YouTube and TikTok."""
    transcript = (
        "Invest in CryptoWealth AI and earn guaranteed 500 percent returns in 30 days. "
        "Zero risk, our AI trading bot never loses. "
        "Join now before this opportunity disappears forever. "
        "No experience needed, just deposit and watch your money grow."
    )
    report, result = _run_audit(
        name="financial_claim_multi_platform",
        transcript=transcript,
        platforms=["youtube", "tiktok"],
        expected_status="FAIL",
        min_violations=2,
    )
    assert result["match"], f"Expected FAIL for guaranteed returns, got {report.overall_status}"
    assert result["violations_met"], f"Expected ≥2 violations, got {len(report.violations)}"


# ── Save results after all tests ─────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="module")
def save_results():
    """Save all synthetic eval results to JSON after tests complete."""
    yield
    if RESULTS:
        passed = sum(1 for r in RESULTS if r["match"])
        total = len(RESULTS)
        summary = {
            "total": total,
            "passed": passed,
            "score_percent": round(passed / total * 100, 1) if total else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "results": RESULTS,
        }
        Path(OUTPUT_PATH).parent.mkdir(exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n\n=== SYNTHETIC EVAL: {passed}/{total} ({summary['score_percent']}%) ===")
        print(f"Results saved to {OUTPUT_PATH}")
