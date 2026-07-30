"""Region masks and statistics — cropped bounding-box implementation."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np


def _empty_stats() -> dict[str, Any]:
    return {
        "npix": 0, "sum": 0.0, "mean": 0.0, "rms": 0.0,
        "peak": 0.0, "min": 0.0, "flux": 0.0,
    }


def _clamp_bbox(ny: int, nx: int, y0: float, y1: float, x0: float, x1: float):
    """Return integer (ys, ye, xs, xe) clamped to image, or None if empty."""
    ys = max(0, int(np.floor(min(y0, y1))))
    ye = min(ny, int(np.ceil(max(y0, y1))) + 1)
    xs = max(0, int(np.floor(min(x0, x1))))
    xe = min(nx, int(np.ceil(max(x0, x1))) + 1)
    if ye <= ys or xe <= xs:
        return None
    return ys, ye, xs, xe


def _region_bbox(shape, region: dict) -> Optional[tuple]:
    ny, nx = shape
    rtype = region.get("type", "ellipse")
    pad = 2.0
    if rtype == "ellipse":
        cx, cy = float(region["cx"]), float(region["cy"])
        rx = float(region.get("rx", region.get("r", 10)))
        ry = float(region.get("ry", region.get("r", 10)))
        # Axis-aligned bbox of rotated ellipse = max extent
        rmax = max(rx, ry) + pad
        return _clamp_bbox(ny, nx, cy - rmax, cy + rmax, cx - rmax, cx + rmax)
    if rtype == "rectangle":
        return _clamp_bbox(
            ny, nx,
            float(region["y0"]) - pad, float(region["y1"]) + pad,
            float(region["x0"]) - pad, float(region["x1"]) + pad,
        )
    if rtype == "annulus":
        cx, cy = float(region["cx"]), float(region["cy"])
        r_out = float(region["r_out"]) + pad
        return _clamp_bbox(ny, nx, cy - r_out, cy + r_out, cx - r_out, cx + r_out)
    if rtype == "wedge":
        cx, cy = float(region["cx"]), float(region["cy"])
        r_out = float(region["r_out"]) + pad
        return _clamp_bbox(ny, nx, cy - r_out, cy + r_out, cx - r_out, cx + r_out)
    if rtype == "polygon":
        pts = region.get("points", [])
        if len(pts) < 3:
            return None
        xs = [float(p["x"]) for p in pts]
        ys = [float(p["y"]) for p in pts]
        return _clamp_bbox(ny, nx, min(ys) - pad, max(ys) + pad, min(xs) - pad, max(xs) + pad)
    raise ValueError(f"Unknown region type: {rtype}")


def _ellipse_mask_local(ys, ye, xs, xe, cx, cy, rx, ry, pa_deg=0.0):
    y, x = np.ogrid[ys:ye, xs:xe]
    pa = np.radians(pa_deg)
    dx = x - cx
    dy = y - cy
    xr = dx * np.cos(pa) + dy * np.sin(pa)
    yr = -dx * np.sin(pa) + dy * np.cos(pa)
    return (xr / max(rx, 1e-6)) ** 2 + (yr / max(ry, 1e-6)) ** 2 <= 1.0


def _rect_mask_local(ys, ye, xs, xe, x0, y0, x1, y1):
    y, x = np.ogrid[ys:ye, xs:xe]
    xmin, xmax = min(x0, x1), max(x0, x1)
    ymin, ymax = min(y0, y1), max(y0, y1)
    return (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)


def _annulus_mask_local(ys, ye, xs, xe, cx, cy, r_in, r_out):
    y, x = np.ogrid[ys:ye, xs:xe]
    r = np.hypot(x - cx, y - cy)
    return (r >= r_in) & (r <= r_out)


def _wedge_mask_local(ys, ye, xs, xe, cx, cy, r_in, r_out, theta0, theta1):
    y, x = np.ogrid[ys:ye, xs:xe]
    dx = x - cx
    dy = y - cy
    r = np.hypot(dx, dy)
    ang = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    t0 = theta0 % 360.0
    t1 = theta1 % 360.0
    if t0 <= t1:
        ang_ok = (ang >= t0) & (ang <= t1)
    else:
        ang_ok = (ang >= t0) | (ang <= t1)
    return (r >= r_in) & (r <= r_out) & ang_ok


def _polygon_mask_local(ys, ye, xs, xe, points):
    from matplotlib.path import Path

    verts = [(p["x"], p["y"]) for p in points]
    if len(verts) < 3:
        return np.zeros((ye - ys, xe - xs), dtype=bool)
    path = Path(verts)
    yy, xx = np.mgrid[ys:ye, xs:xe]
    coords = np.column_stack([xx.ravel(), yy.ravel()])
    return path.contains_points(coords).reshape((ye - ys, xe - xs))


def region_mask_cropped(shape, region: dict):
    """
    Build a boolean mask only inside the region's bounding box.

    Returns (mask, (ys, ye, xs, xe)) or (None, None) if the region is empty / off-image.
    """
    bbox = _region_bbox(shape, region)
    if bbox is None:
        return None, None
    ys, ye, xs, xe = bbox
    rtype = region.get("type", "ellipse")
    if rtype == "ellipse":
        # Client stores Konva display rotation (y↓); array PA is the opposite sign.
        if "pa" in region:
            pa = float(region["pa"])
        elif "rotation" in region:
            pa = -float(region["rotation"])
        else:
            pa = 0.0
        mask = _ellipse_mask_local(
            ys, ye, xs, xe,
            float(region["cx"]), float(region["cy"]),
            float(region.get("rx", region.get("r", 10))),
            float(region.get("ry", region.get("r", 10))),
            pa,
        )
    elif rtype == "rectangle":
        mask = _rect_mask_local(
            ys, ye, xs, xe,
            float(region["x0"]), float(region["y0"]),
            float(region["x1"]), float(region["y1"]),
        )
    elif rtype == "annulus":
        mask = _annulus_mask_local(
            ys, ye, xs, xe,
            float(region["cx"]), float(region["cy"]),
            float(region["r_in"]), float(region["r_out"]),
        )
    elif rtype == "wedge":
        mask = _wedge_mask_local(
            ys, ye, xs, xe,
            float(region["cx"]), float(region["cy"]),
            float(region["r_in"]), float(region["r_out"]),
            float(region["theta0"]), float(region["theta1"]),
        )
    elif rtype == "polygon":
        mask = _polygon_mask_local(ys, ye, xs, xe, region.get("points", []))
    else:
        raise ValueError(f"Unknown region type: {rtype}")
    return mask, (ys, ye, xs, xe)


def region_mask(shape, region: dict) -> np.ndarray:
    """Full-size boolean mask (compat). Prefer region_mask_cropped for large images."""
    ny, nx = shape
    local, bbox = region_mask_cropped(shape, region)
    out = np.zeros((ny, nx), dtype=bool)
    if local is None or bbox is None:
        return out
    ys, ye, xs, xe = bbox
    out[ys:ye, xs:xe] = local
    return out


def region_stats(
    data: np.ndarray,
    region: dict,
    pixel_scale: float = 1.0,
    beam_area_pix: float | None = None,
) -> dict[str, Any]:
    mask, bbox = region_mask_cropped(data.shape, region)
    if mask is None or bbox is None:
        return _empty_stats()
    ys, ye, xs, xe = bbox
    vals = data[ys:ye, xs:xe][mask]
    vals = vals[np.isfinite(vals)]
    n = int(vals.size)
    if n == 0:
        return _empty_stats()
    total = float(np.sum(vals))
    mean = float(np.mean(vals))
    rms = float(np.std(vals))
    peak = float(np.max(vals))
    vmin = float(np.min(vals))
    if beam_area_pix and beam_area_pix > 0:
        flux = total / beam_area_pix
    else:
        flux = total * (pixel_scale ** 2)
    return {
        "npix": n,
        "sum": total,
        "mean": mean,
        "rms": rms,
        "peak": peak,
        "min": vmin,
        "flux": float(flux),
    }
