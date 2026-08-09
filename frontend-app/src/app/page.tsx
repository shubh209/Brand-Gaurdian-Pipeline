"use client";

import { useEffect, useState } from "react";
import { getDashboardStats, getAudits, DashboardStats, AuditSummary } from "@/lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [audits, setAudits] = useState<AuditSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboardStats().then(setStats).catch((e) => setError(e.message));
    getAudits(1, 10).then((r) => setAudits(r.data)).catch((e) => setError(e.message));
  }, []);

  return (
    <main className="max-w-screen-xl mx-auto px-4 py-16">
      {/* Hero */}
      <div className="mb-8 grid grid-cols-1 lg:grid-cols-12 gap-0">
        <div className="lg:col-span-7">
          <span className="font-mono text-xs uppercase tracking-widest text-neutral-500">Dashboard</span>
          <h1 className="font-serif font-black text-5xl lg:text-7xl leading-[0.9] tracking-tighter mt-2">
            Compliance<br />Dashboard
          </h1>
        </div>
        <div className="lg:col-span-5 flex flex-col justify-end lg:text-right mt-4 lg:mt-0">
          <p className="font-body text-sm text-neutral-600 leading-relaxed max-w-sm lg:ml-auto">
            Pre-publication video ad compliance scanning. Check your ads against live platform policies before you publish.
          </p>
          <div className="mt-4">
            <a
              href="/audit/new"
              className="inline-block bg-ink text-bg px-6 py-3 font-mono text-xs uppercase tracking-widest hover:bg-white hover:text-ink border-2 border-ink transition-all"
            >
              Run New Audit
            </a>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="border-2 border-accent p-4 mb-6 font-mono text-xs text-accent">
          API Error: {error}
        </div>
      )}

      {/* Stats Row */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 border border-ink">
          <Stat label="Total Audits" value={String(stats.total_audits)} />
          <Stat label="Pass Rate" value={`${stats.pass_rate}%`} />
          <Stat label="Violations Found" value={String(stats.violation_count)} accent />
          <Stat label="Avg. Time" value={`${stats.avg_time_seconds}s`} />
        </div>
      )}

      {/* Recent Audits */}
      <div className="mt-8 border border-ink">
        <div className="bg-ink text-bg px-4 py-2 font-mono text-xs uppercase tracking-widest">
          Recent Audits
        </div>
        <table className="w-full text-sm font-sans">
          <thead className="border-b border-ink">
            <tr className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
              <th className="text-left px-4 py-2">Date</th>
              <th className="text-left px-4 py-2">Video</th>
              <th className="text-left px-4 py-2">Platform</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-left px-4 py-2">Violations</th>
            </tr>
          </thead>
          <tbody>
            {audits.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-neutral-500 font-mono text-xs">
                  No audits yet. Run your first audit to see results here.
                </td>
              </tr>
            )}
            {audits.map((a) => (
              <tr key={a.id} className="border-b border-neutral-200 hover:bg-neutral-100 transition-colors">
                <td className="px-4 py-3 font-mono text-xs">
                  {new Date(a.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 truncate max-w-[200px]">{a.video_url}</td>
                <td className="px-4 py-3 font-mono text-xs uppercase">{a.platforms || "youtube"}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={a.final_status} />
                </td>
                <td className="px-4 py-3 font-mono">{a.violation_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="p-6 border-r border-b lg:border-b-0 border-ink last:border-r-0">
      <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">{label}</span>
      <p className={`font-serif font-black text-4xl mt-1 ${accent ? "text-accent" : ""}`}>{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isFail = status === "FAIL";
  return (
    <span
      className={`px-2 py-0.5 text-xs font-mono uppercase ${
        isFail ? "bg-accent text-white" : "border border-ink"
      }`}
    >
      {status}
    </span>
  );
}
