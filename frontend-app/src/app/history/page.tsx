"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAudits, AuditSummary, PaginatedAudits } from "@/lib/api";

const FILTERS = [
  { label: "All", status: undefined, platform: undefined },
  { label: "Pass", status: "PASS", platform: undefined },
  { label: "Fail", status: "FAIL", platform: undefined },
  { label: "YouTube", status: undefined, platform: "youtube" },
  { label: "Meta", status: undefined, platform: "meta" },
  { label: "TikTok", status: undefined, platform: "tiktok" },
] as const;

export default function HistoryPage() {
  const router = useRouter();
  const [activeFilter, setActiveFilter] = useState(0);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<PaginatedAudits | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const f = FILTERS[activeFilter];
    getAudits(page, 21, f.status, f.platform)
      .then(setResult)
      .catch((e) => setError(e.message));
  }, [activeFilter, page]);

  function handleFilter(i: number) {
    setActiveFilter(i);
    setPage(1);
  }

  const totalPages = result ? Math.ceil(result.total / 21) : 1;

  return (
    <main className="max-w-screen-xl mx-auto px-4 py-16">
      {/* Header */}
      <div className="mb-8">
        <span className="font-mono text-xs uppercase tracking-widest text-neutral-500">History</span>
        <h1 className="font-serif font-black text-4xl lg:text-5xl leading-[0.9] tracking-tighter mt-2">
          Audit History
        </h1>
      </div>

      {/* Error */}
      {error && (
        <div className="border-2 border-accent p-4 mb-6 font-mono text-xs text-accent">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 font-mono text-xs uppercase tracking-widest">
        {FILTERS.map((f, i) => (
          <button
            key={f.label}
            onClick={() => handleFilter(i)}
            className={`px-3 py-1.5 transition-all ${
              i === activeFilter
                ? "bg-ink text-bg"
                : "border border-ink hover:bg-ink hover:text-bg"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Card Grid */}
      {result && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 border-t border-l border-ink">
          {result.data.map((audit) => (
            <AuditCard key={audit.id} audit={audit} onClick={() => router.push(`/audit/${audit.id}`)} />
          ))}
          {result.data.length === 0 && (
            <div className="col-span-full border-r border-b border-ink p-12 text-center">
              <p className="font-mono text-xs text-neutral-500 uppercase tracking-widest">
                No audits found
              </p>
            </div>
          )}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-4 font-mono text-xs uppercase tracking-widest">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="border border-ink px-3 py-1.5 hover:bg-ink hover:text-bg transition-all disabled:opacity-30"
          >
            Prev
          </button>
          <span className="text-neutral-500">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="border border-ink px-3 py-1.5 hover:bg-ink hover:text-bg transition-all disabled:opacity-30"
          >
            Next
          </button>
        </div>
      )}
    </main>
  );
}

function AuditCard({ audit, onClick }: { audit: AuditSummary; onClick: () => void }) {
  const isFail = audit.final_status === "FAIL";
  const platforms = audit.platforms?.split(",").map((p) => p.trim()) || ["youtube"];

  return (
    <div
      onClick={onClick}
      className="border-r border-b border-ink p-6 hover:bg-neutral-100 transition-all cursor-pointer hard-shadow-hover"
    >
      <div className="flex justify-between items-start mb-3">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
          {new Date(audit.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
        <span
          className={`px-2 py-0.5 text-[10px] font-mono uppercase ${
            isFail ? "bg-accent text-white" : "border border-ink"
          }`}
        >
          {audit.final_status || "Pending"}
        </span>
      </div>
      <p className="font-serif font-bold text-lg mb-2 truncate">
        {audit.video_url || `Audit ${audit.id.slice(0, 8)}`}
      </p>
      <p className="font-body text-sm text-neutral-600">
        {audit.violation_count} violation{audit.violation_count !== 1 ? "s" : ""} detected
      </p>
      <div className="mt-3 flex gap-2 flex-wrap">
        {platforms.map((p) => (
          <span key={p} className="font-mono text-[10px] uppercase tracking-widest bg-neutral-100 px-2 py-0.5">
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}
