from fastapi.testclient import TestClient

from app.main import app


def test_healthz_tra_ve_ok():
    with TestClient(app) as client:
        res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
