"""Tests for region statistics (cropped bounding-box masks)."""
from __future__ import annotations

import numpy as np

from disco.core.regions import region_mask, region_mask_cropped, region_stats


def test_ellipse_region_stats():
    data = np.zeros((100, 100), dtype=np.float32)
    data[40:60, 40:60] = 5.0
    region = {"type": "ellipse", "cx": 50, "cy": 50, "rx": 12, "ry": 12, "pa": 0}
    stats = region_stats(data, region, pixel_scale=0.05)
    assert stats["npix"] > 50
    assert stats["peak"] == 5.0
    assert stats["mean"] > 0


def test_rectangle_mask():
    mask = region_mask((50, 50), {"type": "rectangle", "x0": 10, "y0": 10, "x1": 20, "y1": 20})
    assert mask.sum() == 11 * 11


def test_annulus_mask():
    mask = region_mask((80, 80), {"type": "annulus", "cx": 40, "cy": 40, "r_in": 5, "r_out": 15})
    assert mask.sum() > 0


def test_cropped_matches_full_mask():
    rng = np.random.default_rng(0)
    data = rng.normal(size=(200, 200)).astype(np.float32)
    region = {"type": "ellipse", "cx": 100, "cy": 80, "rx": 25, "ry": 15, "pa": 30}
    full = region_mask(data.shape, region)
    local, bbox = region_mask_cropped(data.shape, region)
    assert bbox is not None
    ys, ye, xs, xe = bbox
    reconstructed = np.zeros_like(full)
    reconstructed[ys:ye, xs:xe] = local
    assert np.array_equal(full, reconstructed)
    stats_a = region_stats(data, region, pixel_scale=0.1)
    # Manual via full mask
    vals = data[full]
    vals = vals[np.isfinite(vals)]
    assert stats_a["npix"] == int(vals.size)
    assert abs(stats_a["sum"] - float(np.sum(vals))) < 1e-3


def test_off_image_region_empty():
    data = np.ones((50, 50), dtype=np.float32)
    region = {"type": "ellipse", "cx": 5000, "cy": 5000, "rx": 10, "ry": 10, "pa": 0}
    stats = region_stats(data, region)
    assert stats["npix"] == 0
    local, bbox = region_mask_cropped(data.shape, region)
    assert local is None and bbox is None


def test_polygon_region():
    data = np.ones((40, 40), dtype=np.float32)
    region = {
        "type": "polygon",
        "points": [{"x": 5, "y": 5}, {"x": 20, "y": 5}, {"x": 20, "y": 20}, {"x": 5, "y": 20}],
    }
    stats = region_stats(data, region)
    assert stats["npix"] > 100
