import os
from pathlib import Path


def test_fts_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DOCQUERY_DB_PATH', str(tmp_path / 'test.db'))
    import importlib
    import lib.db as db
    importlib.reload(db)
    db.init_db()
    doc_id, created = db.create_document('invoice.txt', 'text/plain', 42, 'abc123')
    assert created
    db.insert_chunks(doc_id, [{'page': 1, 'section': None, 'content': 'Invoice total is INR 4500 due on 2026-09-30.'}])
    db.mark_document_ready(doc_id, {'title':'Invoice','document_type':'invoice','summary':'Test','confidence':0.9,'entities':[]}, {})
    hits = db.search_chunks('invoice total')
    assert hits and hits[0]['document_id'] == doc_id
    doc = db.get_document(doc_id)
    assert doc['status'] == 'ready'
    assert doc['chunks'][0]['page'] == 1
    assert db.delete_document(doc_id)
    assert db.get_document(doc_id) is None


def test_search_excludes_documents_that_are_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DOCQUERY_DB_PATH', str(tmp_path / 'test.db'))
    import importlib
    import lib.db as db
    importlib.reload(db)
    db.init_db()
    doc_id, created = db.create_document('pending.txt', 'text/plain', 42, 'pending-hash')
    assert created
    db.insert_chunks(doc_id, [{'page': 1, 'section': None, 'content': 'Sensitive draft invoice total INR 4500.'}])

    assert db.search_chunks('invoice total') == []
