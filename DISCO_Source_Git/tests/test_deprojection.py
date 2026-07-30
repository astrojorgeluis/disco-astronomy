"""
Deprojection conventions and product geometry.

The PA convention is shared by three independent implementations (core
deprojection, the geometric loss used by the optimizer, and the client
overlay), so it is pinned here: PA is the position angle of the major axis
measured East of North with East = -x, i.e. a deprojected offset (s, t) is
sampled at the sky offset R(pa) . (s cos incl, t).
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import map_coordinates

from disco.core.geometry import deproject_image, deprojection_crop_size
from disco.core.optimization import geometric_loss
from disco.core.profiles import run_analysis_pipeline
from tests.conftest import make_synthetic_disk

CARTESIAN = ("data", "deproj", "model", "residuals")


def ring_azimuthal_scatter(deproj, ring_pix):
    """Relative peak-to-mean scatter of a ring sampled around the deprojection."""
    dim = deproj.shape[0]
    half = dim / 2.0
    th = np.linspace(0, 2 * np.pi, 181)
    vals = map_coordinates(
        np.nan_to_num(deproj),
        [ring_pix * np.sin(th) + half, ring_pix * np.cos(th) + half],
        order=1,
    )
    mean = float(np.mean(vals))
    return float(np.std(vals)) / max(abs(mean), 1e-9)


@pytest.mark.parametrize("incl,pa", [(35.0, 0.0), (55.0, 35.0), (70.0, 120.0)])
def test_deprojection_circularizes_ring(incl, pa):
    """With the true geometry the ring becomes axisymmetric; -PA must not."""
    rout_pix = 60.0
    data, _ = make_synthetic_disk(incl=incl, pa=pa, rout_pix=rout_pix, noise=0.0)
    ring = rout_pix * 0.55
    good = deproject_image(data, 128.0, 128.0, incl, pa, dim=256)
    assert ring_azimuthal_scatter(good, ring) < 0.02
    if pa % 90 != 0:
        mirrored = deproject_image(data, 128.0, 128.0, incl, -pa, dim=256)
        assert ring_azimuthal_scatter(mirrored, ring) > 0.1


def test_geometric_loss_shares_pa_convention():
    """The optimizer loss must be minimal at the true PA, not the mirrored one."""
    incl, pa, rout_pix = 55.0, 35.0, 60.0
    data, _ = make_synthetic_disk(incl=incl, pa=pa, rout_pix=rout_pix, noise=0.0)
    args = (data, 128.0, 128.0, 100, 0.0, 0.0, 200, 1)
    true_loss = geometric_loss([incl, pa, 0.0, 0.0], *args)
    mirrored_loss = geometric_loss([incl, -pa % 180, 0.0, 0.0], *args)
    assert true_loss < mirrored_loss / 5


def test_cartesian_products_share_fov():
    data, header = make_synthetic_disk(incl=70.0, pa=120.0, noise=0.0)
    out = run_analysis_pipeline(
        data, header, cx=128.0, cy=128.0, pa=120.0, incl=70.0, rout=1.5,
    )
    shapes = {p: out["results"][p].shape for p in CARTESIAN}
    assert len(set(shapes.values())) == 1, shapes
    ref = out["extents"]["deproj"]
    for product in CARTESIAN:
        assert out["extents"][product] == ref


def test_deprojection_has_no_uncovered_corners():
    """
    The source crop must cover the whole deprojected grid: an inclined disk
    used to leave a rotated square of valid data inside a black canvas.
    """
    data, header = make_synthetic_disk(size=512, cx=256.0, cy=256.0, incl=75.0, pa=42.0, noise=0.0)
    out = run_analysis_pipeline(
        data, header, cx=256.0, cy=256.0, pa=42.0, incl=75.0, rout=1.2,
    )
    for product in ("data", "deproj"):
        assert np.isfinite(out["results"][product]).all(), product


def test_uncovered_pixels_are_nan_not_zero():
    """Off-edge disks yield transparent (NaN) pixels rather than fake zeros."""
    data, header = make_synthetic_disk(size=256, cx=40.0, cy=40.0, incl=45.0, pa=20.0, noise=0.0)
    out = run_analysis_pipeline(
        data, header, cx=40.0, cy=40.0, pa=20.0, incl=45.0, rout=1.5,
    )
    deproj = out["results"]["deproj"]
    assert np.isnan(deproj).any()
    assert np.isfinite(deproj).any()


def test_offcenter_disk_is_centered_by_array_coords():
    """
    cx/cy are array coords end to end: an off-center disk must still deproject
    into a ring centered on the grid (a y-flip would break axisymmetry).
    """
    rout_pix = 60.0
    data, header = make_synthetic_disk(
        size=512, cx=180.0, cy=140.0, incl=50.0, pa=25.0, rout_pix=rout_pix, noise=0.0,
    )
    out = run_analysis_pipeline(
        data, header, cx=180.0, cy=140.0, pa=25.0, incl=50.0, rout=rout_pix * 2 * 0.05,
    )
    assert ring_azimuthal_scatter(out["results"]["deproj"], rout_pix * 0.55) < 0.02


def test_profile_is_json_safe():
    import json

    data, header = make_synthetic_disk(size=256, cx=30.0, cy=30.0, incl=60.0, pa=75.0)
    out = run_analysis_pipeline(
        data, header, cx=30.0, cy=30.0, pa=75.0, incl=60.0, rout=1.8,
    )
    text = json.dumps(out["profile"])
    assert "NaN" not in text and "Infinity" not in text


@pytest.mark.parametrize("incl", [0.0, 45.0, 80.0])
def test_crop_size_covers_grid_corner(incl):
    dim = 200
    size = deprojection_crop_size(dim, incl)
    cos_i = max(np.cos(np.radians(incl)), 0.05)
    corner = (dim / 2.0) * np.hypot(cos_i, 1.0)
    assert size % 2 == 0
    assert size / 2.0 >= corner


def test_optimize_recovers_geometry():
    """API optimize recovers incl/PA from a poor starting guess on a synthetic ring."""
    import time

    from disco.core.units import get_pixel_scale_arcsec
    from disco.server.routers.analysis import optimize_geometry
    from disco.server.schemas import OptimizeParams
    from disco.server.session import ImageEntry, store

    incl, pa, rout_pix = 55.0, 35.0, 60.0
    data, header = make_synthetic_disk(incl=incl, pa=pa, rout_pix=rout_pix, noise=0.0)
    ps = get_pixel_scale_arcsec(header)
    img = ImageEntry(
        id="opt-test", filename="synth.fits", path="", data=data, header=header,
        pixel_scale=ps, created_at=time.time(),
    )
    store.images[img.id] = img
    store.active_id = img.id
    try:
        out = optimize_geometry(OptimizeParams(
            image_id=img.id, cx=128.0, cy=128.0, pa=10.0, incl=30.0,
            rout=rout_pix * ps, fit_rmin=0.0, fit_rmax=0.0,
        ))
        assert abs(out["optimized_incl"] - incl) < 3.0
        assert abs(out["optimized_pa"] - pa) < 5.0
        assert abs(out["optimized_cx"] - 128.0) < 3.0
        assert abs(out["optimized_cy"] - 128.0) < 3.0
    finally:
        store.images.pop(img.id, None)
        store.active_id = None
