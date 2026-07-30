"""Deprojection and polar remapping (shared by CLI and GUI)."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates


def deproject_image(data, cx, cy, incl, pa, dim=1000, order=3, cval=0.0):
    """
    Deproject a disk image centered at (cx, cy) in array coordinates.
    Note: cy is in array/FITS y (origin lower), matching CLI usage.

    PA is the position angle of the major axis measured East of North with
    East = -x, i.e. output offset (s, t) maps to the sky offset
    (dx, dy) = R(pa) . (s cos incl, t). Returns a dim x dim image whose pixel
    scale equals the input pixel scale (radii are true disk radii).
    """
    pa_rad = np.radians(pa)
    incl_rad = np.radians(incl)
    half = dim / 2.0
    x = np.arange(dim) - half
    X, Y = np.meshgrid(x, x)
    Xc = X * np.cos(incl_rad)
    Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
    Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y
    coords = [Yrot + cy, -Xrot + cx]
    deproj = map_coordinates(data, coords, order=order, mode="constant", cval=cval)
    return np.fliplr(deproj)


def deprojection_crop_size(dim, incl, margin=8):
    """
    Smallest even crop size that fully covers the sampling footprint of a
    dim x dim deprojection: the grid corner (dim/2, dim/2) is sampled at a
    sky distance of (dim/2) * hypot(cos incl, 1) from the center.
    """
    cos_i = max(float(np.cos(np.radians(incl))), 0.05)
    needed = (dim / 2.0) * float(np.hypot(cos_i, 1.0)) + margin
    size = int(np.ceil(needed)) * 2
    return size + (size % 2)


def to_polar(deproj, n_theta=181, order=1):
    """
    Convert square deprojected image to polar (theta, radius).

    Returns an array of shape (n_theta, n_r) with azimuth along rows and
    radius along columns (R → +x, θ → +y after display flip).
    """
    dim = deproj.shape[0]
    half = dim / 2.0
    max_radius_pix = np.hypot(half, half)
    # Enough radial samples that a Rout crop stays wider than it is tall
    n_steps = max(int(max_radius_pix), n_theta * 2)
    r_full = np.linspace(0, max_radius_pix, n_steps)
    th = np.linspace(-180, 180, n_theta)
    R, TH = np.meshgrid(r_full, th)
    Xd = R * np.cos(np.radians(TH))
    Yd = R * np.sin(np.radians(TH))
    coords_polar = [Yd + half, Xd + half]
    polar = map_coordinates(deproj, coords_polar, order=order, mode="constant", cval=np.nan)
    polar = np.flipud(polar)
    return polar, r_full


def widen_polar(polar, min_aspect=2.2):
    """Upsample the radius axis so the polar map is wider than it is tall."""
    polar = np.asarray(polar, dtype=np.float32)
    if polar.ndim != 2 or polar.shape[1] < 2:
        return polar
    n_th, n_r = polar.shape
    target_w = max(n_r, int(np.ceil(n_th * min_aspect)))
    if target_w <= n_r:
        return polar
    x_old = np.linspace(0.0, 1.0, n_r)
    x_new = np.linspace(0.0, 1.0, target_w)
    out = np.empty((n_th, target_w), dtype=np.float32)
    for i in range(n_th):
        row = polar[i]
        finite = np.isfinite(row)
        fill = np.where(finite, row, 0.0)
        sampled = np.interp(x_new, x_old, fill)
        weight = np.interp(x_new, x_old, finite.astype(np.float64))
        out[i] = np.where(weight > 0.5, sampled, np.nan)
    return out


def crop_around_center(data, cx, cy, crop_size):
    """
    Pad and crop a square around (cx, cy) with sub-pixel offsets preserved.
    cx/cy are in array coordinates (origin lower-left for FITS-style).
    Returns (crop, local_cx, local_cy).
    """
    crop_size = int(crop_size)
    if crop_size % 2 != 0:
        crop_size += 1
    crop_rad = crop_size // 2
    pad = crop_rad
    d_pad = np.pad(data, pad, mode="constant", constant_values=0)
    y_start_int = int(cy) + pad - crop_rad
    x_start_int = int(cx) + pad - crop_rad
    local_cy = (cy + pad) - y_start_int
    local_cx = (cx + pad) - x_start_int
    dc = d_pad[y_start_int:y_start_int + crop_size, x_start_int:x_start_int + crop_size]
    if dc.shape != (crop_size, crop_size):
        temp = np.zeros((crop_size, crop_size), dtype=data.dtype)
        h, w = dc.shape
        temp[0:h, 0:w] = dc
        dc = temp
    return dc, float(local_cx), float(local_cy)


def adaptive_crop_size(data_shape, rout_pix, min_size=256, max_size=2000):
    """Choose crop size based on Rout and image size (avoids fixed 2000)."""
    ny, nx = data_shape
    needed = int(max(rout_pix * 2.4, 64)) + 20
    size = int(np.clip(needed, min_size, min(max_size, max(ny, nx) + 200)))
    if size % 2:
        size += 1
    return size
