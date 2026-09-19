from pathlib import Path

from fastapi.testclient import TestClient


def test_health_and_upload(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DOCQUERY_DB_PATH', str(tmp_path / 'api.db'))
    import importlib
    import lib.db as db
    import app as app_module
    importlib.reload(db)
    importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        health = client.get('/api/health')
        assert health.status_code == 200
        response = client.post(
            '/api/documents',
            files={'file': ('sample.txt', b'Acme invoice\nTotal INR 5000\nfinance@example.com', 'text/plain')},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload['document']['document_type'] == 'invoice'
        duplicate = client.post(
            '/api/documents',
            files={'file': ('sample.txt', b'Acme invoice\nTotal INR 5000\nfinance@example.com', 'text/plain')},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()['duplicate'] is True


def test_upload_limit_is_enforced_before_a_large_payload_is_retained(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DOCQUERY_DB_PATH', str(tmp_path / 'api.db'))
    monkeypatch.setenv('MAX_UPLOAD_MB', '0')
    import importlib
    import lib.db as db
    import app as app_module
    importlib.reload(db)
    importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        response = client.post(
            '/api/documents',
            files={'file': ('too-large.txt', b'x', 'text/plain')},
        )
    assert response.status_code == 413
    assert 'exceeds the 0 MB limit' in response.json()['detail']
