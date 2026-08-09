"use client";

import { useState } from "react";
import { generatePrompt, PromptGenerateResponse } from "@/lib/api";

const PLATFORMS = ["youtube", "meta", "tiktok", "x"] as const;
const AI_TOOLS = ["cursor", "chatgpt", "claude", "midjourney", "runway"] as const;
const OUTPUT_FORMATS = ["json", "markdown", "text"] as const;
const MODELS = ["gpt-4o", "claude-sonnet", "gpt-4o-mini"] as const;

export default function PromptPage() {
  const [brief, setBrief] = useState("");
  const [platform, setPlatform] = useState<string>("youtube");
  const [aiTool, setAiTool] = useState<string>("cursor");
  const [outputFormat, setOutputFormat] = useState<string>("json");
  const [model, setModel] = useState<string>("gpt-4o");

  const [result, setResult] = useState<PromptGenerateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleGenerate() {
    if (!brief.trim()) {
      setError("Enter an ad brief first.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await generatePrompt(brief, platform, aiTool, outputFormat, model);
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleCopy() {
    if (result) {
      navigator.clipboard.writeText(result.prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <main className="max-w-screen-xl mx-auto px-4 py-16">
      {/* Header */}
      <div className="mb-8">
        <span className="font-mono text-xs uppercase tracking-widest text-neutral-500">Prompt Generator</span>
        <h1 className="font-serif font-black text-4xl lg:text-5xl leading-[0.9] tracking-tighter mt-2">
          Compliance Prompt<br />Generator
        </h1>
        <p className="font-body text-sm text-neutral-600 mt-3 max-w-2xl leading-relaxed">
          Creating an ad with AI? Paste your brief below and get a compliance-aware prompt that avoids common policy violations before you generate.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="border-2 border-accent p-4 mb-6 font-mono text-xs text-accent">
          {error}
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border border-ink">
        {/* Input Side */}
        <div className="p-8 lg:border-r border-b lg:border-b-0 border-ink">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-3">
            Your Ad Brief
          </span>
          <textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            disabled={loading}
            placeholder="e.g. We're promoting a weight loss supplement called SlimFit. Target: women 25-45. Key benefit: fast results. Platform: YouTube pre-roll."
            className="w-full h-40 border-2 border-ink bg-transparent p-4 font-body text-sm focus:bg-[#F0F0F0] focus:outline-none resize-none disabled:opacity-50"
          />

          {/* Selects row */}
          <div className="mt-4 flex flex-wrap gap-3">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              disabled={loading}
              className="border-2 border-ink bg-transparent px-3 py-2 font-mono text-xs uppercase tracking-widest focus:outline-none disabled:opacity-50"
            >
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {p === "meta" ? "Meta / Facebook" : p === "x" ? "X (Twitter)" : p.charAt(0).toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>

            <select
              value={aiTool}
              onChange={(e) => setAiTool(e.target.value)}
              disabled={loading}
              className="border-2 border-ink bg-transparent px-3 py-2 font-mono text-xs uppercase tracking-widest focus:outline-none disabled:opacity-50"
            >
              {AI_TOOLS.map((t) => (
                <option key={t} value={t}>
                  {t === "chatgpt" ? "ChatGPT / GPT-4" : t.charAt(0).toUpperCase() + t.slice(1)}
                </option>
              ))}
            </select>

            <select
              value={outputFormat}
              onChange={(e) => setOutputFormat(e.target.value)}
              disabled={loading}
              className="border-2 border-ink bg-transparent px-3 py-2 font-mono text-xs uppercase tracking-widest focus:outline-none disabled:opacity-50"
            >
              {OUTPUT_FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f.toUpperCase()}
                </option>
              ))}
            </select>

            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={loading}
              className="border-2 border-ink bg-transparent px-3 py-2 font-mono text-xs uppercase tracking-widest focus:outline-none disabled:opacity-50"
            >
              {MODELS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleGenerate}
            disabled={loading}
            className="mt-4 bg-ink text-bg px-6 py-2 font-mono text-xs uppercase tracking-widest border-2 border-ink hover:bg-white hover:text-ink transition-all disabled:opacity-50"
          >
            {loading ? "Generating..." : "Generate"}
          </button>
        </div>

        {/* Output Side */}
        <div className="p-8 bg-neutral-100">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-3">
            Compliance-Aware Prompt
          </span>
          <div className="border-2 border-ink bg-bg p-4 h-40 overflow-y-auto">
            {result ? (
              <p className="font-mono text-xs leading-relaxed text-neutral-700 whitespace-pre-wrap">
                {result.prompt}
              </p>
            ) : (
              <p className="font-mono text-xs text-neutral-400">
                Your generated prompt will appear here...
              </p>
            )}
          </div>

          {result && (
            <>
              <div className="mt-3 flex gap-3">
                <button
                  onClick={handleCopy}
                  className="border border-ink px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest hover:bg-ink hover:text-bg transition-all"
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
                <button
                  onClick={handleGenerate}
                  disabled={loading}
                  className="border border-ink px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest hover:bg-ink hover:text-bg transition-all disabled:opacity-50"
                >
                  Regenerate
                </button>
              </div>
              <p className="font-mono text-[10px] text-neutral-400 mt-3 uppercase tracking-widest">
                Based on {result.policy_sources_used} policy sources
              </p>
              {result.tools_recommended.length > 0 && (
                <p className="font-mono text-[10px] text-neutral-400 mt-1 uppercase tracking-widest">
                  Recommended tools: {result.tools_recommended.join(", ")}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
