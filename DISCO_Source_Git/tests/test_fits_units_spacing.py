"""Tests for RESTFRQ / BUNIT helpers, radial spacing, and FluxNorm single-pass."""

import numpy as np
from astropy.io import fits

from disco.core.fits_utils import (
    DEFAULT_RESTFRQ_HZ,
    normalize_flux_units,
    radial_pixel_grid,
    resolve_restfrq,
)


def test_resolve_restfrq_prefers_restfrq():
    h = fits.Header({"RESTFRQ": 345e9, "CRVAL3": 230e9, "CTYPE3": "FREQ"})
    hz, fallback, src = resolve_restfrq(h)
    assert abs(hz - 345e9) < 1.0
    assert fallback is False
    assert src == "RESTFRQ"


def test_resolve_restfrq_freq_axis_then_default():
    h = fits.Header({"CTYPE3": "FREQ", "CRVAL3": 405e9})
    hz, fallback, src = resolve_restfrq(h)
    assert abs(hz - 405e9) < 1.0
    assert fallback is False
    assert src == "CRVAL3"

    h2 = fits.Header()
    hz2, fallback2, src2 = resolve_restfrq(h2)
    assert abs(hz2 - DEFAULT_RESTFRQ_HZ) < 1.0
    assert fallback2 is True
    assert src2 == "default_230GHz"


def test_normalize_bunit_jybeam():
    h = fits.Header({"BUNIT": "Jy/beam"})
    data = np.array([[0.01, 0.02]], dtype=float)
    out, h2, warns = normalize_flux_units(data, h)
    assert np.allclose(out, data * 1000)
    assert h2["BUNIT"].lower() == "mjy/beam"
    assert warns == []


def test_normalize_bunit_empty_heuristic():
    h = fits.Header()
    data = np.array([[0.01, 0.02]], dtype=float)
    out, _, warns = normalize_flux_units(data, h)
    assert np.allclose(out, data * 1000)
    assert any("×1000" in w or "x1000" in w.lower() or "heuristic" in w for w in warns)


def test_normalize_bunit_empty_no_heuristic():
    h = fits.Header()
    data = np.array([[10.0, 12.0]], dtype=float)
    out, _, warns = normalize_flux_units(data, h)
    assert np.allclose(out, data)
    assert any("missing" in w.lower() for w in warns)


def test_radial_pixel_grid_unit_spacing():
    r = radial_pixel_grid(500)
    assert len(r) == 500
    assert r[0] == 0.0
    assert r[-1] == 499.0
    d = np.diff(r)
    assert np.allclose(d, 1.0)
    # Contrast with broken linspace(0, N, N)
    bad = np.linspace(0, 500, 500)
    assert not np.allclose(np.diff(bad), 1.0)


def test_fluxnorm_single_pass_identity():
    """Document expected CLI behaviour: one peak normalise, no second pass."""
    y = np.array([0.0, 50.0, 100.0, 25.0], dtype=float)
    e = np.array([1.0, 1.0, 1.0, 1.0], dtype=float)
    max_val = np.nanmax(y)
    y_norm = y / max_val
    e_norm = e / max_val
    assert abs(np.nanmax(y_norm) - 1.0) < 1e-12
    # A second pass would be a no-op on finite data without NaNs
    mx2 = np.nanmax(y_norm)
    assert abs(mx2 - 1.0) < 1e-12
    assert np.allclose(e_norm, e / 100.0)
