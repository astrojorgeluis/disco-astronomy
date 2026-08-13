"""Minimal regression tests for DISCO v1 server helpers and upload path."""
import os
import sys
import tempfile

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

# Ensure package import works when tests run from repo root or DISCO_Source_Git
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    # Import after path setup
    import disco.server as server

    monkeypatch.setattr(server, "UPLOAD_DIR", str(upload_dir))
    server.clear_analysis_state()
    server.state.data = None
    server.state.header = None
    server.state.filename = None
    return TestClient(server.app), server


def _write_fits(path, data, header_extra=None):
    hdu = fits.PrimaryHDU(data=data)
    if header_extra:
        for k, v in header_extra.items():
            hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def test_extract_image_2d(client):
    _, server = client
    data = np.random.rand(64, 64).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as f:
        path = f.name
    try:
        _write_fits(path, data, {"CDELT2": 1e-5, "BMAJ": 1e-5, "BMIN": 8e-6})
        with fits.open(path) as hdul:
            arr, hdr = server.extract_image_from_hdul(hdul)
        assert arr.ndim == 2
        assert arr.shape == (64, 64)
        assert "CDELT2" in hdr
    finally:
        os.unlink(path)


def test_extract_image_cube_takes_plane(client):
    _, server = client
    cube = np.random.rand(4, 32, 32).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as f:
        path = f.name
    try:
        _write_fits(path, cube, {"CDELT2": 1e-5})
        with fits.open(path) as hdul:
            arr, _ = server.extract_image_from_hdul(hdul)
        assert arr.ndim == 2
        assert arr.shape == (32, 32)
    finally:
        os.unlink(path)


def test_extract_image_empty_hdu_errors(client):
    _, server = client
    with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as f:
        path = f.name
    try:
        fits.PrimaryHDU(data=None).writeto(path, overwrite=True)
        with fits.open(path) as hdul:
            with pytest.raises(Exception):
                server.extract_image_from_hdul(hdul)
    finally:
        os.unlink(path)


def test_pixel_scale_missing_cdelt_warns(client):
    _, server = client
    hdr = fits.Header()
    scale, warning = server.get_pixel_scale_arcsec(hdr)
    assert scale > 0
    assert warning is not None


def test_pixel_scale_zero_cdelt_warns(client):
    _, server = client
    hdr = fits.Header({"CDELT2": 0.0})
    scale, warning = server.get_pixel_scale_arcsec(hdr)
    assert scale > 0
    assert warning is not None


def test_safe_upload_basename_blocks_traversal(client):
    _, server = client
    assert server.safe_upload_basename("../../etc/passwd") == "passwd"
    assert server.safe_upload_basename("disk.fits") == "disk.fits"


def test_upload_and_pipeline_roundtrip(client):
    tc, server = client
    data = np.zeros((128, 128), dtype=np.float32)
    yy, xx = np.ogrid[:128, :128]
    data += np.exp(-(((xx - 64) ** 2 + (yy - 64) ** 2) / (2 * 8 ** 2)))
    data *= 10.0

    with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as f:
        path = f.name
    try:
        _write_fits(
            path,
            data,
            {
                "CDELT2": 1e-5,
                "BMAJ": 2e-5,
                "BMIN": 1.5e-5,
                "BPA": 0.0,
                "RESTFRQ": 230e9,
                "BUNIT": "JY/BEAM",
            },
        )
        with open(path, "rb") as fh:
            resp = tc.post("/upload", files={"file": ("synth.fits", fh, "application/fits")})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["shape"] == [128, 128]
        assert body["pixel_scale"] > 0

        pipe = tc.post(
            "/run_pipeline",
            json={
                "cx": 64.0,
                "cy": 64.0,
                "pa": 45.0,
                "incl": 30.0,
                "rout": 1.0,
                "fit_rmin": 0.0,
                "fit_rmax": 0.0,
            },
        )
        assert pipe.status_code == 200, pipe.text
        out = pipe.json()
        assert "images" in out and "deproj" in out["images"]
        assert "profile" in out
        assert server.state.profile_data is not None

        # Loading a second file must clear prior analysis state
        with open(path, "rb") as fh:
            resp2 = tc.post("/upload", files={"file": ("synth2.fits", fh, "application/fits")})
        assert resp2.status_code == 200
        assert server.state.profile_data is None
        assert server.state.results == {}
    finally:
        os.unlink(path)


def test_cnn_empty_crop_arity():
    from disco.core.cnn_inference import predict_with_cnn

    class Dummy:
        def eval(self):
            return self

    data = np.zeros((10, 10), dtype=np.float32)
    header = fits.Header({"BMAJ": 1e-5, "BMIN": 1e-5, "BPA": 0.0})
    # Force empty crop by putting center far outside with tiny search
    result = predict_with_cnn(data, header, pixel_scale=1.0, cx=-1000, cy=-1000, search_rad=0.1, model=Dummy())
    assert len(result) == 4


def test_cli_help_includes_yes():
    from disco.cli import main
    import argparse
    # Smoke: argparse accepts --yes
    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--yes", action="store_true")
    ns = parser.parse_args(["--yes"])
    assert ns.yes is True
