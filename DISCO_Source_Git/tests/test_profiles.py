"""Regression tests for radial profile extraction and Gaussian ring fit."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest
from scipy.optimize import curve_fit

from disco.core.fits_utils import extract_profile


def gaussian(x, a, x0, sigma, c):
    return a * np.exp(-(x - x0) ** 2 / (2 * sigma ** 2)) + c


def test_extract_profile_shape(synthetic_disk):
    d = synthetic_disk
    r, tb, err = extract_profile(
        d["data"], d["header"], incl=40.0, pa=90.0,
        pixel_scale=d["pixel_scale"], cx=d["cx"], cy=d["cy"],
        limit_arcsec=4.0,
    )
    assert len(r) == len(tb) == len(err)
    assert len(r) > 10
    assert r[0] >= 0
    assert r[-1] <= 4.0 + 1e-6
    assert np.all(np.isfinite(tb))
    assert np.nanmax(tb) > 0


def test_extract_profile_golden(synthetic_disk, golden_dir):
    d = synthetic_disk
    r, tb, err = extract_profile(
        d["data"], d["header"], incl=40.0, pa=90.0,
        pixel_scale=d["pixel_scale"], cx=d["cx"], cy=d["cy"],
        limit_arcsec=3.0,
    )
    path = os.path.join(golden_dir, "profile_synth.npz")
    if not os.path.exists(path):
        np.savez_compressed(path, radius=r, tb=tb, err=err)
        pytest.skip("Golden file created; re-run to compare")
    golden = np.load(path)
    np.testing.assert_allclose(r, golden["radius"], rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(tb, golden["tb"], rtol=1e-4, atol=1e-5)
    np.testing.assert_allclose(err, golden["err"], rtol=1e-3, atol=1e-5)


def test_gaussian_ring_fit(synthetic_disk, golden_dir):
    d = synthetic_disk
    r, tb, _ = extract_profile(
        d["data"], d["header"], incl=40.0, pa=90.0,
        pixel_scale=d["pixel_scale"], cx=d["cx"], cy=d["cy"],
        limit_arcsec=4.0,
    )
    fit_rmin, fit_rmax = 0.8, 2.2
    mask = (r >= fit_rmin) & (r <= fit_rmax)
    x_region, y_region = r[mask], tb[mask]
    assert len(y_region) > 5
    idx_max = int(np.argmax(y_region))
    p0 = [float(y_region[idx_max]), float(x_region[idx_max]), (fit_rmax - fit_rmin) / 4, 0.0]
    popt, _ = curve_fit(gaussian, x_region, y_region, p0=p0, maxfev=2000)
    stats = {
        "peak_radius": float(popt[1]),
        "fwhm": float(2.355 * abs(popt[2])),
        "peak_intensity": float(popt[0]),
    }
    assert 0.5 < stats["peak_radius"] < 3.0
    assert stats["fwhm"] > 0
    path = os.path.join(golden_dir, "gaussian_fit.json")
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(stats, f, indent=2)
        pytest.skip("Golden file created; re-run to compare")
    with open(path) as f:
        golden = json.load(f)
    assert abs(stats["peak_radius"] - golden["peak_radius"]) < 0.15
    assert abs(stats["fwhm"] - golden["fwhm"]) < 0.25
