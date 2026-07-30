"""Unit conversions and FITS header scalar helpers (no matplotlib / FastAPI)."""
from __future__ import annotations

import numpy as np
from astropy.wcs import WCS


def get_pixel_scale_arcsec(header) -> float:
    """Return pixel scale in arcsec from CDELT, CD, or PC matrices."""
    try:
        wcs = WCS(header).celestial
        scales = wcs.proj_plane_pixel_scales()
        if scales is not None and len(scales) >= 2:
            return float(np.mean([abs(s.to_value("arcsec")) for s in scales]))
    except Exception:
        pass

    if "CDELT2" in header:
        return abs(float(header["CDELT2"])) * 3600.0
    if "CDELT1" in header:
        return abs(float(header["CDELT1"])) * 3600.0

    if "CD1_1" in header and "CD2_2" in header:
        cd11 = float(header.get("CD1_1", 0.0))
        cd12 = float(header.get("CD1_2", 0.0))
        cd21 = float(header.get("CD2_1", 0.0))
        cd22 = float(header.get("CD2_2", 0.0))
        sx = np.hypot(cd11, cd21) * 3600.0
        sy = np.hypot(cd12, cd22) * 3600.0
        scale = (abs(sx) + abs(sy)) / 2.0
        if scale > 0:
            return float(scale)

    return 0.03


def get_rest_frequency_hz(header) -> float:
    """Resolve rest frequency from RESTFRQ or frequency axis CRVALn."""
    restfrq = header.get("RESTFRQ", 0)
    if restfrq:
        return float(restfrq)
    for axis in (3, 4):
        ctype = str(header.get(f"CTYPE{axis}", "")).upper()
        if "FREQ" in ctype:
            return float(header.get(f"CRVAL{axis}", 230e9))
    return 230e9


def normalize_bunit_to_mjy(data: np.ndarray, header) -> tuple[np.ndarray, object]:
    """
    Convert Jy/beam data to mJy/beam when needed.
    Returns (data, updated_header_copy-like header).
    """
    bunit = str(header.get("BUNIT", "")).strip().upper()
    out = np.asarray(data, dtype=np.float32)
    if bunit == "JY/BEAM":
        out = out * 1000.0
        try:
            header = header.copy()
            header["BUNIT"] = "mJy/beam"
        except Exception:
            pass
    elif bunit == "" and np.nanmax(out) < 5.0:
        # Ambiguous units: historical heuristic used by CLI/GUI
        out = out * 1000.0
        try:
            header = header.copy()
            header["BUNIT"] = "mJy/beam"
        except Exception:
            pass
    return out, header


def mjy_to_tb(intensity_mjy: np.ndarray, header) -> np.ndarray:
    """Convert mJy/beam intensity to brightness temperature [K]."""
    restfrq = get_rest_frequency_hz(header)
    bmaj = float(header.get("BMAJ", 0) or 0) * 3600.0
    bmin = float(header.get("BMIN", 0) or 0) * 3600.0
    if bmaj > 0 and bmin > 0 and restfrq > 0:
        beam_sr = (np.pi * bmaj * bmin / (4 * np.log(2))) / 206265.0 ** 2
        factor = ((3e10) ** 2 * 1e-23) / (2 * 1.38e-16 * restfrq ** 2 * beam_sr * 1000.0)
        return intensity_mjy * factor
    return intensity_mjy


def beam_info_from_header(header) -> dict | None:
    if "BMAJ" not in header:
        return None
    try:
        return {
            "major": float(header["BMAJ"]) * 3600.0,
            "minor": float(header.get("BMIN", header["BMAJ"])) * 3600.0,
            "pa": float(header.get("BPA", 0.0)),
        }
    except Exception:
        return None
