"""Analysis pipeline and region statistics."""
from __future__ import annotations

import io

import numpy as np
from astropy.io import fits
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from scipy.optimize import minimize

from disco.core.optimization import geometric_loss
from disco.core.profiles import make_result_header, run_analysis_pipeline
from disco.core.regions import region_stats
from disco.core.units import beam_info_from_header
from disco.server.schemas import OptimizeParams, PipelineParams, RegionStatsParams
from disco.server.session import store

router = APIRouter(tags=["analysis"])


def _resolve(image_id=None):
    if image_id and image_id in store.images:
        return store.images[image_id]
    img = store.active()
    if not img:
        raise HTTPException(400, "No FITS data loaded.")
    return img


@router.post("/run_pipeline")
def run_pipeline(params: PipelineParams):
    """Run analysis. cx/cy are FITS array coords (origin bottom-left, y north)."""
    img = _resolve(params.image_id)
    out = run_analysis_pipeline(
        img.data, img.header,
        cx=params.cx, cy=params.cy, pa=params.pa, incl=params.incl, rout=params.rout,
        fit_rmin=params.fit_rmin, fit_rmax=params.fit_rmax,
    )
    img.results = out["results"]
    img.extents = out["extents"]
    img.profile_data = out["profile"]
    img.geometry = out["geometry"]
    img.fit = out["fit"]
    img.params = {
        "cx": params.cx, "cy": params.cy, "pa": params.pa, "incl": params.incl,
        "rout": params.rout, "fit_rmin": params.fit_rmin, "fit_rmax": params.fit_rmax,
    }
    # Drop stale tile pyramids so the next raster/tile fetch rebuilds from new results
    img.pyramid = None
    img.pyramid_stats = None
    store.log("run_pipeline", {"image_id": img.id, "params": img.params})

    # Lightweight PNG previews for backward-compatible clients
    from disco.server.render_utils import array_to_base64

    images = {
        "data": f"data:image/png;base64,{array_to_base64(out['results']['data'], cmap='inferno')}",
        "deproj": f"data:image/png;base64,{array_to_base64(out['results']['deproj'], cmap='inferno')}",
        "polar": f"data:image/png;base64,{array_to_base64(out['results']['polar'], cmap='inferno', stretch_val=0.1)}",
        "model": f"data:image/png;base64,{array_to_base64(out['results']['model'], cmap='inferno')}",
        "residuals": f"data:image/png;base64,{array_to_base64(out['results']['residuals'], cmap='magma', stretch_val=0.9)}",
    }
    return {
        "images": images,
        "profile": {
            "radius": out["profile"]["radius"],
            "intensity": out["profile"]["intensity"],
            "raw_intensity": out["profile"]["raw_intensity"],
        },
        "geometry": out["geometry"],
        "fit": out["fit"],
        "image_id": img.id,
    }


@router.post("/optimize_geometry")
def optimize_geometry(params: OptimizeParams):
    """Optimize incl/PA (and refine cx/cy). Coordinates are FITS array (origin lower-left)."""
    img = _resolve(params.image_id)
    data = img.data
    # Array-bottom coords from the API (no further flip)
    eff_cy = float(params.cy)
    eff_cx = float(params.cx)
    pad = 1000
    d_pad = np.pad(data, pad, mode="constant", constant_values=0)
    real_cy_int = int(eff_cy) + pad
    real_cx_int = int(eff_cx) + pad
    offset_y = (eff_cy + pad) - real_cy_int
    offset_x = (eff_cx + pad) - real_cx_int
    pixel_scale = float(img.pixel_scale) or 0.03

    # Sensible radial window when the client has not set one yet
    rout = max(float(params.rout), 0.05)
    fit_rmin = float(params.fit_rmin)
    fit_rmax = float(params.fit_rmax)
    if not (fit_rmax > fit_rmin > 0):
        fit_rmin = rout * 0.15
        fit_rmax = rout * 0.85

    search_rad = max(rout, fit_rmax)
    search_rad_pix = max(int(search_rad / pixel_scale), 16)
    crop_rad = int(search_rad_pix * 1.25) + 16
    dc = d_pad[
        real_cy_int - crop_rad: real_cy_int + crop_rad,
        real_cx_int - crop_rad: real_cx_int + crop_rad,
    ]
    if dc.size == 0 or min(dc.shape) < 32:
        raise HTTPException(400, "Crop around center is empty — check cx/cy and Rout.")
    local_c_y = crop_rad + offset_y
    local_c_x = crop_rad + offset_x
    rmin_pix = fit_rmin / pixel_scale
    rmax_pix = fit_rmax / pixel_scale

    loss_args = (dc, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix)
    best_guess = [float(params.incl), float(params.pa) % 180, 0.0, 0.0]
    min_loss = geometric_loss(best_guess, *loss_args, dim=120, order=1)

    # Coarse grid over inclination × PA
    for ti in range(5, 80, 5):
        for tp in range(0, 180, 10):
            loss_val = geometric_loss([ti, tp, 0.0, 0.0], *loss_args, dim=120, order=1)
            if loss_val < min_loss:
                min_loss = loss_val
                best_guess = [float(ti), float(tp), 0.0, 0.0]

    # Nelder-Mead ignores bounds — use L-BFGS-B so incl/PA/center stay physical
    res = minimize(
        geometric_loss,
        best_guess,
        args=(*loss_args, 360, 3),
        method="L-BFGS-B",
        bounds=[(0.0, 85.0), (0.0, 180.0), (-12.0, 12.0), (-12.0, 12.0)],
    )
    best_incl, best_pa, best_dcx, best_dcy = (float(v) for v in res.x)
    best_pa = best_pa % 180.0
    if best_pa < 0:
        best_pa += 180.0
    best_incl = float(np.clip(best_incl, 0.0, 85.0))
    out_cx = eff_cx + best_dcx
    out_cy = eff_cy + best_dcy
    store.log(
        "optimize_geometry",
        {"incl": best_incl, "pa": best_pa, "cx": out_cx, "cy": out_cy, "success": bool(res.success)},
    )
    return {
        "optimized_incl": best_incl,
        "optimized_pa": best_pa,
        "optimized_cx": float(out_cx),
        "optimized_cy": float(out_cy),
    }


@router.post("/regions/stats")
def regions_stats(params: RegionStatsParams):
    img = _resolve(params.image_id)
    if params.product == "data" or params.product not in img.results:
        arr = img.data
    else:
        arr = img.results[params.product]
    if arr is None or getattr(arr, "size", 0) == 0:
        raise HTTPException(400, "No image data available")
    region = params.region or {}
    # Quick off-image rejection
    ny, nx = arr.shape
    if region.get("type") == "ellipse":
        cx, cy = float(region.get("cx", -1)), float(region.get("cy", -1))
        if cx < -1e6 or cy < -1e6 or cx > nx + 1e6 or cy > ny + 1e6:
            return {"stats": {"npix": 0, "sum": 0.0, "mean": 0.0, "rms": 0.0, "peak": 0.0, "min": 0.0, "flux": 0.0}}
    beam = beam_info_from_header(img.header)
    beam_area_pix = None
    if beam:
        beam_area_pix = (np.pi * beam["major"] * beam["minor"] / (4 * np.log(2))) / (img.pixel_scale ** 2)
    stats = region_stats(arr, region, pixel_scale=img.pixel_scale, beam_area_pix=beam_area_pix)
    store.log("region_stats", {"region": region.get("type"), "stats": stats})
    return {"stats": stats}


@router.get("/download_fits")
def download_fits(type: str = "deproj", image_id: str | None = None):
    img = _resolve(image_id)
    if type in img.results:
        data_to_save = img.results[type]
        extent = img.extents.get(type)
    elif type == "data":
        data_to_save = img.data
        extent = None
    else:
        raise HTTPException(400, "Data not found")
    hdr = make_result_header(img.header, data_to_save, type, extent=extent, pixel_scale=img.pixel_scale)
    hdu = fits.PrimaryHDU(data=np.asarray(data_to_save, dtype=np.float32), header=hdr)
    buf = io.BytesIO()
    hdu.writeto(buf)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=result_{type}.fits"},
    )
