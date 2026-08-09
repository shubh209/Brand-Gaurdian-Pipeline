"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getAuditDetail, getExportUrl, AuditDetail, ViolationOut } from "@/lib/api";

export default function AuditResultPage() {
  const { id } = useParams<{ id: string }>();
  const [audit, setAudit] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) {
      getAuditDetail(id).then(setAudit).catch((e) => setError(e.message));
    }
  }, [id]);

  if (error) {
    return (
      <main className="max-w-screen-xl mx-auto px-4 py-16">
        <div className="border-2 border-accent p-4 font-mono text-xs text-accent">
          Error loading audit: {error}
        </div>
      </main>
    );
  }

  if (!audit) {
    return (
      <main className="max-w-screen-xl mx-auto px-4 py-16">
        <p className="font-mono text-xs text-neutral-500 uppercase tracking-widest">Loading...</p>
      </main>
    );
  }

  const isFail = audit.final_status === "FAIL";
  const platformList = audit.platforms?.split(",").map((p) => p.trim()) || ["youtube"];

  return (
    <main className="max-w-screen-xl mx-auto px-4 py-16">
      {/* Header */}
      <div className="mb-8">
        <span className="font-mono text-xs uppercase tracking-widest text-neutral-500">Audit Report</span>
        <h1 className="font-serif font-black text-4xl lg:text-5xl leading-[0.9] tracking-tighter mt-2">
          Audit Report
        </h1>
      </div>

      {/* Verdict Banner */}
      <div
        className={`border-4 p-6 mb-8 flex items-center justify-between ${
          isFail ? "border-accent" : "border-green-700"
        }`}
      >
        <div>
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">Verdict</span>
          <p className={`font-serif font-black text-3xl mt-1 ${isFail ? "text-accent" : "text-green-700"}`}>
            {isFail ? "FAIL — Policy Violations Detected" : "PASS — No Violations"}
          </p>
        </div>
        <div className="text-right">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">Violations</span>
          <p className="font-serif font-black text-3xl mt-1">{audit.violations.length}</p>
        </div>
      </div>

      {/* Per-Platform Status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 border border-ink mb-8">
        {platformList.map((platform, i) => {
          // ponytail: no per-platform breakdown from backend yet, use overall status
          const platformFail = isFail;
          return (
            <div
              key={platform}
              className={`p-4 ${i < platformList.length - 1 ? "border-r border-ink" : ""} ${
                platformFail ? "bg-accent text-white" : ""
              }`}
            >
              <span
                className={`font-mono text-[10px] uppercase tracking-widest ${
                  platformFail ? "opacity-70" : "text-neutral-500"
                }`}
              >
                {platform}
              </span>
              <p className="font-mono font-bold text-lg mt-1">{platformFail ? "FAIL" : "PASS"}</p>
            </div>
          );
        })}
      </div>

      {/* Violations Timeline */}
      {audit.violations.length > 0 && (
        <div className="border border-ink">
          <div className="bg-ink text-bg px-4 py-2 font-mono text-xs uppercase tracking-widest flex justify-between">
            <span>Violations ({audit.violations.length})</span>
            <span className="truncate ml-4">{audit.video_url || audit.video_id}</span>
          </div>

          {audit.violations.map((v, i) => (
            <ViolationRow key={i} violation={v} isLast={i === audit.violations.length - 1} />
          ))}
        </div>
      )}

      {/* Final Report text (if no structured violations) */}
      {audit.violations.length === 0 && audit.final_report && (
        <div className="border border-ink p-6 mb-8">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-3">
            Report
          </span>
          <p className="font-body text-sm text-neutral-700 leading-relaxed whitespace-pre-wrap">
            {audit.final_report}
          </p>
        </div>
      )}

      {/* Export Row */}
      <div className="mt-6 flex gap-4 font-mono text-xs uppercase tracking-widest">
        <a
          href={getExportUrl(id, "pdf")}
          target="_blank"
          rel="noopener noreferrer"
          className="border border-ink px-4 py-2 hover:bg-ink hover:text-bg transition-all"
        >
          Download PDF
        </a>
        <a
          href={getExportUrl(id, "csv")}
          target="_blank"
          rel="noopener noreferrer"
          className="border border-ink px-4 py-2 hover:bg-ink hover:text-bg transition-all"
        >
          Export CSV
        </a>
        <button
          onClick={() => navigator.clipboard.writeText(window.location.href)}
          className="border border-ink px-4 py-2 hover:bg-ink hover:text-bg transition-all"
        >
          Share Report
        </button>
      </div>

      {/* Meta info */}
      <div className="mt-8 flex flex-wrap gap-6 font-mono text-[10px] uppercase tracking-widest text-neutral-400">
        <span>ID: {audit.id}</span>
        <span>Mode: {audit.audit_mode || "file"}</span>
        <span>Model: {audit.model_version || "gpt-4o"}</span>
        <span>Created: {new Date(audit.created_at).toLocaleString()}</span>
      </div>
    </main>
  );
}

function ViolationRow({ violation, isLast }: { violation: ViolationOut; isLast: boolean }) {
  const isCritical = violation.severity?.toLowerCase() === "critical";
  return (
    <div className={`p-6 ${!isLast ? "border-b border-ink" : ""} hover:bg-neutral-100 transition-colors`}>
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-16 text-center">
          <span
            className={`font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 inline-block ${
              isCritical ? "bg-accent text-white" : "border border-ink"
            }`}
          >
            {violation.severity || "Warning"}
          </span>
          <p className="font-mono text-xs text-neutral-500 mt-1">{violation.category}</p>
        </div>
        <div className="flex-1">
          <p className="font-body text-sm text-neutral-600 leading-relaxed">{violation.description}</p>

          {violation.citation_source && (
            <div className="mt-3 border-l-2 border-neutral-300 pl-3">
              <p className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">Policy Citation</p>
              <p className="font-body text-xs text-neutral-600 italic mt-0.5">
                {violation.citation_source}
                {violation.citation_excerpt && `: "${violation.citation_excerpt}"`}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
