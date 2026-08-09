"use client";

import { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { presignUpload, startAudit, getAuditStreamUrl, createAuditFromUrl } from "@/lib/api";

const STAGES = ["Transcribing", "Analyzing", "Auditing", "Done"] as const;
const MAX_FILE_SIZE = 500 * 1024 * 1024; // 500MB
const MAX_DURATION = 60; // seconds

type PipelineStage = (typeof STAGES)[number];

export default function NewAuditPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Form state
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [platforms, setPlatforms] = useState<Record<string, boolean>>({
    youtube: true,
    meta: false,
    tiktok: false,
    x: false,
  });
  const [email, setEmail] = useState("");

  // Progress state
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [pipelineStage, setPipelineStage] = useState<PipelineStage | null>(null);
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const selectedPlatforms = Object.entries(platforms)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const isProcessing = uploading || pipelineStage !== null;

  // ponytail: validate video duration client-side via <video> element
  function validateDuration(f: File): Promise<boolean> {
    return new Promise((resolve) => {
      const video = document.createElement("video");
      video.preload = "metadata";
      video.onloadedmetadata = () => {
        URL.revokeObjectURL(video.src);
        resolve(video.duration <= MAX_DURATION);
      };
      video.onerror = () => resolve(true); // can't check, let backend handle
      video.src = URL.createObjectURL(f);
    });
  }

  function handleFileDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  }

  function pickFile(f: File) {
    setError(null);
    if (f.size > MAX_FILE_SIZE) {
      setError("File exceeds 500MB limit.");
      return;
    }
    setFile(f);
    setUrl(""); // clear URL if file chosen
  }

  const startPipeline = useCallback(
    async (auditId: string) => {
      // Open SSE connection
      const es = new EventSource(getAuditStreamUrl(auditId));
      setPipelineStage("Transcribing");
      setPipelineProgress(50);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.status === "complete" || data.progress === 100) {
            setPipelineStage("Done");
            setPipelineProgress(100);
            es.close();
            setTimeout(() => router.push(`/audit/${auditId}`), 800);
          } else if (data.progress != null) {
            setPipelineProgress(50 + Math.round(data.progress / 2));
            // Map progress to stage
            if (data.progress < 33) setPipelineStage("Transcribing");
            else if (data.progress < 66) setPipelineStage("Analyzing");
            else setPipelineStage("Auditing");
          }
          if (data.status && data.status !== "complete") {
            const stageMap: Record<string, PipelineStage> = {
              transcribing: "Transcribing",
              analyzing: "Analyzing",
              auditing: "Auditing",
            };
            if (stageMap[data.status]) setPipelineStage(stageMap[data.status]);
          }
        } catch {
          // ignore malformed events
        }
      };

      es.onerror = () => {
        es.close();
        // ponytail: don't fake success — show connection lost and let user navigate manually
        setError("Connection lost. Your audit may still be processing.");
        setPipelineStage(null);
        setUploading(false);
      };

      // 5 min timeout
      setTimeout(() => {
        if (es.readyState !== EventSource.CLOSED) {
          es.close();
          setError("Still processing — check back later.");
          setPipelineStage(null);
        }
      }, 5 * 60 * 1000);
    },
    [router]
  );

  async function handleSubmit() {
    setError(null);

    if (!file && !url.trim()) {
      setError("Provide a video file or YouTube URL.");
      return;
    }
    if (selectedPlatforms.length === 0) {
      setError("Select at least one platform.");
      return;
    }

    try {
      if (file) {
        // Validate duration
        const durationOk = await validateDuration(file);
        if (!durationOk) {
          setError("Video exceeds 60 second limit.");
          return;
        }

        setUploading(true);

        // 1. Get presigned URL
        const { upload_url, audit_id } = await presignUpload(file.name, file.type || "video/mp4");

        // 2. Upload to blob storage with progress
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("PUT", upload_url);
          xhr.setRequestHeader("x-ms-blob-type", "BlockBlob");
          xhr.setRequestHeader("Content-Type", file.type || "video/mp4");
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
              setUploadProgress(Math.round((e.loaded / e.total) * 50));
            }
          };
          xhr.onload = () => (xhr.status < 400 ? resolve() : reject(new Error(`Upload failed: ${xhr.status}`)));
          xhr.onerror = () => reject(new Error("Upload failed"));
          xhr.send(file);
        });

        setUploading(false);
        setUploadProgress(50);

        // 3. Start processing
        await startAudit(audit_id, selectedPlatforms);

        // 4. SSE
        startPipeline(audit_id);
      } else {
        // URL mode — use typed API client
        setUploading(true);
        const data = await createAuditFromUrl(url.trim(), selectedPlatforms, email || undefined);
        const auditId = data.audit_id;
        setUploading(false);
        setUploadProgress(50);
        startPipeline(auditId);
      }
    } catch (err: unknown) {
      setUploading(false);
      setPipelineStage(null);
      setError(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  const currentStageIdx = pipelineStage ? STAGES.indexOf(pipelineStage) : -1;
  const progressPercent = pipelineStage ? pipelineProgress : uploadProgress;

  return (
    <main className="max-w-screen-xl mx-auto px-4 py-16">
      {/* Header */}
      <div className="mb-8">
        <span className="font-mono text-xs uppercase tracking-widest text-neutral-500">New Audit</span>
        <h1 className="font-serif font-black text-5xl lg:text-7xl leading-[0.9] tracking-tighter mt-2">
          Run New Audit
        </h1>
      </div>

      {/* Error */}
      {error && (
        <div className="border-2 border-accent p-4 mb-6 font-mono text-xs text-accent">
          {error}
          <button onClick={() => setError(null)} className="ml-4 underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Main form grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-0 border border-ink">
        {/* Left: Upload */}
        <div className="lg:col-span-8 p-8 lg:border-r border-b lg:border-b-0 border-ink">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-4">
            Upload Video
          </span>

          {/* Drop zone */}
          <div
            className={`border-2 border-dashed border-ink p-12 text-center cursor-pointer transition-colors ${
              file ? "bg-neutral-100" : "hover:bg-neutral-100"
            }`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleFileDrop}
          >
            {file ? (
              <>
                <p className="font-serif text-2xl mb-2">{file.name}</p>
                <p className="font-mono text-xs text-neutral-500 uppercase tracking-widest">
                  {(file.size / (1024 * 1024)).toFixed(1)} MB
                </p>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                  }}
                  className="mt-2 font-mono text-xs underline text-neutral-500"
                >
                  Remove
                </button>
              </>
            ) : (
              <>
                <p className="font-serif text-2xl mb-2">Drop video file here</p>
                <p className="font-mono text-xs text-neutral-500 uppercase tracking-widest">
                  MP4, MOV, AVI, WebM — max 60 seconds
                </p>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) pickFile(f);
              }}
            />
          </div>

          {/* URL input */}
          <div className="mt-6">
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-2">
              Or paste YouTube URL
            </span>
            <div className="flex gap-0">
              <input
                type="url"
                placeholder="https://youtu.be/..."
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  if (e.target.value) setFile(null);
                }}
                disabled={isProcessing}
                className="flex-1 border-2 border-ink bg-transparent px-4 py-3 font-mono text-sm focus:bg-[#F0F0F0] focus:outline-none disabled:opacity-50"
              />
              <button
                onClick={handleSubmit}
                disabled={isProcessing}
                className="bg-ink text-bg px-6 py-3 font-mono text-xs uppercase tracking-widest border-2 border-ink hover:bg-white hover:text-ink transition-all disabled:opacity-50"
              >
                {isProcessing ? "Processing..." : "Audit"}
              </button>
            </div>
          </div>
        </div>

        {/* Right: Options */}
        <div className="lg:col-span-4 p-8">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-4">
            Target Platforms
          </span>
          <div className="space-y-3">
            {[
              { key: "youtube", label: "YouTube" },
              { key: "meta", label: "Meta / Facebook" },
              { key: "tiktok", label: "TikTok" },
              { key: "x", label: "X (Twitter)" },
            ].map(({ key, label }) => (
              <label key={key} className="flex items-center gap-3 cursor-pointer hover:bg-neutral-100 p-2 -ml-2 transition-colors">
                <input
                  type="checkbox"
                  checked={platforms[key]}
                  onChange={(e) => setPlatforms((p) => ({ ...p, [key]: e.target.checked }))}
                  disabled={isProcessing}
                  className="w-4 h-4 accent-ink"
                />
                <span className="font-sans text-sm">{label}</span>
              </label>
            ))}
          </div>

          <div className="mt-8 pt-6 border-t border-ink">
            <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-2">
              Email report to
            </span>
            <input
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isProcessing}
              className="w-full border-b-2 border-ink bg-transparent px-3 py-2 font-mono text-sm focus:bg-[#F0F0F0] focus:outline-none disabled:opacity-50"
            />
          </div>

          {/* Submit button (for file upload mode) */}
          {file && (
            <button
              onClick={handleSubmit}
              disabled={isProcessing}
              className="mt-6 w-full bg-ink text-bg px-6 py-3 font-mono text-xs uppercase tracking-widest border-2 border-ink hover:bg-white hover:text-ink transition-all disabled:opacity-50"
            >
              {isProcessing ? "Processing..." : "Start Audit"}
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {isProcessing && (
        <div className="mt-8 border border-ink p-6">
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500 block mb-3">
            Pipeline Status
          </span>
          <div className="flex items-center gap-0 font-mono text-xs uppercase tracking-widest">
            {STAGES.map((stage, i) => (
              <span
                key={stage}
                className={`px-3 py-1 border border-ink ${
                  i <= currentStageIdx ? "bg-ink text-bg" : "text-neutral-400"
                } ${i > 0 ? "border-l-0" : ""}`}
              >
                {stage}
              </span>
            ))}
          </div>
          <div className="mt-3 h-1 bg-neutral-200">
            <div
              className="h-1 bg-ink transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          {uploading && (
            <p className="mt-2 font-mono text-xs text-neutral-500">
              Uploading... {uploadProgress}%
            </p>
          )}
        </div>
      )}
    </main>
  );
}
