"""Tests for shared CNN preprocess and geometry uncertainty helpers."""

import numpy as np
from astropy.io import fits

from disco.core.cnn_preprocess import (
    CENTER_SCALE,
    decode_labels,
    elliptical_beam_map,
    encode_labels,
    fov_offset_to_pixels,
    normalize_percentile,
    scale_map,
    stack_cnn_channels,
)
from disco.core.cnn_inference import prepare_cnn_inputs, predict_with_cnn
from disco.core.optimization import estimate_geometry_errors, geometric_loss


def test_encode_decode_roundtrip():
    vec = encode_labels(45.0, 90.0, dx_fov=0.07, dy_fov=-0.07)
    assert vec.shape == (5,)
    out = decode_labels(vec, crop_half_pix=100.0)
    assert abs(out["inclination"] - 45.0) < 1e-5
    assert abs(out["pa"] - 90.0) < 1e-4
    assert abs(out["dx_fov"] - 0.07) < 1e-6
    assert abs(out["dx_pix"] - 7.0) < 1e-6


def test_elliptical_beam_not_circular():
    cell = 0.02
    circ = elliptical_beam_map(0.2, 0.2, 0.0, cell)
    ell = elliptical_beam_map(0.3, 0.1, 30.0, cell)
    assert circ.shape == (128, 128)
    assert abs(circ.max() - 1.0) < 1e-5
    # Elliptical map should differ from circular
    assert np.mean(np.abs(circ - ell)) > 1e-3


def test_prepare_cnn_inputs_matches_stack():
    rng = np.random.RandomState(0)
    data = rng.rand(256, 256).astype(np.float32)
    header = fits.Header({"BMAJ": 1e-4, "BMIN": 8e-5, "BPA": 15.0})
    chw, half = prepare_cnn_inputs(data, header, pixel_scale=0.01, cx=128, cy=128, search_rad=0.8)
    assert chw is not None
    assert chw.shape == (3, 128, 128)
    assert half > 0
    assert 0.0 <= chw[0].min() and chw[0].max() <= 1.0


def test_predict_empty_crop_arity():
    class Dummy:
        def eval(self):
            return self

    data = np.zeros((10, 10), dtype=np.float32)
    header = fits.Header({"BMAJ": 1e-5, "BMIN": 1e-5, "BPA": 0.0})
    result = predict_with_cnn(
        data, header, pixel_scale=1.0, cx=-1000, cy=-1000, search_rad=0.1, model=Dummy()
    )
    assert len(result) == 4


def test_fov_offset_scaling():
    dx, dy = fov_offset_to_pixels(0.14, -0.14, 50.0)
    assert abs(dx - 7.0) < 1e-9
    assert abs(dy + 7.0) < 1e-9
    assert abs(CENTER_SCALE - 0.14) < 1e-12


def _synthetic_inclined_disk(size=120, incl=40.0, pa=70.0, noise=0.02):
    y, x = np.mgrid[:size, :size]
    cy = cx = size / 2.0
    pa_r = np.radians(pa)
    cos_i = np.cos(np.radians(incl))
    x0 = x - cx
    y0 = y - cy
    rmaj = -x0 * np.sin(pa_r) + y0 * np.cos(pa_r)
    rmin = (x0 * np.cos(pa_r) + y0 * np.sin(pa_r)) / max(cos_i, 0.05)
    r = np.sqrt(rmaj**2 + rmin**2)
    disk = np.exp(-(r / 25.0) ** 2)
    rng = np.random.RandomState(1)
    return (disk + rng.normal(0, noise, disk.shape)).astype(np.float64)


def test_estimate_geometry_errors_finite():
    data = _synthetic_inclined_disk()
    err_i, err_pa = estimate_geometry_errors(
        data, pixel_scale=0.01, cx=60.0, cy=60.0, incl=40.0, pa=70.0, rmin=0.05, rmax=0.6
    )
    assert 0.3 <= err_i <= 10.0
    assert 0.3 <= err_pa <= 10.0


def test_geometric_loss_minimum_near_truth():
    data = _synthetic_inclined_disk(incl=35.0, pa=20.0, noise=0.01)
    size = data.shape[0]
    crop_rad = size // 2
    largs = (data, crop_rad, crop_rad, crop_rad, 5.0, 55.0, 80, 1)
    loss_true = geometric_loss([35.0, 20.0, 0.0, 0.0], *largs)
    loss_bad = geometric_loss([70.0, 100.0, 0.0, 0.0], *largs)
    assert np.isfinite(loss_true)
    assert loss_true < loss_bad
