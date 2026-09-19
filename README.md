# DocQuery

DocQuery is a small document-intelligence workspace built for the open-ended assignment:

> Turn messy documents into structured, queryable data.

The product deliberately focuses on one high-value workflow:

**upload → normalize → structure → index → search → answer with evidence**

It accepts PDF, DOCX, TXT, and CSV files. It keeps source provenance at the chunk level, exposes extracted fields, supports full-text search using SQLite FTS5, and can optionally use the OpenAI Responses API for richer extraction and grounded Q&A.

## Why this scope

The problem statement is intentionally broad. Instead of building a generic “AI document platform”, DocQuery chooses a concrete user: an operations/analyst user who regularly receives messy business documents and needs to answer questions quickly without losing the source of truth.

The differentiator is **trust**: every generated answer is backed by retrieved source passages, and every indexed passage retains page/section provenance when the input format supports it.

## Product flow

1. Upload a document.
2. Validate size/type and hash it for duplicate detection.
3. Parse the format into page/section-aware text.
4. Normalize repeated headers/footers and whitespace.
5. Chunk the content while preserving provenance.
6. Extract useful structured fields.
7. Index the chunks in SQLite FTS5.
8. Search by keyword or ask a natural-language question.
9. Inspect the evidence behind the answer.

## Supported formats

- PDF — text extraction with page numbers.
- DOCX — paragraph, heading and table extraction with section labels.
- TXT — plain text.
- CSV — row/column-preserving text representation.

Image-only PDFs are intentionally detected as unreadable rather than silently hallucinating OCR output. OCR is a planned extension and is called out in `decisions.md`.

## Stack

- Python 3.11+
- FastAPI
- Jinja2 + small vanilla JS UI
- SQLite + FTS5
- pypdf
- python-docx
- OpenAI Responses API (optional)

The current OpenAI model default is `gpt-5.6-luna`, chosen for cost-sensitive extraction/QA. The key is server-side only; no API key is exposed to the browser.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload
```

Open http://127.0.0.1:8000.

Without `OPENAI_API_KEY`, the app still works end to end using deterministic field extraction and FTS5 search. With an API key, structured extraction and grounded Q&A become substantially richer.

## Tests

```bash
pytest -q
```

The tests focus on real failure modes rather than superficial endpoint coverage:

- repeated PDF headers/footers should not pollute retrieval;
- page/section provenance must survive chunking;
- duplicate uploads must be detected by content hash;
- indexed content must round-trip through FTS5;
- processing/failed records must never leak into search results;
- the upload limit must reject an over-limit stream before it is retained;
- extraction should recognize high-signal fields such as email and currency;
- a question with no evidence must not be sent to the model.

## Deploy on Render for free

The repository includes `render.yaml` configured for Render's free web-service tier. It provides a public HTTPS URL without needing an OpenAI key.

Create a **New Blueprint** in Render, connect this repository, and let `render.yaml` configure the service. If you later want LLM extraction and grounded answers, add `OPENAI_API_KEY` in the service's Environment settings; it is not needed for the deterministic baseline. The app exposes `/api/health` as a health-check endpoint.

The free service is intended for a live submission demo: it spins down after inactivity and its local SQLite index is reset on a restart, redeploy, or spin-down. A reviewer should upload documents and query them in the same active session. After deployment, verify `https://<your-service>.onrender.com/api/health`, then use that same base URL for the reviewer-facing submission link.

For a durable production deployment, I would move the relational state to managed Postgres and binary storage to object storage. That is deliberately outside this five-day scope; the tradeoff is recorded in `decisions.md`.

## Demo script

A reviewer can understand the product in about two minutes:

1. Upload a representative invoice, resume, contract, or report.
2. Open the document and inspect the structured fields.
3. Ask a cross-document question from the home page.
4. Click one of the evidence sources and verify the answer against the original extracted passage.
5. Upload the exact same file again to see duplicate detection.

## Repository structure

```text
.
├── app.py                 # HTTP routes + web app
├── lib/
│   ├── db.py             # SQLite schema + FTS5 queries
│   ├── extract.py        # deterministic + LLM extraction / grounded QA
│   ├── normalize.py      # normalization, repeated header/footer cleanup, chunking
│   └── parser.py         # PDF/DOCX/TXT/CSV parsing
├── templates/            # server-rendered product UI
├── static/               # CSS + browser interactions
├── tests/                # unit + API tests
├── decisions.md          # engineering/product decision log
├── render.yaml           # deployment definition
└── requirements.txt
```

## Optional demo seed

For a quick local walkthrough:

```bash
python scripts/seed.py
```

This adds three small, intentionally different documents so search, structured extraction, duplicate detection, and evidence links can be demonstrated before uploading anything.
