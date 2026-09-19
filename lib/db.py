from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = os.getenv("DOCQUERY_DB_PATH", "./data/docquery.db")


def _connect() -> sqlite3.Connection:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Concurrent uploads are still serialized by SQLite, but a short wait is much
    # friendlier than immediately failing one of two near-simultaneous requests.
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            title TEXT,
            document_type TEXT,
            summary TEXT,
            extraction_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page INTEGER,
            section TEXT,
            content TEXT NOT NULL,
            UNIQUE(document_id, chunk_index)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            content='chunks',
            content_rowid='id'
        );

        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_entities_key ON entities(key);
        """
    )
    conn.commit()
    conn.close()


def create_document(filename: str, mime_type: str, size_bytes: int, sha256: str) -> tuple[str, bool]:
    conn = _connect()
    existing = conn.execute("SELECT id FROM documents WHERE sha256=?", (sha256,)).fetchone()
    if existing:
        conn.close()
        return existing["id"], False
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents(id,filename,mime_type,size_bytes,sha256,status,created_at) VALUES (?,?,?,?,?,?,?)",
        (doc_id, filename, mime_type, size_bytes, sha256, "processing", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return doc_id, True


def mark_document_ready(doc_id: str, extraction: dict[str, Any], metadata: dict[str, Any]) -> None:
    conn = _connect()
    entities = extraction.get("entities") or []
    conn.execute(
        "UPDATE documents SET status='ready', title=?, document_type=?, summary=?, extraction_json=?, metadata_json=?, error=NULL WHERE id=?",
        (
            extraction.get("title"),
            extraction.get("document_type", "document"),
            extraction.get("summary", ""),
            json.dumps(extraction, ensure_ascii=False),
            json.dumps(metadata, ensure_ascii=False),
            doc_id,
        ),
    )
    conn.executemany(
        "INSERT INTO entities(document_id,key,value,value_type,confidence) VALUES (?,?,?,?,?)",
        [
            (doc_id, str(e.get("key", "field")), str(e.get("value", "")), str(e.get("type", "text")), float(e.get("confidence", 0.5)))
            for e in entities
            if e.get("value")
        ],
    )
    conn.commit()
    conn.close()


def mark_document_error(doc_id: str, error: str) -> None:
    conn = _connect()
    conn.execute("UPDATE documents SET status='error', error=? WHERE id=?", (error[:1000], doc_id))
    conn.commit()
    conn.close()


def insert_chunks(doc_id: str, chunks: list[dict[str, Any]]) -> None:
    conn = _connect()
    conn.executemany(
        "INSERT INTO chunks(document_id,chunk_index,page,section,content) VALUES (?,?,?,?,?)",
        [(doc_id, i, c.get("page"), c.get("section"), c["content"]) for i, c in enumerate(chunks)],
    )
    # Contentless FTS table is maintained explicitly so indexing remains deterministic.
    conn.executemany(
        "INSERT INTO chunks_fts(rowid,content) VALUES ((SELECT id FROM chunks WHERE document_id=? AND chunk_index=?),?)",
        [(doc_id, i, c["content"]) for i, c in enumerate(chunks)],
    )
    conn.commit()
    conn.close()


def list_documents() -> list[dict[str, Any]]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id,filename,mime_type,size_bytes,status,title,document_type,summary,created_at,error FROM documents ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    conn = _connect()
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return None
    chunks = conn.execute(
        "SELECT id,chunk_index,page,section,content FROM chunks WHERE document_id=? ORDER BY chunk_index", (doc_id,)
    ).fetchall()
    entities = conn.execute(
        "SELECT key,value,value_type,confidence FROM entities WHERE document_id=? ORDER BY key,value", (doc_id,)
    ).fetchall()
    conn.close()
    data = dict(doc)
    data["extraction"] = json.loads(data.pop("extraction_json") or "{}")
    data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    data["chunks"] = [dict(r) for r in chunks]
    data["entities"] = [dict(r) for r in entities]
    return data


def delete_document(doc_id: str) -> bool:
    conn = _connect()
    exists = conn.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not exists:
        conn.close()
        return False
    ids = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE document_id=?", (doc_id,)).fetchall()]
    if ids:
        conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()
    return True


def search_chunks(query: str, limit: int = 8, document_type: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    terms = [t for t in query.strip().split() if len(t) >= 2]
    fts_query = " OR ".join(f'"{t.replace(chr(34), "")}"*' for t in terms[:12])
    if not fts_query:
        return []
    sql = """
        SELECT c.id, c.document_id, c.page, c.section, c.content,
               d.filename AS document_name, d.title, d.document_type,
               bm25(chunks_fts) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ? AND d.status='ready'
    """
    params: list[Any] = [fts_query]
    if document_type:
        sql += " AND d.document_type=?"
        params.append(document_type)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats() -> dict[str, int]:
    conn = _connect()
    data = {
        "documents": conn.execute("SELECT COUNT(*) AS c FROM documents WHERE status='ready'").fetchone()["c"],
        "processing": conn.execute("SELECT COUNT(*) AS c FROM documents WHERE status='processing'").fetchone()["c"],
        "chunks": conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"],
        "fields": conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"],
    }
    conn.close()
    return data
