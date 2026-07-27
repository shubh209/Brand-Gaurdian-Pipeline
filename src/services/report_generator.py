"""
ReportGenerator: structured multi-format output.
Interface: generate(audit_report, formats) → dict[str, bytes]

Produces JSON (API), PDF (downloadable), CSV (exportable) from an AuditReport.
Each format includes per-platform breakdown, overall status, violations with
timestamps as MM:SS, confidence scores, suggested rewrites, and policy citations.
"""
import csv
import io
import json
from dataclasses import asdict

from src.services.compliance_auditor import AuditReport, Violation

DISCLAIMER = (
    "Decision support only. This audit does not constitute legal advice. "
    "A qualified reviewer must confirm findings before publishing ads."
)


def _format_timestamp(seconds: float | None) -> str:
    """Render seconds as MM:SS for human-readable formats."""
    if seconds is None:
        return "--:--"
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def _violation_to_dict(v: Violation) -> dict:
    return {
        "claim": v.claim,
        "timestamp": v.timestamp,
        "timestamp_display": _format_timestamp(v.timestamp),
        "severity": v.severity,
        "confidence": v.confidence,
        "category": v.category,
        "description": v.description,
        "citation": v.citation,
        "suggested_rewrite": v.suggested_rewrite,
        "platform": v.platform,
        "chunk_id": v.chunk_id,
    }


class ReportGenerator:
    """
    Generate structured reports from an AuditReport in multiple formats.
    """

    def generate(
        self,
        audit_report: AuditReport,
        formats: list[str] | None = None,
    ) -> dict[str, bytes]:
        """
        Generate report in requested formats.
        Returns {format_name: bytes_content}.
        Supported formats: "json", "pdf", "csv".
        """
        if formats is None:
            formats = ["json"]

        results: dict[str, bytes] = {}
        for fmt in formats:
            if fmt == "json":
                results["json"] = self._to_json(audit_report)
            elif fmt == "pdf":
                results["pdf"] = self._to_pdf(audit_report)
            elif fmt == "csv":
                results["csv"] = self._to_csv(audit_report)
        return results

    def _to_json(self, report: AuditReport) -> bytes:
        """Structured JSON matching API response schema."""
        data = {
            "overall_status": report.overall_status,
            "per_platform": report.per_platform,
            "claim_count": report.claim_count,
            "chunk_count": report.chunk_count,
            "violation_count": len(report.violations),
            "violations": [_violation_to_dict(v) for v in report.violations],
            "disclaimer": DISCLAIMER,
        }
        return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    def _to_pdf(self, report: AuditReport) -> bytes:
        """
        Plain-text PDF-style report with per-platform sections.
        ponytail: text-based, not actual PDF rendering (no reportlab dep).
        Ceiling: no styling/fonts. Upgrade path: add reportlab or weasyprint when needed.
        """
        lines = [
            "=" * 60,
            "BRAND GUARDIAN AI — COMPLIANCE AUDIT REPORT",
            "=" * 60,
            "",
            f"Overall Status: {report.overall_status}",
            f"Claims Analyzed: {report.claim_count}",
            f"Policy Chunks Retrieved: {report.chunk_count}",
            f"Violations Found: {len(report.violations)}",
            "",
        ]

        # Per-platform summary
        lines.append("─" * 40)
        lines.append("PLATFORM STATUS")
        lines.append("─" * 40)
        for platform, status in report.per_platform.items():
            indicator = "✓ PASS" if status == "PASS" else "✗ FAIL"
            lines.append(f"  {platform.upper()}: {indicator}")
        lines.append("")

        # Violations grouped by platform
        violations_by_platform: dict[str, list[Violation]] = {}
        for v in report.violations:
            violations_by_platform.setdefault(v.platform, []).append(v)

        for platform, violations in violations_by_platform.items():
            lines.append("─" * 40)
            lines.append(f"VIOLATIONS — {platform.upper()}")
            lines.append("─" * 40)
            for i, v in enumerate(violations, 1):
                ts = _format_timestamp(v.timestamp)
                lines.extend([
                    f"  {i}. [{v.severity}] {v.category} @ {ts}",
                    f"     Claim: {v.claim}",
                    f"     Issue: {v.description}",
                    f"     Confidence: {v.confidence:.0%}",
                    f"     Citation: {v.citation or 'n/a'}",
                    f"     Suggested rewrite: {v.suggested_rewrite or 'n/a'}",
                    "",
                ])

        if not report.violations:
            lines.append("No violations detected.")
            lines.append("")

        lines.extend(["", "─" * 40, DISCLAIMER])
        return "\n".join(lines).encode("utf-8")

    def _to_csv(self, report: AuditReport) -> bytes:
        """One row per violation with all fields."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        # Header
        writer.writerow([
            "platform", "severity", "category", "timestamp",
            "claim", "description", "confidence", "citation",
            "suggested_rewrite", "chunk_id",
        ])

        for v in report.violations:
            writer.writerow([
                v.platform,
                v.severity,
                v.category,
                _format_timestamp(v.timestamp),
                v.claim,
                v.description,
                f"{v.confidence:.2f}",
                v.citation,
                v.suggested_rewrite,
                v.chunk_id or "",
            ])

        # Summary row
        writer.writerow([])
        writer.writerow(["overall_status", report.overall_status])
        for platform, status in report.per_platform.items():
            writer.writerow([f"platform_status_{platform}", status])
        writer.writerow(["disclaimer", DISCLAIMER])

        return buffer.getvalue().encode("utf-8")
