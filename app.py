from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# Local development uses `.env`; hosted environments provide the same values as
# real environment variables. Existing environment variables always win.
load_dotenv(BASE_DIR / ".env")

from lib.db import (
    create_document,
    delete_document,
    get_document,
    init_db,
    insert_chunks,
    list_documents,
    mark_document_error,
    mark_document_ready,
    search_chunks,
    stats,
)
from lib.extract import grounded_answer, llm_extract
from lib.normalize import chunk_pages
from lib.parser import DocumentParseError, UnsupportedDocument, parse_document

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv"}
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


class UploadTooLarge(Exception):
    """Raised before an upload can consume more than the configured memory budget."""


async def read_upload_with_limit(file: UploadFile) -> bytes:
    """Read an upload incrementally and stop as soon as it crosses the size limit.

    ``UploadFile.read()`` without a size argument loads the complete request payload.
    That makes a post-read size check ineffective for the failure mode it is meant to
    guard against. This keeps the normal in-memory parsing design, while bounding it
    to the application's advertised upload limit.
    """
    chunks: list[bytes] = []
    total = 0
    while data := await file.read(UPLOAD_READ_CHUNK_BYTES):
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise UploadTooLarge
        chunks.append(data)
    return b"".join(chunks)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="DocQuery", version="0.1.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class AskRequest(BaseModel):
    question: str
    document_type: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "documents": list_documents(),
            "stats": stats(),
            "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
        },
    )


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_page(request: Request, doc_id: str):
    document = get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return templates.TemplateResponse(request=request, name="document.html", context={"document": document})


@app.post("/api/documents")
async def upload_document(file: Annotated[UploadFile, File(...)]):
    filename = file.filename or "untitled"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Use {', '.join(sorted(ALLOWED_EXTENSIONS))}.")
    try:
        data = await read_upload_with_limit(file)
    except UploadTooLarge:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit.")
    sha256 = hashlib.sha256(data).hexdigest()
    doc_id, created = create_document(filename, file.content_type or "application/octet-stream", len(data), sha256)
    if not created:
        return JSONResponse({"id": doc_id, "duplicate": True, "message": "This exact file is already indexed."}, status_code=200)
    try:
        from io import BytesIO

        pages, metadata = parse_document(filename, BytesIO(data))
        chunks = chunk_pages(pages)
        insert_chunks(
            doc_id,
            [{"page": c.page, "section": c.section, "content": c.text} for c in chunks],
        )
        full_text = "\n\n".join(c.text for c in chunks)
        extraction = llm_extract(filename, full_text)
        mark_document_ready(doc_id, extraction, metadata)
        return JSONResponse(
            {"id": doc_id, "duplicate": False, "document": get_document(doc_id)},
            status_code=201,
        )
    except (UnsupportedDocument, DocumentParseError, ValueError) as exc:
        mark_document_error(doc_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        mark_document_error(doc_id, f"Unexpected ingestion failure: {exc}")
        raise HTTPException(status_code=500, detail="The document could not be indexed. The failure has been recorded.") from exc


@app.get("/api/documents")
def documents_api():
    return {"documents": list_documents(), "stats": stats()}


@app.get("/api/documents/{doc_id}")
def document_api(doc_id: str):
    document = get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@app.delete("/api/documents/{doc_id}")
def delete_document_api(doc_id: str):
    if not delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}


@app.get("/api/search")
def search_api(q: str, document_type: Optional[str] = None):
    if len(q.strip()) < 2:
        return {"results": []}
    return {"results": search_chunks(q, limit=10, document_type=document_type)}


@app.post("/api/ask")
def ask_api(payload: AskRequest):
    question = payload.question.strip()
    if len(question) < 3:
        raise HTTPException(status_code=400, detail="Ask a question with at least 3 characters.")
    sources = search_chunks(question, limit=6, document_type=payload.document_type)
    answer = grounded_answer(question, sources)
    return {**answer, "sources": sources}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "docquery", "stats": stats()}
