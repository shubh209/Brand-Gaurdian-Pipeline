"""E2E test: run full V2 pipeline on a real video file."""
import json
import time
from pathlib import Path

from src.services.video_analyzer import VideoAnalyzer, AnalyzerOptions
from src.services.compliance_auditor import ComplianceAuditor
from src.services.report_generator import ReportGenerator

VIDEO_PATH = "videos/videoplayback.mp4"
PLATFORMS = ["youtube"]
OUTPUT_PATH = "evals/e2e_result.json"


def main():
    print("=== E2E TEST: Full V2 Pipeline ===")
    start = time.time()

    print("[1/3] VideoAnalyzer (Groq Whisper)...")
    analyzer = VideoAnalyzer()
    analysis = analyzer.analyze(VIDEO_PATH, AnalyzerOptions(enable_visual=False))
    t1 = time.time()
    print(f"  {len(analysis.transcript_segments)} segments, {t1-start:.1f}s")

    print("[2/3] ComplianceAuditor...")
    auditor = ComplianceAuditor()
    report = auditor.audit(analysis, PLATFORMS)
    t2 = time.time()
    print(f"  Status={report.overall_status}, {len(report.violations)} violations, {t2-t1:.1f}s")

    print("[3/3] ReportGenerator...")
    gen = ReportGenerator()
    outputs = gen.generate(report, formats=["json", "pdf", "csv"])
    t3 = time.time()
    print(f"  JSON={len(outputs['json'])}B PDF={len(outputs['pdf'])}B CSV={len(outputs['csv'])}B, {t3-t2:.1f}s")

    total = t3 - start
    print(f"\nTOTAL: {total:.1f}s")
    print(f"Status: {report.overall_status}")
    print(f"Violations: {len(report.violations)}")

    for i, v in enumerate(report.violations, 1):
        ts = f"{int(v.timestamp)//60:02d}:{int(v.timestamp)%60:02d}" if v.timestamp else "--:--"
        print(f"  {i}. [{v.severity}] {v.category} @ {ts}: {v.claim[:60]}")

    criticals = [v for v in report.violations if v.severity == "CRITICAL"]
    if not criticals:
        print("\nPASS: No CRITICAL violations.")
    else:
        print(f"\nNOTE: {len(criticals)} CRITICAL found.")

    result = {
        "video": VIDEO_PATH,
        "platforms": PLATFORMS,
        "total_time_seconds": round(total, 1),
        "overall_status": report.overall_status,
        "per_platform": report.per_platform,
        "claim_count": report.claim_count,
        "chunk_count": report.chunk_count,
        "violation_count": len(report.violations),
        "violations": [
            {
                "severity": v.severity,
                "category": v.category,
                "claim": v.claim,
                "timestamp": v.timestamp,
                "confidence": v.confidence,
                "description": v.description,
                "citation": v.citation,
                "suggested_rewrite": v.suggested_rewrite,
                "platform": v.platform,
            }
            for v in report.violations
        ],
        "transcript_segments": [
            {"text": s.text, "start": s.start, "end": s.end}
            for s in analysis.transcript_segments
        ],
    }

    Path(OUTPUT_PATH).parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
