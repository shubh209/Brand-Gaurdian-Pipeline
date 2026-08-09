# Spec: Frontend Pages + Deployment

## Context

Backend API is complete with all endpoints typed. Next.js scaffold exists with a working Dashboard page. This spec covers building the remaining pages and deploying.

## What exists

- `frontend-app/` — Next.js 14, TypeScript, Tailwind with Newsprint design tokens
- `frontend-app/src/app/page.tsx` — Dashboard page (calls `/dashboard/stats` + `/audits`)
- `frontend-app/src/lib/api.ts` — Typed fetch client
- `frontend/prototype.html` — Visual reference for all page designs
- Backend endpoints: `/dashboard/stats`, `/audits`, `/audits/{id}`, `/audits/{id}/stream`, `/uploads/presign`, `/uploads/{id}/start`, `/prompt/generate`

## Decisions locked

- Monorepo (frontend in `frontend-app/`)
- Tailwind + Newsprint design system (sharp corners, serif headlines, black borders, editorial red for severity)
- API target: deployed Azure Container App URL (configured in `.env.local`)
- No auth (AUTH_DISABLED=true on deployed backend)
- npm as package manager
- Vercel or Cloudflare Pages for frontend hosting (user decides at deploy time)

## Pages to build

### 1. New Audit page (`/audit/new`)

**What it does:** User uploads video or pastes URL → watches real-time progress → gets redirected to result.

**UI (from prototype Section III):**
- Upload zone (drag-drop + click)
- OR YouTube URL input with "Audit" button
- Platform checkboxes (YouTube checked by default, Meta, TikTok, X)
- Email field (optional)
- Pipeline progress bar with stage labels (Transcribing → Analyzing → Auditing → Done)

**Data flow:**
1. User drops file → `POST /uploads/presign` → get `upload_url` + `audit_id`
2. `PUT upload_url` (XHR with onprogress, shows 0-50%)
3. `POST /uploads/{audit_id}/start` with platforms
4. Open EventSource on `GET /audits/{audit_id}/stream`
5. SSE events update progress bar (50-100%)
6. On `complete` event → redirect to `/audit/{audit_id}`

**Edge cases:**
- File too large (>500MB) → show error before upload
- Duration too long (>60s) → check via `<video>` element before upload
- SSE timeout (5 min) → show "still processing, check back later"
- Upload failure → show error, allow retry

### 2. Audit Result page (`/audit/[id]`)

**What it does:** Shows full audit result — verdict, violations timeline, export buttons.

**UI (from prototype Section IV):**
- Verdict banner (PASS green / FAIL red with 4px border)
- Per-platform status row (PASS/FAIL per platform)
- Violations list — each violation shows: severity badge, timestamp (MM:SS), claim text, description, policy citation (indented), suggested rewrite (grey bg)
- Export buttons: Download PDF, Export CSV, Share Report

**Data flow:**
- `GET /audits/{id}` → renders all fields
- PDF download: `GET /audits/{id}/export?format=pdf` (opens in new tab)
- CSV: same with `format=csv`

### 3. Audit History page (`/history`)

**What it does:** Paginated list of all past audits with filters.

**UI (from prototype Section VII):**
- Filter buttons: All, Pass, Fail, YouTube, Meta, TikTok
- Card grid (3 columns desktop, 1 mobile) — each card shows date, title, status badge, violation count, platform tags
- Hard-shadow hover on cards
- Click → navigates to `/audit/{id}`
- Pagination at bottom (or infinite scroll)

**Data flow:**
- `GET /audits?page=1&per_page=20&status=FAIL&platform=youtube`
- Filter buttons update query params and re-fetch

### 4. Prompt Generator page (`/prompt`)

**What it does:** User enters ad brief → gets compliance-aware agent prompt to paste into their IDE.

**UI (from prototype Section V):**
- Left side: textarea for ad brief, platform select, AI tool select, output format select, model select, "Generate" button
- Right side: rendered prompt output (monospace, scrollable), "Copy" button, "Regenerate" button
- Below: "Based on X policy sources" indicator

**Data flow:**
- `POST /prompt/generate` with `{brief, platform, ai_tool, output_format, model}`
- Response: `{prompt, platform, ai_tool, policy_sources_used, tools_recommended}`
- "Copy" button: `navigator.clipboard.writeText(prompt)`

### 5. Deploy to hosting

**What it does:** Frontend accessible via a public URL.

**Steps:**
- Add `frontend-app/` to Vercel (or Cloudflare Pages)
- Set `NEXT_PUBLIC_API_URL` env var to the Azure Container App URL
- Configure CORS on backend to allow the new frontend origin
- Verify: dashboard loads, upload works end-to-end

## Non-goals (explicitly out of scope)

- Auth / login page
- Admin panel
- Policy Coverage page (static content, low priority)
- Integrations page (future, no backend support)
- Dark mode
- Mobile-native optimizations beyond responsive layout

## Skills for implementation

- `ponytail` — always active (minimum code)
- `prompt-master` — NOT needed (no new LLM prompts in frontend)
- No `/tdd` for frontend (React component tests are out of scope for now)

## Blocking edges

```
Page 1 (New Audit) → depends on nothing (endpoints exist)
Page 2 (Audit Result) → depends on nothing
Page 3 (History) → depends on nothing
Page 4 (Prompt Generator) → depends on nothing
Page 5 (Deploy) → depends on pages 1-4 being built
```

All pages are independent — can be built in any order. Deploy is last.
