"""Tests for FITS I/O helpers and unit handling."""
from __future__ import annotations

import numpy as np
from astropy.io import fits

from disco.core.fits_utils import auto_detect_parameters, find_center_robust


def test_find_center_near_true(synthetic_disk):
    d = synthetic_disk
    cx, cy = find_center_robust(d["data"], d["pixel_scale"], d["header"])
    assert abs(cx - d["cx"]) < 15
    assert abs(cy - d["cy"]) < 15


def test_auto_detect_parameters(synthetic_disk):
    d = synthetic_disk
    rmin, rout, bmaj = auto_detect_parameters(
        d["data"], d["header"], d["pixel_scale"], d["cx"], d["cy"]
    )
    assert rmin > 0
    assert rout > rmin
    assert rout < 8.0
    assert bmaj > 0


def test_synthetic_fits_roundtrip(synthetic_fits_path):
    with fits.open(synthetic_fits_path) as hdul:
        data = np.squeeze(hdul[0].data)
        header = hdul[0].header
    assert data.ndim == 2
    assert header["BUNIT"] == "mJy/beam"
    assert "BMAJ" in header
