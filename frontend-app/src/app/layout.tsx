import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brand Guardian — Ad Compliance Auditor",
  description: "Pre-publication video ad compliance scanning.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">
        {/* Nav */}
        <header className="sticky top-0 z-40 bg-bg border-b-2 border-ink">
          <div className="max-w-screen-xl mx-auto px-4 flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <span className="font-serif font-black text-xl tracking-tight">Brand Guardian</span>
              <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 hidden sm:inline">
                Ad Compliance Auditor
              </span>
            </div>
            <nav className="hidden md:flex items-center gap-6 font-mono text-xs uppercase tracking-widest">
              <a href="/" className="hover:text-accent transition-colors">Dashboard</a>
              <a href="/audit/new" className="hover:text-accent transition-colors">New Audit</a>
              <a href="/history" className="hover:text-accent transition-colors">History</a>
              <a href="/prompt" className="hover:text-accent transition-colors">Prompt</a>
            </nav>
            <div className="font-mono text-[10px] text-neutral-500 uppercase tracking-widest">
              Vol. 2 | Jul 2026
            </div>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
