"""
Run the v2 golden dataset (104 cases) through ComplianceAuditor.
Measures per-category accuracy, false positive rate, and false negative rate.

Usage: PYTHONPATH=. uv run python evals/run_eval_v2.py
       PYTHONPATH=. uv run python evals/run_eval_v2.py --limit 5  # quick test

Output: evals/eval_results_v2.json
"""
import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.video_analyzer import AnalysisResult, TranscriptSegment
from src.services.compliance_auditor import ComplianceAuditor

logging.basicConfig(level=logging.WARNING)  # suppress noisy logs during eval
logger = logging.getLogger("eval-v2")
logger.setLevel(logging.INFO)

OUTPUT_PATH = "evals/eval_results_v2.json"


def _make_analysis(transcript: str) -> AnalysisResult:
    """Convert transcript text into AnalysisResult format."""
    sentences = [s.strip() for s in transcript.split(".") if s.strip()]
    segments = [
        TranscriptSegment(text=s + ".", start=float(i * 5), end=float(i * 5 + 4))
        for i, s in enumerate(sentences)
    ]
    return AnalysisResult(
        transcript_segments=segments,
        ocr_frames=[],
        visual_context=[],
        metadata={"source": "eval_v2"},
    )


def run_single(case: dict, auditor: ComplianceAuditor) -> dict:
    """Run one eval case and return scored result."""
    analysis = _make_analysis(case["transcript"])
    platforms = case.get("platforms", ["youtube"])

    start = time.time()
    try:
        report = auditor.audit(analysis, platforms)
        elapsed = time.time() - start

        actual_status = report.overall_status
        expected_status = case["expected_status"]
        min_violations = case.get("min_violations", 0)

        status_correct = actual_status == expected_status
        violations_met = len(report.violations) >= min_violations

        return {
            "id": case["id"],
            "name": case["name"],
            "category": case["category"],
            "expected_status": expected_status,
            "actual_status": actual_status,
            "status_correct": status_correct,
            "expected_min_violations": min_violations,
            "actual_violations": len(report.violations),
            "violations_met": violations_met,
            "pass": status_correct and violations_met,
            "elapsed_seconds": round(elapsed, 1),
            "violations": [
                {"severity": v.severity, "category": v.category, "claim": v.claim[:80]}
                for v in report.violations
            ],
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "name": case["name"],
            "category": case["category"],
            "expected_status": case["expected_status"],
            "actual_status": "ERROR",
            "status_correct": False,
            "pass": False,
            "elapsed_seconds": round(time.time() - start, 1),
            "violations": [],
            "error": str(exc),
        }


def main():
    parser = argparse.ArgumentParser(description="Run eval v2 golden dataset")
    parser.add_argument("--limit", type=int, default=None, help="Max cases to run")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    args = parser.parse_args()

    dataset_path = Path(__file__).parent / "golden_dataset_v2.json"
    with open(dataset_path) as f:
        dataset = json.load(f)

    if args.category:
        dataset = [d for d in dataset if d["category"] == args.category]
    if args.limit:
        dataset = dataset[:args.limit]

    logger.info("Running %d eval cases...\n", len(dataset))

    auditor = ComplianceAuditor()
    results = []

    for i, case in enumerate(dataset, 1):
        logger.info("[%d/%d] %s...", i, len(dataset), case["name"][:50])
        result = run_single(case, auditor)
        results.append(result)
        mark = "PASS" if result["pass"] else "FAIL"
        status_mark = "✓" if result["status_correct"] else "✗"
        logger.info("  %s %s (expected=%s, got=%s, violations=%d, %.1fs)",
                    mark, status_mark, result["expected_status"],
                    result["actual_status"], result.get("actual_violations", 0),
                    result["elapsed_seconds"])

    # ── Scoring ──────────────────────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    errors = sum(1 for r in results if r.get("error"))

    # Per-category breakdown
    cat_results = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        cat = r["category"]
        cat_results[cat]["total"] += 1
        if r["pass"]:
            cat_results[cat]["passed"] += 1

    # False positive rate (PASS cases incorrectly flagged as FAIL)
    pass_cases = [r for r in results if r["expected_status"] == "PASS"]
    false_positives = [r for r in pass_cases if r["actual_status"] == "FAIL"]
    fp_rate = len(false_positives) / len(pass_cases) if pass_cases else 0

    # False negative rate (FAIL cases incorrectly passed)
    fail_cases = [r for r in results if r["expected_status"] == "FAIL"]
    false_negatives = [r for r in fail_cases if r["actual_status"] == "PASS"]
    fn_rate = len(false_negatives) / len(fail_cases) if fail_cases else 0

    # ── Print summary ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  EVAL V2 RESULTS: {passed}/{total} ({100*passed/total:.1f}%)")
    print(f"{'='*60}")
    print(f"\n  False Positive Rate: {fp_rate*100:.1f}% ({len(false_positives)}/{len(pass_cases)} PASS cases flagged)")
    print(f"  False Negative Rate: {fn_rate*100:.1f}% ({len(false_negatives)}/{len(fail_cases)} FAIL cases missed)")
    print(f"  Errors: {errors}")

    print(f"\n  Per-Category Accuracy:")
    for cat, data in sorted(cat_results.items(), key=lambda x: x[1]["passed"]/max(x[1]["total"],1)):
        pct = 100 * data["passed"] / data["total"] if data["total"] else 0
        print(f"    {cat:<25} {data['passed']}/{data['total']} ({pct:.0f}%)")

    # ── Failures detail ──────────────────────────────────────────────────────
    failures = [r for r in results if not r["pass"]]
    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures[:20]:  # show first 20
            print(f"    [{f['category']}] {f['name'][:45]}")
            print(f"      Expected: {f['expected_status']} | Got: {f['actual_status']} | Violations: {f.get('actual_violations', '?')}")
            if f.get("error"):
                print(f"      Error: {f['error'][:80]}")

    # ── Save results ─────────────────────────────────────────────────────────
    output = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_cases": total,
        "passed": passed,
        "accuracy_pct": round(100 * passed / total, 1),
        "false_positive_rate": round(fp_rate, 3),
        "false_negative_rate": round(fn_rate, 3),
        "errors": errors,
        "per_category": {
            cat: {"total": d["total"], "passed": d["passed"], "accuracy_pct": round(100*d["passed"]/d["total"], 1)}
            for cat, d in cat_results.items()
        },
        "results": results,
    }

    Path(OUTPUT_PATH).parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
