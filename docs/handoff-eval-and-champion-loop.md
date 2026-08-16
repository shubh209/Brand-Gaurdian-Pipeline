# Handoff: Eval Baseline + Self-Improving Champion Loop

## What happened this session

This session covered frontend implementation, repo cleanup, production hardening, testing, error analysis, eval dataset creation, and speed optimization. Key commits:

- `23458ba` — Frontend pages (New Audit, Result, History, Prompt) + repo cleanup
- `a4f79b3` — Production hardening (CORS, non-root, LLM timeouts, DB connect_timeout)
- `81f69b0` — Testing phase (failure paths, API contracts, synthetic eval, rate limiter)
- `ce69812` — Operational error learning system
- `eab2b96` / `25a6843` — 104-case golden eval dataset v2
- `378ddfc` — FTC seed claim scraper
- `bfdcb63` — Timeout fix for query expansion
- `4654a23` — Batch query expansion + eval --fast mode (50% faster)

## Current state

- **74 backend tests passing** (excluding DB-dependent and LLM-dependent tests)
- **104-case eval dataset** in `evals/golden_dataset_v2.json` (6 categories, 72 FAIL / 32 PASS)
- **Eval runner** at `evals/run_eval_v2.py` with `--fast` flag (~14s/case, ~25 min for full run)
- **Error analysis endpoint** at `GET /admin/error-analysis` with Langfuse integration
- **Frontend deployed** at `brand-guardian-nine.vercel.app`
- **Backend deployed** at `brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io`

## What needs to happen next

### Step 1: Get baseline eval results

**COMPLETED.** Baseline established:

```
Overall: 76.9% (80/104)
False Positive Rate: 68.8% (22/32 PASS cases flagged as violations)
False Negative Rate: 2.8% (2/72 FAIL cases missed)

Per-category:
  financial_claim:       92% (11/12)
  deceptive_urgency:     90% (9/10)
  before_after:          89% (8/9)
  misleading_efficacy:   78% (18/23)
  health_claim:          71% (25/35)
  disclosure_violation:  60% (9/15)
```

**Root cause:** The system catches 97% of violations but only recognizes 31% of compliant ads. GPT-4o's reasoning prompt flags ads even when they use proper hedging and disclaimers.

### Step 2: Build the Self-Improving Champion Loop

Priority rounds for the loop:

1. **Round 1:** Add explicit PASS criteria to reasoning prompt — "If the ad uses 'may', 'some research suggests', 'individual results vary', 'not intended to treat', and does NOT make absolute claims, return no violations"
2. **Round 2:** Fix disclosure detection — distinguish "#ad missing" (violation) from "This episode is brought to you by..." (compliant)
3. **Round 3:** Reduce health_claim false positives on properly qualified supplement ads

**Loop specification:**

| Field | Value |
|-------|-------|
| **Task** | Improve ComplianceAuditor prompts until eval score reaches target |
| **Trigger** | Manual (run by developer after eval baseline) |
| **Goal** | Raise holdout accuracy from baseline to ≥85% |
| **Champion** | Current prompts in `src/services/compliance_auditor.py` |
| **Improvement set** | 70 cases from golden_dataset_v2.json (random 67%) |
| **Holdout set** | 34 cases (remaining 33% — never seen during improvement) |
| **Evaluator** | Per-case: status_correct AND violations_met. Overall: accuracy %. Per-criterion: false_positive_rate, false_negative_rate, per_category_accuracy |
| **Allowed changes** | System prompts, few-shot examples, claim extraction prompt, reasoning prompt |
| **Prohibited changes** | Architecture, models used, retrieval logic, API contracts |
| **Budget** | 12 rounds max, 3 stall rounds, ~$5 total LLM cost |
| **Stopping** | Target reached (85% holdout) OR budget exhausted OR 3 stalls |

**Key insight from early results:** The system is good at catching violations (0% false negative in 3-case test) but bad at recognizing compliant ads (100% false positive). The first improvement rounds should target the GPT-4o reasoning prompt — it needs stronger "only flag if you can cite a SPECIFIC rule" enforcement.

### Step 3: After the loop

Once the champion loop produces an improved prompt:
1. Commit the final champion prompt
2. Re-run full eval (including holdout) to confirm
3. Update AGENTS.md with new baseline score
4. Deploy to production

## Key files

| File | Purpose |
|------|---------|
| `evals/golden_dataset_v2.json` | 104 eval cases (source of truth) |
| `evals/run_eval_v2.py` | Eval runner (--fast, --limit, --category) |
| `evals/eval_results_v2.json` | Latest eval output (after running) |
| `evals/curated_seeds.json` | 20 FTC verbatim seeds for variant generation |
| `evals/seed_claims.json` | 54 raw scraped seeds |
| `evals/scrape_ftc_seeds.py` | Reusable FTC scraper |
| `src/services/compliance_auditor.py` | The prompts to improve (champion) |
| `src/services/policy_retriever.py` | Batch expansion + retrieval |
| `src/services/error_analysis.py` | Operational error detection |
| `docs/SPEC-testing-phase.md` | Testing phase spec |
| `docs/SPEC-production-hardening.md` | Hardening spec |

## Known issues

1. **False positive on compliant ads** — system flags hedged language as violations. The reasoning prompt needs "only flag with specific policy citation" enforcement.
2. **Phi-4-mini cold start** — serverless endpoint can take 60s+ when cold. Batch expansion and 15s timeout mitigate this.
3. **`signal.SIGALRM` doesn't work on Windows** — eval runner is macOS/Linux only.
4. **AGENTS.md is stale** — still references old state (containers as root, scripts/gate.py, etc.). Update after this work stabilizes.

## Suggested skills for next session

- `/implement` — for building the champion loop runner
- `/tdd` — each round of improvement should be testable
- `/diagnose` — if false positive pattern is unclear, trace through the reasoning step
- `/grill-with-docs` — stress-test the loop design before building
- `ponytail` — always active on this project
