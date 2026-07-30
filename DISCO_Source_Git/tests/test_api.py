"""API smoke tests for the modular FastAPI app."""
from __future__ import annotations

import os
import tempfile

import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from disco.server.app import create_app
from tests.conftest import make_synthetic_disk


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_and_pipeline(client):
    data, header = make_synthetic_disk()
    path = tempfile.mktemp(suffix=".fits")
    fits.PrimaryHDU(data=data, header=header).writeto(path, overwrite=True)
    with open(path, "rb") as f:
        r = client.post("/api/upload", files={"file": ("synth.fits", f, "application/fits")})
    os.unlink(path)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    r2 = client.post(
        "/api/run_pipeline",
        json={"cx": 128, "cy": 128, "pa": 90, "incl": 40, "rout": 3.0},
    )
    assert r2.status_code == 200
    out = r2.json()
    assert "profile" in out
    assert len(out["profile"]["radius"]) > 10
    r3 = client.get("/api/pixels")
    assert r3.status_code == 200
    assert int(r3.headers["X-DISCO-Width"]) == 256
