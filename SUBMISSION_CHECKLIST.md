# Submission checklist

| Evaluation area | What the repo demonstrates |
|---|---|
| Problem framing | Concrete analyst workflow: ingest → structure → query → verify evidence. |
| Product thinking | Small surface area focused on reducing manual document lookup, with trust as the product promise. |
| UX decisions | Explicit first-run flow, upload status, empty state, structured view, failure state, source evidence. |
| Code quality | Separated parser, normalization, extraction, persistence, and HTTP layers. |
| Tests | Focused tests covering normalization, provenance, FTS round-trip, extraction, duplicate uploads, upload limits, readiness isolation, and API health. |
| Documentation | README, architecture diagram, product notes, decisions log, deployment config. |
| Setup experience | One Python service, optional API key, local SQLite, seed script, health endpoint. |
| Velocity | Scope avoids auth, distributed infra, OCR, vector DB, and other work that would dilute the five-day core. |
| Above & beyond | Repeated header/footer cleanup, bounded upload streaming, deterministic fallback extraction, exact-file dedupe, grounded retrieval with provenance, readiness-gated search, recorded ingestion failures. |

## Final demo sequence

1. Start from an empty library.
2. Upload a messy document and show the structured fields.
3. Ask a cross-document question.
4. Open one cited source and verify the claim.
5. Upload the same file again and show idempotent duplicate handling.
6. Show `decisions.md` and `ARCHITECTURE.md` in the repository.
