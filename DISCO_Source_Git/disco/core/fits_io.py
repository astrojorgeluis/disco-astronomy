"""FITS loading, WCS helpers, and center finding."""
from __future__ import annotations

import os

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord, skycoord_to_pixel
from scipy.ndimage import binary_fill_holes, center_of_mass, gaussian_filter, label

from disco.core.units import get_pixel_scale_arcsec, normalize_bunit_to_mjy

try:
    import logging

    from astroquery.gaia import Gaia as _GaiaCatalog

    logging.getLogger("astroquery").setLevel(logging.ERROR)
    _ASTROQUERY_AVAILABLE = True
except ImportError:
    _ASTROQUERY_AVAILABLE = False


def load_fits(path: str) -> dict:
    """Load a FITS image, normalize units, return a session-ready dict."""
    with fits.open(path, memmap=False) as hdul:
        data = np.nan_to_num(np.squeeze(hdul[0].data).astype(np.float32))
        header = hdul[0].header.copy()
    data, header = normalize_bunit_to_mjy(data, header)
    pixel_scale = get_pixel_scale_arcsec(header)
    return {
        "data": data,
        "header": header,
        "filename": os.path.basename(path),
        "path": path,
        "pixel_scale": pixel_scale,
        "shape": data.shape,
    }


def find_center_robust(data, pixel_scale, header):
    cy_cen, cx_cen = data.shape[0] // 2, data.shape[1] // 2
    search_rad_pix = int(3.0 / pixel_scale)
    y_min = max(0, cy_cen - search_rad_pix)
    y_max = min(data.shape[0], cy_cen + search_rad_pix)
    x_min = max(0, cx_cen - search_rad_pix)
    x_max = min(data.shape[1], cx_cen + search_rad_pix)
    crop = data[y_min:y_max, x_min:x_max]

    bmaj_arcsec = header.get("BMAJ", 0) * 3600
    sigma_as = max(bmaj_arcsec / 2.355, 0.08)
    sigma_pix = sigma_as / pixel_scale
    smoothed = gaussian_filter(crop, sigma=sigma_pix)
    peak = np.nanmax(smoothed)
    mask = smoothed > (peak * 0.20)
    labeled, num_features = label(mask)
    if num_features > 0:
        sizes = np.bincount(labeled.ravel())
        sizes[0] = 0
        main_comp = np.argmax(sizes)
        main_mask = labeled == main_comp
    else:
        main_mask = mask

    filled = binary_fill_holes(main_mask)
    pixels_orig = np.sum(main_mask)
    pixels_fill = np.sum(filled)
    if pixels_orig > 0 and (pixels_fill > pixels_orig * 1.03):
        y_idx, x_idx = np.where(filled)
        cy_local = (np.min(y_idx) + np.max(y_idx)) / 2.0
        cx_local = (np.min(x_idx) + np.max(x_idx)) / 2.0
    else:
        if np.any(main_mask):
            cy_local, cx_local = center_of_mass(main_mask)
        else:
            cy_local, cx_local = np.unravel_index(np.argmax(smoothed), smoothed.shape)
    return float(cx_local + x_min), float(cy_local + y_min)


def auto_detect_parameters(data, header, pixel_scale, cx, cy):
    from scipy.ndimage import gaussian_filter1d

    bmaj = header.get("BMAJ", 0) * 3600
    rmin = max(bmaj * 1.2, 0.15) if bmaj > 0 else 0.2
    y, x = np.indices(data.shape)
    r = np.hypot(x - cx, y - cy) * pixel_scale
    bins = np.arange(0, 10.0, pixel_scale)
    prof, _ = np.histogram(r, bins=bins, weights=data)
    counts, _ = np.histogram(r, bins=bins)
    prof_mean = prof / np.maximum(counts, 1)
    prof_smooth = gaussian_filter1d(prof_mean, sigma=2)
    edge = np.concatenate([
        data[:10, :].ravel(), data[-10:, :].ravel(),
        data[:, :10].ravel(), data[:, -10:].ravel(),
    ])
    rms = np.nanstd(edge)
    if rms <= 0:
        rms = 1e-9
    above_snr = prof_smooth > (3.0 * rms)
    max_gap_bins = int(0.3 / pixel_scale)
    rout_idx = 0
    gap_counter = 0
    for i in range(len(above_snr)):
        if above_snr[i]:
            rout_idx = i
            gap_counter = 0
        else:
            gap_counter += 1
            if gap_counter > max_gap_bins:
                break
    rout = bins[rout_idx] + (pixel_scale * 2.0) + 0.05
    rout = float(np.clip(rout, 0.15, 8.0))
    return float(rmin), rout, float(bmaj)


def refine_center_local(data, header, pixel_scale, cx_init, cy_init):
    bmaj_arcsec = header.get("BMAJ", 0) * 3600
    search_rad_arcsec = max(bmaj_arcsec * 0.6, 0.15) if bmaj_arcsec > 0 else 0.25
    search_rad_pix = max(int(np.ceil(search_rad_arcsec / pixel_scale)), 3)
    y_min = max(0, int(round(cy_init)) - search_rad_pix)
    y_max = min(data.shape[0], int(round(cy_init)) + search_rad_pix + 1)
    x_min = max(0, int(round(cx_init)) - search_rad_pix)
    x_max = min(data.shape[1], int(round(cx_init)) + search_rad_pix + 1)
    if y_max - y_min < 3 or x_max - x_min < 3:
        return cx_init, cy_init
    crop = data[y_min:y_max, x_min:x_max].copy()
    sigma_pix = max((bmaj_arcsec / 2.355) / pixel_scale, 1.0) if bmaj_arcsec > 0 else 1.5
    smoothed = gaussian_filter(crop, sigma=sigma_pix)
    peak = np.nanmax(smoothed)
    if peak <= 0:
        return cx_init, cy_init
    mask = smoothed > (peak * 0.25)
    if not np.any(mask):
        return cx_init, cy_init
    cy_local, cx_local = center_of_mass(smoothed * mask)
    cx_ref = cx_init - x_min
    cy_ref = cy_init - y_min
    if abs(cx_local - cx_ref) > search_rad_pix or abs(cy_local - cy_ref) > search_rad_pix:
        return cx_init, cy_init
    return float(cx_local + x_min), float(cy_local + y_min)


def deg_to_sex(deg):
    sign = "+" if deg >= 0 else "-"
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60.0) * 3600.0
    return f"{sign}{d:03d}:{m:02d}:{s:06.3f}"


def pixel_to_icrs(header, cx, cy):
    wcs = WCS(header).celestial
    coord = pixel_to_skycoord(cx, cy, wcs, origin=0)
    icrs = coord.icrs
    return float(icrs.ra.deg), float(icrs.dec.deg)


def icrs_to_pixel(header, ra_deg, dec_deg):
    wcs = WCS(header).celestial
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    x, y = skycoord_to_pixel(coord, wcs, origin=0)
    return float(x), float(y)


def pixel_to_world_strings(header, x, y):
    """Return sexagesimal RA/Dec strings for a pixel (origin=0)."""
    try:
        wcs = WCS(header).celestial
        coord = pixel_to_skycoord(x, y, wcs, origin=0).icrs
        ra = coord.ra.to_string(unit=u.hour, sep=":", precision=3, pad=True)
        dec = coord.dec.to_string(sep=":", precision=2, pad=True, alwayssign=True)
        return str(ra), str(dec), float(coord.ra.deg), float(coord.dec.deg)
    except Exception:
        return None, None, None, None


def get_obs_epoch(header):
    date_obs = header.get("DATE-OBS", None)
    if date_obs:
        try:
            return Time(str(date_obs).strip(), format="isot", scale="utc")
        except Exception:
            try:
                return Time(str(date_obs).strip(), scale="utc")
            except Exception:
                pass
    mjd_obs = header.get("MJD-OBS", None)
    if mjd_obs is not None:
        try:
            return Time(float(mjd_obs), format="mjd", scale="utc")
        except Exception:
            pass
    return None


def query_gaia_proper_motion(ra_deg, dec_deg, search_radius_arcsec=3.0):
    if not _ASTROQUERY_AVAILABLE:
        return None, None, None
    try:
        _GaiaCatalog.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
        _GaiaCatalog.ROW_LIMIT = 20
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
        radius = u.Quantity(search_radius_arcsec, u.arcsec)
        job = _GaiaCatalog.cone_search_async(coord, radius=radius, verbose=False)
        r = job.get_results()
        if len(r) == 0:
            return None, None, None
        gaia_coords = SkyCoord(
            ra=np.array(r["ra"], dtype=float) * u.deg,
            dec=np.array(r["dec"], dtype=float) * u.deg,
            frame="icrs",
        )
        seps = coord.separation(gaia_coords).arcsec
        order = np.argsort(seps)
        for idx in order:
            row = r[idx]
            try:
                pmra_raw = row["pmra"]
                pmdec_raw = row["pmdec"]
                if np.ma.is_masked(pmra_raw) or np.ma.is_masked(pmdec_raw):
                    continue
                pmra_val = float(pmra_raw)
                pmdec_val = float(pmdec_raw)
                if not (np.isfinite(pmra_val) and np.isfinite(pmdec_val)):
                    continue
                return pmra_val, pmdec_val, float(seps[idx])
            except Exception:
                continue
        return None, None, None
    except Exception:
        return None, None, None


def apply_proper_motion_correction(ra_deg, dec_deg, pmra_masyr, pmdec_masyr, dt_yr):
    cos_dec = np.cos(np.radians(dec_deg))
    delta_ra = (pmra_masyr * dt_yr) / (cos_dec * 3.6e6)
    delta_dec = (pmdec_masyr * dt_yr) / 3.6e6
    return float(ra_deg + delta_ra), float(dec_deg + delta_dec)


def header_to_list(header) -> list[dict]:
    rows = []
    for key, value in header.items():
        if key in ("COMMENT", "HISTORY"):
            continue
        rows.append({"key": key, "value": str(value), "comment": header.comments[key]})
    return rows
