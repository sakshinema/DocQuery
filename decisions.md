# Decisions

This is a decision log, not a changelog. I am keeping the reasoning here because the assignment explicitly asks how I made calls under ambiguity.

## 1. Chose a document-intelligence workspace, not a generic parser API

**The decision**

I interpreted “turn messy documents into structured, queryable data” as a user-facing workspace rather than a raw extraction API.

**The alternatives**

- A developer API that simply returns JSON.
- A batch ETL pipeline with no UI.
- A general-purpose “chat with your files” experience.

**The reasoning**

The evaluator will see more product judgment from an end-to-end workflow. A human user needs to know not only what was extracted, but whether the extraction can be trusted and where it came from. The product therefore treats search, structure, and provenance as one workflow.

**What I deliberately cut**

Authentication, teams, billing, sharing, and a broad connector marketplace. They add surface area without proving the core interpretation of the problem.

---

## 2. Made provenance a first-class data field

**The decision**

Every indexed chunk stores `document_id`, `page`, `section`, and content. Q&A retrieves these chunks and surfaces them next to the answer.

**The alternatives**

- Store one giant text blob per document.
- Use an LLM to answer directly from the whole document.
- Store embeddings only and hide the original evidence.

**The reasoning**

The hardest product problem is not extracting text; it is making the result trustworthy when the input is messy. Page/section provenance lets a reviewer inspect the evidence and makes the generated answer falsifiable.

**What I deliberately cut**

A pixel-perfect PDF viewer. The extracted source is enough to prove provenance in the five-day scope; a full document renderer would add UI complexity without improving the retrieval core.

---

## 3. Used SQLite + FTS5 for the first deployment

**The decision**

Use one SQLite database for documents, chunks, extracted fields, and full-text indexing.

**The alternatives**

- Postgres + pgvector.
- A managed vector database.
- Elasticsearch/OpenSearch.
- Separate relational DB + search service.

**The reasoning**

The expected dataset for a five-day submission is small enough that SQLite FTS5 is operationally sufficient. One datastore means one schema, one backup surface, no synchronization job, and an easy stranger setup. FTS5 also gives us real indexed retrieval rather than scanning every document on every query.

**Tradeoff accepted**

This does not scale horizontally to multiple service instances. The submission runs as one free web service; a durable multi-instance version would move relational state to Postgres.

**What I deliberately cut**

Vector search and multi-node scaling. They are sensible next steps after measuring retrieval misses on a real corpus, not prerequisites for proving the core product.

---

## 4. Added duplicate detection before indexing

**The decision**

Hash the raw upload with SHA-256 and reject/reuse an existing record when the same bytes are uploaded again.

**The alternatives**

- Allow duplicates and dedupe only visually.
- Deduplicate by filename.
- Deduplicate by normalized text.

**The reasoning**

Filenames are not identity, and normalized text can collapse legitimately different versions. The raw content hash is deterministic and cheap. It also turns a realistic user behavior—uploading the same attachment twice—into a predictable experience.

**What I deliberately cut**

Semantic near-duplicate detection. That is valuable for versioned documents but needs a clear product rule about what “same enough” means.

---

## 5. Clean repeated headers/footers conservatively

**The decision**

Before chunking, detect repeated first/last lines across at least three pages and remove them from retrieval text.

**The alternatives**

- Keep every line exactly as extracted.
- Strip every first/last line unconditionally.
- Run an LLM over the entire PDF to decide what is page furniture.

**The reasoning**

Repeated page headers and footers are high-frequency retrieval noise. But aggressively stripping boundaries can delete legitimate content. A three-page recurrence threshold keeps the heuristic conservative and deterministic.

**What I deliberately cut**

OCR and layout-aware header/footer detection. The current parser works best on text-bearing PDFs; image-heavy files are surfaced as a known limitation instead of pretending they were parsed accurately.

---

## 6. Made AI optional, not required for the baseline product

**The decision**

The extraction pipeline has a deterministic fallback. OpenAI is used only when `OPENAI_API_KEY` is configured.

**The alternatives**

- Make the LLM mandatory for every upload.
- Build a purely rule-based extractor.
- Use a third-party document AI product.

**The reasoning**

A document product should degrade gracefully when an external model is unavailable or times out. Deterministic extraction gives the system a usable minimum path, while the LLM improves schema richness and natural-language Q&A.

**What I deliberately cut**

Provider abstraction across several model vendors. It is useful later, but premature for a five-day submission and would dilute the central architecture.

---

## 7. Grounded Q&A retrieves before generating

**The decision**

The `/api/ask` flow first performs FTS5 retrieval and then sends only the top source passages to the model, explicitly requiring citations and an “insufficient evidence” response when the sources do not support the answer.

**The alternatives**

- Send the entire corpus to the model.
- Let the model decide what documents to search without deterministic retrieval.
- Return an answer with no source references.

**The reasoning**

Retrieval limits context size, reduces irrelevant information, and creates an auditable boundary around the generation step. The source cards also make the UI useful even when the model is unavailable.

**What I deliberately cut**

Agentic tool use, web search, and multi-turn memory. The assignment is about the submitted document corpus; expanding beyond it would make the product harder to reason about.

---

## 8. Chose one free deployment unit for the submission demo

**The decision**

Deploy the FastAPI app, UI, parser, search index, and SQLite database as one free Render web service. The SQLite index is ephemeral in this demo environment.

**The alternatives**

- A paid Render service with a persistent disk.
- A free app service plus managed Postgres.
- Separate frontend/backend services.

**The reasoning**

A reviewer needs a public URL more than durable data for a short evaluation. One free service minimizes cost and deployment failure modes, while still supporting the complete upload → query journey within an active session.

**What I deliberately cut**

Durable hosted data, horizontal scaling, background workers, object storage, and distributed tracing. The free demo makes its reset behavior explicit rather than implying production-grade retention.

---

## 9. Treated failures as product states, not just exceptions

**The decision**

Documents move through `processing → ready` or `processing → error`, and parsing failures are stored on the document record.

**The alternatives**

- Let the upload endpoint simply throw a generic error.
- Delete failed records.
- Return a 200 with an empty document.

**The reasoning**

Messy input is part of the problem statement. A useful product should preserve the failure reason so a user knows what happened. This also leaves a clear path for future retries.

**What I deliberately cut**

Automatic retries and a job queue. The five-day version records failure cleanly first; retry orchestration is a production scaling concern.

---

## 10. Bound ingestion work and hide incomplete records from retrieval

**The decision**

Read uploads in fixed-size chunks until the configured byte ceiling, use a SQLite busy timeout for short write contention, and search only documents in the `ready` state. A question with no retrieved evidence returns an explicit no-evidence result without calling the model.

**The alternatives**

- Read the whole multipart payload and check its size afterwards.
- Index chunks as soon as parsing succeeds, even while extraction or persistence can still fail.
- Send an empty evidence set to the LLM and trust it to decline the question.

**The reasoning**

The most believable failure modes in a document tool are an unexpectedly large upload, two users uploading at once, and a partial ingestion leaking draft/error content into search. A limit that runs after the complete body is in memory does not protect the service. Similarly, an answer must be bounded by actual indexed evidence, including the zero-evidence case. These guardrails add very little architecture while making the trust promise concrete.

**What I deliberately cut**

Virus scanning, asynchronous job orchestration, and distributed locking. Those require storage and worker infrastructure that would obscure the core single-service design. The present guardrails make the synchronous path honest and safe within its stated deployment boundary.

---
