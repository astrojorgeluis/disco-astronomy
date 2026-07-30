"""Shared fixtures for DISCO regression tests."""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pytest
from astropy.io import fits

# Ensure package import works when running from repo root or DISCO_Source_Git
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def make_synthetic_disk(
    size: int = 256,
    cx: float = 128.0,
    cy: float = 128.0,
    incl: float = 40.0,
    pa: float = 90.0,
    rout_pix: float = 60.0,
    peak: float = 10.0,
    noise: float = 0.05,
    pixel_scale: float = 0.05,
    seed: int = 42,
    use_cd_matrix: bool = False,
    bunit: str = "mJy/beam",
) -> tuple[np.ndarray, fits.Header]:
    """Build a simple inclined Gaussian ring disk + FITS header with WCS/beam."""
    rng = np.random.default_rng(seed)
    y, x = np.indices((size, size))
    dx = x - cx
    dy = y - cy

    pa_rad = np.radians(pa)
    incl_rad = np.radians(incl)
    cos_i = np.cos(incl_rad)

    # Rotate into disk frame
    x_maj = -dx * np.sin(pa_rad) + dy * np.cos(pa_rad)
    x_min = dx * np.cos(pa_rad) + dy * np.sin(pa_rad)
    r = np.sqrt(x_maj**2 + (x_min / cos_i) ** 2)

    ring_r = rout_pix * 0.55
    sigma = rout_pix * 0.18
    data = peak * np.exp(-0.5 * ((r - ring_r) / sigma) ** 2)
    data += rng.normal(0.0, noise, size=data.shape).astype(np.float32)
    data = data.astype(np.float32)

    header = fits.Header()
    header["NAXIS"] = 2
    header["NAXIS1"] = size
    header["NAXIS2"] = size
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = cx + 1
    header["CRPIX2"] = cy + 1
    header["CRVAL1"] = 150.0
    header["CRVAL2"] = -30.0
    deg = pixel_scale / 3600.0
    if use_cd_matrix:
        # CD matrix only — no CDELT (covers the old CLI bug)
        header["CD1_1"] = -deg
        header["CD1_2"] = 0.0
        header["CD2_1"] = 0.0
        header["CD2_2"] = deg
    else:
        header["CDELT1"] = -deg
        header["CDELT2"] = deg
    header["BUNIT"] = bunit
    header["BMAJ"] = (0.15 / 3600.0)
    header["BMIN"] = (0.12 / 3600.0)
    header["BPA"] = 10.0
    header["RESTFRQ"] = 230.538e9
    header["OBJECT"] = "SYNTH_DISK"
    header["TELESCOP"] = "ALMA"
    return data, header


def make_cli_args(**overrides):
    """Build an argparse.Namespace matching disco.cli.run_pipeline expectations."""
    defaults = {
        "rout": None,
        "rmin": 0.0,
        "incl": 40.0,
        "pa": 90.0,
        "beam": None,
        "homobeam": "off",
        "csv": "on",
        "debug": "off",
        "yes": True,
        "no_gaia": True,
        "identifier": [],
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def synthetic_disk():
    data, header = make_synthetic_disk()
    return {"data": data, "header": header, "pixel_scale": 0.05, "cx": 128.0, "cy": 128.0}


@pytest.fixture
def synthetic_fits_path(tmp_path, synthetic_disk):
    path = tmp_path / "synth_disk.fits"
    hdu = fits.PrimaryHDU(data=synthetic_disk["data"], header=synthetic_disk["header"])
    hdu.writeto(path, overwrite=True)
    return str(path)


@pytest.fixture
def cd_matrix_header():
    """Synthetic disk whose WCS uses a CD matrix and no CDELT keywords."""
    data, header = make_synthetic_disk(use_cd_matrix=True, noise=0.0)
    assert "CDELT2" not in header
    assert "CD2_2" in header
    return {
        "data": data,
        "header": header,
        "pixel_scale": 0.05,
        "cx": 128.0,
        "cy": 128.0,
        "rout_pix": 60.0,
    }


@pytest.fixture
def multiband_tree(tmp_path):
    """Temporary directory tree with two Band_* FITS files for discover_groups."""
    data_dir = tmp_path / "targets" / "OBJ"
    data_dir.mkdir(parents=True)
    data, header = make_synthetic_disk(noise=0.02, seed=1)
    paths = []
    for band in (6, 7):
        path = data_dir / f"OBJ_Band_{band}.fits"
        fits.PrimaryHDU(data=data, header=header).writeto(path, overwrite=True)
        paths.append(str(path))
    return {"root": str(tmp_path), "data_dir": str(data_dir), "files": paths}


@pytest.fixture
def cli_args():
    return make_cli_args()


@pytest.fixture
def golden_dir():
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    return GOLDEN_DIR
