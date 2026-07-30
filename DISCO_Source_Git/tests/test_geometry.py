"""Regression tests for geometric loss and optimization helpers."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from disco.core.optimization import geometric_loss


def test_geometric_loss_finite(synthetic_disk):
    d = synthetic_disk
    data = d["data"]
    cy, cx = d["cy"], d["cx"]
    pad = 50
    d_pad = np.pad(data, pad, mode="constant", constant_values=0)
    crop_rad = 80
    dc = d_pad[
        int(cy) + pad - crop_rad : int(cy) + pad + crop_rad,
        int(cx) + pad - crop_rad : int(cx) + pad + crop_rad,
    ]
    rmin_pix = 0.3 / d["pixel_scale"]
    rmax_pix = 3.0 / d["pixel_scale"]
    loss = geometric_loss(
        [40.0, 90.0, 0.0, 0.0],
        dc, crop_rad, crop_rad, crop_rad,
        rmin_pix, rmax_pix, dim=100, order=1,
    )
    assert np.isfinite(loss)
    assert loss < 1e11


def test_geometric_loss_prefers_true_inclination(synthetic_disk, golden_dir):
    d = synthetic_disk
    data = d["data"]
    cy, cx = d["cy"], d["cx"]
    pad = 50
    d_pad = np.pad(data, pad, mode="constant", constant_values=0)
    crop_rad = 80
    dc = d_pad[
        int(cy) + pad - crop_rad : int(cy) + pad + crop_rad,
        int(cx) + pad - crop_rad : int(cx) + pad + crop_rad,
    ]
    rmin_pix = 0.3 / d["pixel_scale"]
    rmax_pix = 3.0 / d["pixel_scale"]
    args = (dc, crop_rad, crop_rad, crop_rad, rmin_pix, rmax_pix, 80, 1)
    losses = {}
    for incl in (10.0, 40.0, 70.0):
        losses[str(incl)] = float(geometric_loss([incl, 90.0, 0.0, 0.0], *args))
    best = min(losses, key=losses.get)
    assert best == "40.0", f"Expected true incl to win, got {best}: {losses}"
    path = os.path.join(golden_dir, "geometry_losses.json")
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(losses, f, indent=2)
        pytest.skip("Golden file created; re-run to compare")
    with open(path) as f:
        golden = json.load(f)
    for k in losses:
        assert abs(losses[k] - golden[k]) / max(golden[k], 1e-9) < 0.05
