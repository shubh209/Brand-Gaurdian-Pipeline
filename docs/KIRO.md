# Kiro-specific context for Brand Guardian AI

This file adds Kiro IDE-specific instructions on top of `AGENTS.md`. Read `AGENTS.md` first.

---

## Session startup checklist

Before responding to any task, run this mentally:

1. Read `AGENTS.md` — understand current state and which category the task falls into
2. Check `IMPLEMENTATION_PLAN.md` — is this task already planned?
3. Run `git log --oneline -5` — know where the codebase is
4. If the user's intent is unclear — use `/grill-me` before building

---

## Skills to activate at session start

Always activate `ponytail` at the start of any coding task on this project:
```
/ponytail
```

For debugging broken pipeline behavior:
```
/diagnose
```

For architecture or design decisions:
```
/grill-me
```

For production readiness checks after a phase completes:
```
/production-audit
```

---

## How to use the gate runner

After completing any phase of `IMPLEMENTATION_PLAN.md`:
```bash
python3 scripts/gate.py <phase_number>
```

Phase 10 (current active phase) gates are in `scripts/gate.py → phase_10()`.

Phase 10 subtasks 10.1–10.4 are complete (URL list, extraction schema, fetcher switch, indexing). Remaining: run live reindex (10.7 gate — needs user confirmation, costs Firecrawl credits).

Pipeline is working end-to-end via upload path. Golden eval baseline is 80% (8/10). Focus has shifted from implementation to hardening (see "Future scope" in AGENTS.md).

All gates must pass before committing. If a gate fails, fix it — do not commit with known failures.

---

## Supervised vs Autopilot

This project was built primarily in **Autopilot mode**. Sub-agents were used for multi-phase work (Phases 3-9 were delegated to sub-agents).

If the user switches to **Supervised mode**, every file edit will show a diff for approval. Do not re-apply rejected edits — ask what they want changed.

Sub-agents were responsible for the file rejection loops that happened in earlier sessions. If using sub-agents, confirm the user is in Autopilot mode first.

---

## Hooks installed

Two hooks are active in `.kiro/hooks/`:

- `verify-file-write.json` — fires after every `fs_write` / `str_replace`, checks file exists on disk
- `stuck-detector.json` — fires after `execute_bash` timeouts, alerts user

If you see a hook verification fail after a write, the file did not land. Re-read the file, find the actual current content, fix the `oldStr` mismatch, and try again.

---

## Known issues with this codebase to watch for

**The PAT warning:** `.env` line 30 has a `PAT=...` entry with a space that causes `command not found: PAT` in shell. This is harmless — ignore it.

**AZURE_SEARCH_INDEX_NAME mismatch:** `.env` previously had `compliance-docs` but the live index is `brand-compliance-rules`. This caused zero-result retrieval for several sessions. If retrieval breaks again, check this value first.

**AzureSearch.__del__ ImportError:** appears at the end of any script that uses the vector store. Harmless cleanup noise — ignore it.

**Heredocs hang:** never use `cat > file << 'EOF'` in `execute_bash`. Use `fs_write` for file creation.

**PYTHONPATH:** must be set to `.` for all local runs. Tests fail with `ModuleNotFoundError: No module named 'src'` without it.

**Vector store singleton:** `_store` in `policy_store.py` is a module-level singleton. After the Azure OpenAI endpoint changes, the Container App must be restarted to clear it. The singleton is not thread-safe across forked processes (noted in code comment).

**Neon DB cold start:** test_auth.py and test_phase6_email.py hang when Neon is suspended. Adding `connect_timeout=10` to DATABASE_URL would fix this. For now, run tests file-by-file to isolate which ones depend on live DB.

**Phi-4-mini endpoint format:** Uses standard OpenAI SDK (not AzureOpenAI). base_url is `https://shubh-llm-api-project.services.ai.azure.com/openai/v1`. The old `/api/projects/proj-default` path is the management endpoint, not inference.

**YouTube bot detection:** Both youtube-transcript-api and yt-dlp are blocked on Azure Container Apps IPs. Upload path (Whisper) is the workaround. URL path returns metadata-only (title + description + tags) when deployed.

---

## Commit discipline

- One commit per phase or per logical unit of work
- Run tests before every commit
- Commit message format: `Phase X: description` or `fix: description` or `docs: description`
- Never commit with failing tests
- Never commit `skills-main/` or `.commitshow/` — both are in `.gitignore`

---

## What to suggest as a new skill

If you catch yourself doing any of these more than twice, suggest `/write-a-skill`:

- Debugging Azure Container Apps deployment failures (restart + log check pattern)
- Running the full test → gate → commit loop
- Diagnosing Azure AI Search retrieval issues (check index count, check scores, check endpoint match)
- Writing interview Q&A about architectural decisions
