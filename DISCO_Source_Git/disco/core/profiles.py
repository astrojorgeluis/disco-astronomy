"""Radial profiles, model/residuals, Gaussian ring fit, and analysis pipeline."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.optimize import curve_fit

from disco.core.geometry import (
    crop_around_center,
    deproject_image,
    deprojection_crop_size,
    to_polar,
    widen_polar,
)
from disco.core.units import beam_info_from_header, get_pixel_scale_arcsec, mjy_to_tb


def gaussian(x, a, x0, sigma, c):
    return a * np.exp(-(x - x0) ** 2 / (2 * sigma ** 2)) + c


def _nanmean_axis0(arr):
    """Mean over axis 0 ignoring NaN; all-NaN columns give NaN without warnings."""
    a = np.asarray(arr, dtype=np.float64)
    good = np.isfinite(a)
    count = good.sum(axis=0)
    total = np.where(good, a, 0.0).sum(axis=0)
    out = np.full(a.shape[1], np.nan)
    np.divide(total, count, out=out, where=count > 0)
    return out


def extract_profile(data, header, incl, pa, pixel_scale, cx, cy, limit_arcsec):
    """Azimuthally-averaged brightness-temperature profile (CLI-compatible)."""
    pa_rad, incl_rad = np.radians(pa), np.radians(incl)
    dim = 1000
    X, Y = np.meshgrid(np.arange(dim) - dim / 2.0, np.arange(dim) - dim / 2.0)
    Xc = X * np.cos(incl_rad)
    Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
    Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y
    coords = [Yrot + cy, -Xrot + cx]
    deproj = map_coordinates(data, coords, order=3, mode="constant", cval=0.0)

    max_radius_pix = int(dim / 2.0)
    R, TH = np.meshgrid(
        np.linspace(0, max_radius_pix, max_radius_pix),
        np.linspace(-180, 180, 361),
    )
    polar_coords = [R * np.sin(np.radians(TH)) + dim / 2.0, R * np.cos(np.radians(TH)) + dim / 2.0]
    polar_full = map_coordinates(np.fliplr(deproj), polar_coords, order=1, mode="constant", cval=0.0)
    polar_flipped = np.flipud(polar_full)
    prof_full = np.nanmean(polar_flipped, axis=0)
    std_full = np.nanstd(polar_flipped, axis=0)

    r_arcsec = np.linspace(0, max_radius_pix, max_radius_pix) * pixel_scale
    bmaj = header.get("BMAJ", 0) * 3600
    if bmaj > 0:
        n_eff = np.maximum(1.0, 2 * np.pi * np.maximum(r_arcsec, pixel_scale) / bmaj)
    else:
        n_eff = np.ones_like(r_arcsec) * 361.0
    err_full = std_full / np.sqrt(n_eff)

    tb_prof = mjy_to_tb(prof_full, header)
    # Scalar factor so errors share TB units even where intensity ≈ 0
    factor = float(mjy_to_tb(np.array([1.0], dtype=float), header)[0])
    tb_err = err_full * factor

    limit_idx = min(np.searchsorted(r_arcsec, limit_arcsec), len(r_arcsec))
    return r_arcsec[:limit_idx], tb_prof[:limit_idx], tb_err[:limit_idx]


def measure_rout_deproj(data, header, pixel_scale, cx, cy, incl, pa, rmin=0.0):
    SNR_THR = 2.0
    gap_tol = 0.50
    pa_rad = np.radians(pa)
    incl_rad = np.radians(incl)
    cos_i = max(np.cos(incl_rad), 0.05)
    bmaj_as = header.get("BMAJ", 0) * 3600.0
    ny, nx = data.shape
    r_max_pix = min(ny // 2, nx // 2, 800)
    y_idx = np.arange(-r_max_pix, r_max_pix + 1)
    x_idx = np.arange(-r_max_pix, r_max_pix + 1)
    Xf, Yf = np.meshgrid(x_idx, y_idx)
    R_maj = -Xf * np.sin(pa_rad) + Yf * np.cos(pa_rad)
    R_min = Xf * np.cos(pa_rad) + Yf * np.sin(pa_rad)
    R_min_dep = R_min / cos_i
    R_pix_fits = np.sqrt(R_maj ** 2 + R_min_dep ** 2)
    R_arcsec = R_pix_fits * pixel_scale
    samp_y = R_maj * np.cos(pa_rad) + R_min * np.sin(pa_rad) + cy
    samp_x = -R_maj * np.sin(pa_rad) + R_min * np.cos(pa_rad) + cx
    deproj = map_coordinates(data, [samp_y, samp_x], order=1, mode="constant", cval=0.0)
    r_arr = R_arcsec.ravel()
    d_arr = deproj.ravel()
    r_max_as = r_max_pix * pixel_scale
    bin_size = pixel_scale
    bins = np.arange(0, r_max_as + bin_size, bin_size)
    prof = np.zeros(len(bins) - 1)
    for k in range(len(bins) - 1):
        m = (r_arr >= bins[k]) & (r_arr < bins[k + 1])
        if m.sum() > 3:
            prof[k] = np.nanmean(d_arr[m])
    r_centers = (bins[:-1] + bins[1:]) / 2.0
    r_85 = r_max_as * 0.85
    edge_mask = r_arr > r_85
    if edge_mask.sum() > 50:
        rms = max(float(np.nanstd(d_arr[edge_mask])), 1e-10)
    else:
        edge = np.concatenate([
            data[:8, :].ravel(), data[-8:, :].ravel(),
            data[:, :8].ravel(), data[:, -8:].ravel(),
        ])
        rms = max(float(np.nanstd(edge)), 1e-10)
    prof_s = gaussian_filter1d(prof, sigma=2)
    gap_bins = max(1, int(gap_tol / bin_size))
    rout_idx = 0
    gap_count = 0
    for k, (r, v) in enumerate(zip(r_centers, prof_s)):
        if r < rmin:
            continue
        if v > SNR_THR * rms:
            rout_idx = k
            gap_count = 0
        else:
            gap_count += 1
            if gap_count > gap_bins:
                break
    margin = max(bmaj_as * 1.0, pixel_scale * 3, 0.03)
    return float(np.clip(r_centers[rout_idx] + margin, 0.10, 8.0))


def fit_gaussian_ring(radius, intensity, fit_rmin, fit_rmax):
    if fit_rmax <= fit_rmin or (fit_rmax - fit_rmin) <= 0.05:
        return None
    radius = np.asarray(radius, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    mask = (radius >= fit_rmin) & (radius <= fit_rmax) & np.isfinite(intensity)
    x_region = radius[mask]
    y_region = intensity[mask]
    if len(y_region) <= 5:
        return None
    try:
        idx_max = int(np.argmax(y_region))
        amp_guess = float(y_region[idx_max])
        if amp_guess <= 0:
            return None
        mean_guess = float(x_region[idx_max])
        sigma_guess = (fit_rmax - fit_rmin) / 4
        p0 = [amp_guess, mean_guess, sigma_guess, 0.0]
        popt, _ = curve_fit(gaussian, x_region, y_region, p0=p0, maxfev=2000)
        return {
            "peak_radius": float(popt[1]),
            "fwhm": float(2.355 * abs(popt[2])),
            "peak_intensity": float(popt[0]),
        }
    except Exception:
        return None


def _json_safe(values):
    """NaN/Inf are not valid JSON — emit null so the client can show gaps."""
    return [None if not np.isfinite(v) else float(v) for v in np.asarray(values, dtype=float)]


def run_analysis_pipeline(
    data,
    header,
    cx,
    cy,
    pa,
    incl,
    rout,
    fit_rmin=0.0,
    fit_rmax=0.0,
    display_dim=None,
    fov_margin=1.15,
):
    """
    Shared GUI/CLI analysis: deprojection, polar map, radial model, residuals, profile.
    cx/cy are FITS array coordinates (origin lower-left), the same convention as
    deproject_image, the optimizer and the pixel probe.

    All cartesian products (data/deproj/model/residuals) share one square FOV
    sized from Rout, so they overlay pixel-for-pixel. Pixels with no source
    coverage are NaN (transparent) instead of 0.
    """
    data = np.asarray(data, dtype=np.float32)
    pixel_scale = get_pixel_scale_arcsec(header)
    eff_cy = cy
    eff_cx = cx

    rout_pix = max(rout / pixel_scale, 8.0)
    if display_dim and display_dim > 0:
        dim = int(display_dim)
        dim += dim % 2
    else:
        half_px = float(np.clip(rout_pix * fov_margin, 64.0, 1024.0))
        dim = int(round(half_px)) * 2
    half = dim / 2.0

    # Crop wide enough that the deprojected grid never runs out of source pixels
    crop_size = deprojection_crop_size(dim, incl)
    dc, local_cx, local_cy = crop_around_center(data, eff_cx, eff_cy, crop_size)
    inside, _, _ = crop_around_center(np.ones(data.shape, dtype=np.float32), eff_cx, eff_cy, crop_size)
    # Blanked (NaN) input pixels would poison the cubic spline: zero them and
    # track them as "no coverage" instead.
    finite = np.isfinite(dc)
    dc = np.where(finite, dc, 0.0).astype(np.float32)
    inside = (inside * finite).astype(np.float32)

    deproj = deproject_image(dc, local_cx, local_cy, incl, pa, dim=dim, order=3)
    cover = deproject_image(inside, local_cx, local_cy, incl, pa, dim=dim, order=1)
    deproj = np.where(cover > 0.5, deproj, np.nan).astype(np.float32)

    polar_full, r_full = to_polar(deproj)
    prof_full = _nanmean_axis0(polar_full)

    # Model needs a gap-free profile; residuals stay NaN where deproj is NaN
    good = np.isfinite(prof_full)
    prof_model = (
        np.interp(r_full, r_full[good], prof_full[good])
        if good.any() else np.zeros_like(prof_full)
    )
    x = np.arange(dim) - half
    X, Y = np.meshgrid(x, x)
    d_map = np.sqrt(X ** 2 + Y ** 2)
    mod = np.interp(d_map.flatten(), r_full, prof_model).reshape(dim, dim)
    resi = deproj - mod

    limit_idx = min(np.searchsorted(r_full, rout_pix), len(r_full))
    polar_display = widen_polar(polar_full[:, :limit_idx])
    prof_display = prof_full[:limit_idx]
    r_display = r_full[:limit_idx]
    r_arcsec = r_display * pixel_scale
    tb_prof = mjy_to_tb(prof_display, header)
    prof_jy = prof_display / 1000.0

    # "data" panel view: same FOV as the deprojected grid, no resampling
    ci_y = int(round(local_cy))
    ci_x = int(round(local_cx))
    h = dim // 2
    dc_view = dc[ci_y - h: ci_y + h, ci_x - h: ci_x + h]
    view_inside = inside[ci_y - h: ci_y + h, ci_x - h: ci_x + h]
    dc_view = np.where(view_inside > 0.5, dc_view, np.nan).astype(np.float32)

    fov_arcsec = dim * pixel_scale
    limit_arcsec = fov_arcsec / 2
    ext_cartesian = [limit_arcsec, -limit_arcsec, -limit_arcsec, limit_arcsec]
    ext_polar = [0, rout, -180, 180]

    fit_stats = fit_gaussian_ring(r_arcsec, tb_prof, fit_rmin, fit_rmax)
    beam = beam_info_from_header(header)

    results = {
        "data": dc_view.astype(np.float32),
        "deproj": deproj.astype(np.float32),
        "polar": polar_display.astype(np.float32),
        "model": mod.astype(np.float32),
        "residuals": resi.astype(np.float32),
    }
    extents = {
        "data": ext_cartesian,
        "deproj": ext_cartesian,
        "model": ext_cartesian,
        "residuals": ext_cartesian,
        "polar": ext_polar,
    }
    tb_json = _json_safe(tb_prof)
    raw_json = _json_safe(prof_jy)
    profile = {
        "radius": _json_safe(r_arcsec),
        "tb": tb_json,
        "raw": raw_json,
        "intensity": tb_json,
        "raw_intensity": raw_json,
    }
    geometry = {
        "fov_cartesian": fov_arcsec,
        "fov_polar": rout,
        "beam": beam,
        "pixel_scale": pixel_scale,
    }
    return {
        "results": results,
        "extents": extents,
        "profile": profile,
        "geometry": geometry,
        "fit": fit_stats,
    }


def make_result_header(base_header, array_2d, product: str, extent=None, pixel_scale=None):
    """Build a FITS header suitable for a derived 2D product (avoids invalid WCS)."""
    from astropy.io import fits as afits

    hdr = afits.Header()
    for key in ("OBJECT", "TELESCOP", "INSTRUME", "OBSERVER", "DATE-OBS", "BUNIT", "BMAJ", "BMIN", "BPA", "RESTFRQ"):
        if key in base_header:
            hdr[key] = base_header[key]
    hdr["NAXIS"] = 2
    hdr["NAXIS1"] = array_2d.shape[1]
    hdr["NAXIS2"] = array_2d.shape[0]
    hdr["DISCOPRD"] = product
    if pixel_scale is None:
        pixel_scale = get_pixel_scale_arcsec(base_header)
    if product == "polar":
        # X = radius [arcsec], Y = azimuth [deg]
        hdr["CTYPE1"] = "RADIUS"
        hdr["CTYPE2"] = "AZIMUTH"
        hdr["CUNIT1"] = "arcsec"
        hdr["CUNIT2"] = "deg"
        if extent:
            r0, r1, a0, a1 = extent
            hdr["CRPIX1"] = 1.0
            hdr["CRVAL1"] = float(r0)
            hdr["CDELT1"] = float((r1 - r0) / max(array_2d.shape[1] - 1, 1))
            hdr["CRPIX2"] = 1.0
            hdr["CRVAL2"] = float(a0)
            hdr["CDELT2"] = float((a1 - a0) / max(array_2d.shape[0] - 1, 1))
    else:
        hdr["CTYPE1"] = "OFFSETX"
        hdr["CTYPE2"] = "OFFSETY"
        hdr["CUNIT1"] = "arcsec"
        hdr["CUNIT2"] = "arcsec"
        hdr["CRPIX1"] = array_2d.shape[1] / 2.0
        hdr["CRPIX2"] = array_2d.shape[0] / 2.0
        hdr["CRVAL1"] = 0.0
        hdr["CRVAL2"] = 0.0
        hdr["CDELT1"] = -float(pixel_scale)
        hdr["CDELT2"] = float(pixel_scale)
    return hdr
