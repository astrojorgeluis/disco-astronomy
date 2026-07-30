"""Tests for raster pyramid and tile endpoints."""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from disco.server.app import create_app
from disco.server.pyramid import TILE_SIZE, ensure_pyramid, extract_tile, overview
from disco.server.session import ImageEntry
from tests.conftest import make_synthetic_disk


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        yield c


def _upload_synth(client, size=256):
    data, header = make_synthetic_disk(size=size, cx=size / 2, cy=size / 2, rout_pix=size * 0.25)
    path = tempfile.mktemp(suffix=".fits")
    fits.PrimaryHDU(data=data.astype(np.float32), header=header).writeto(path, overwrite=True)
    with open(path, "rb") as f:
        r = client.post("/api/upload", files={"file": ("synth.fits", f, "application/fits")})
    os.unlink(path)
    assert r.status_code == 200, r.text
    return r.json()


def test_raster_meta_and_overview(client):
    body = _upload_synth(client, size=512)
    image_id = body["id"]
    meta = client.get(f"/api/raster/meta?image_id={image_id}").json()
    assert meta["full_width"] == 512
    assert meta["n_levels"] >= 1
    assert "stats" in meta
    r = client.get(f"/api/raster?image_id={image_id}&max_size=256")
    assert r.status_code == 200
    w = int(r.headers["X-DISCO-Width"])
    h = int(r.headers["X-DISCO-Height"])
    assert max(w, h) <= 256
    buf = np.frombuffer(r.content, dtype="<f4")
    assert buf.size == w * h


def test_tile_size_and_levels(client):
    body = _upload_synth(client, size=1024)
    image_id = body["id"]
    meta = client.get(f"/api/raster/meta?image_id={image_id}").json()
    assert meta["n_levels"] >= 2
    r = client.get(f"/api/tiles/{image_id}/data/0/0/0")
    assert r.status_code == 200
    buf = np.frombuffer(r.content, dtype="<f4")
    assert buf.size == TILE_SIZE * TILE_SIZE
    assert int(r.headers["X-DISCO-TileSize"]) == TILE_SIZE


def test_pixels_rejects_large(client):
    body = _upload_synth(client, size=2048)
    r = client.get(f"/api/pixels?image_id={body['id']}")
    assert r.status_code == 413


def test_pyramid_unit():
    data = np.arange(256 * 256, dtype=np.float32).reshape(256, 256)
    entry = ImageEntry(
        id="t", filename="t.fits", path="/tmp/t.fits",
        data=data, header=fits.Header(), pixel_scale=0.05,
    )
    levels = ensure_pyramid(entry, "data")
    assert levels[0].shape == (256, 256)
    arr, decim, stats = overview(entry, "data", max_size=64)
    assert max(arr.shape) <= 64
    assert decim >= 1
    tile = extract_tile(levels[0], 0, 0)
    assert tile.shape == (TILE_SIZE, TILE_SIZE)
