# Brand Guardian / YouTube Ads Compliance Pipeline

An internal ad compliance screening tool. Reviewers submit YouTube ad URLs; the system compares content against indexed policy documents and returns a structured audit with optional human review.

## Language

**Audit**:
A single compliance check run against one YouTube URL, producing an AI recommendation and optional human decision.
_Avoid_: scan, job (unless referring to background work)

**Team**:
A group within one company whose audit history and policy access are isolated from other teams.
_Avoid_: tenant (reserved for future SaaS), organization

**Reviewer**:
A user who submits audits and may override AI findings.
_Avoid_: analyst, operator

**Admin**:
A user who manages teams, policy document versions, and user role assignments.
_Avoid_: superuser

**Policy version**:
A dated snapshot of indexed compliance documents (YouTube Ad Specs, FTC Influencer Guide) stored in Azure AI Search with a version identifier.
_Avoid_: index run (use for the technical act of indexing)

**AI status**:
The pass or fail recommendation produced by the LLM pipeline before human review.
_Avoid_: model output, inference result

**Final status**:
The effective pass or fail after human review, or the AI status if no review exists yet.
_Avoid_: resolved status

**Policy citation**:
A link from a violation to the exact indexed rule chunk (source document, excerpt, chunk id).
_Avoid_: reference, source snippet

**Ingestion**:
Collecting all text used for compliance comparison: metadata, captions, and on screen text when available.
_Avoid_: indexing (indexing applies to policy PDFs only)

## Relationships

- A **Team** has many **Reviewers** and many **Audits**
- An **Audit** belongs to one **Team** and one **Policy version**
- An **Audit** has one **AI status** and optionally one **Final status** after human review
- Each violation on an **Audit** may include one **Policy citation**

## Flagged ambiguities

- "transcript" in code historically meant metadata only; going forward **Ingestion** is the domain term for all text inputs to the auditor.
