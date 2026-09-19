# Architecture

```text
                     ┌─────────────────────────┐
                     │        Browser          │
                     │  Upload / Ask / Inspect │
                     └────────────┬────────────┘
                                  │ HTTP
                                  ▼
                     ┌─────────────────────────┐
                     │        FastAPI          │
                     │ routes + validation     │
                     └────────────┬────────────┘
                                  │
                   ┌──────────────┼──────────────┐
                   │              │              │
                   ▼              ▼              ▼
             ┌──────────┐   ┌────────────┐  ┌──────────────┐
             │ Parsers  │   │ Normalizer │  │   LLM layer  │
             │ PDF/DOCX │   │ cleanup +  │  │ optional     │
             │ TXT/CSV  │   │ chunking   │  │ extraction + │
             └────┬─────┘   └─────┬──────┘  │ grounded QA  │
                  │               │         └──────┬───────┘
                  └───────────────┼────────────────┘
                                  ▼
                     ┌─────────────────────────┐
                     │    SQLite + FTS5        │
                     │ documents / chunks /    │
                     │ entities / search index │
                     └────────────┬────────────┘
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │ Evidence-aware response │
                     │ answer + source chunks  │
                     └─────────────────────────┘
```

## Data model

### documents

One record per unique uploaded byte stream. SHA-256 provides idempotency for exact duplicates. The record also holds status, document type, summary, extracted metadata, and errors.

### chunks

The retrieval unit. Each chunk retains the document ID plus page and section where available. Chunk size is deliberately bounded so retrieval has useful local context.

### entities

Normalized extracted fields such as `email`, `amount`, `due_date`, `company`, or `invoice_number`. The schema stays intentionally flexible because the input document types are not fixed by the assignment.

### chunks_fts

SQLite FTS5 external-content index over `chunks`. This keeps storage simple while still providing ranked retrieval.

## Request flow: upload

```text
upload
  │
  ├─ extension + size validation
  ├─ SHA-256 duplicate check
  ├─ parser selection
  ├─ repeated header/footer cleanup
  ├─ provenance-aware chunking
  ├─ FTS5 indexing
  ├─ structured extraction (LLM → deterministic fallback)
  └─ ready / error status
```

## Request flow: question

```text
question
  │
  ├─ tokenize to safe FTS query
  ├─ retrieve top-k chunks
  ├─ optionally pass only those chunks to the LLM
  └─ return answer + source chunks
```

## Scaling boundary

The current architecture is intentionally single-instance. The first production scaling step would be:

1. move SQLite relational state to Postgres;
2. put original binaries in object storage if binary retention is required;
3. keep a search abstraction so FTS5 can later be replaced by Postgres full-text search or a vector/hybrid index;
4. move long-running extraction to a durable queue.

Those changes are intentionally deferred until usage patterns justify them.
