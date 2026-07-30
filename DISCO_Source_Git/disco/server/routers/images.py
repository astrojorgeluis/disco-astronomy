"""Image upload / list / pixels / WCS endpoints."""
from __future__ import annotations

import os
import re

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from disco.core.fits_io import header_to_list, load_fits, pixel_to_world_strings
from disco.core.units import get_pixel_scale_arcsec
from disco.server.pyramid import PIXELS_LEGACY_MAX, ensure_pyramid
from disco.server.schemas import LoadLocalParams, PixelProbeParams, SetActiveParams
from disco.server.session import ImageEntry, new_image_id, store

router = APIRouter(tags=["images"])


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "upload.fits")
    base = re.sub(r"[^\w.\-]+", "_", base)
    if not base.lower().endswith((".fits", ".fit", ".fts")):
        base = base + ".fits"
    return base


def _resolve_image(image_id: str | None = None) -> ImageEntry:
    if image_id:
        img = store.images.get(image_id)
        if not img:
            raise HTTPException(404, "Image not found")
        return img
    img = store.active()
    if not img:
        raise HTTPException(400, "No image loaded")
    return img


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        os.makedirs(store.upload_dir, exist_ok=True)
        safe = _safe_filename(file.filename or "upload.fits")
        image_id = new_image_id()
        dest_name = f"{image_id}_{safe}"
        file_location = os.path.join(store.upload_dir, dest_name)
        if not os.path.abspath(file_location).startswith(os.path.abspath(store.upload_dir)):
            raise HTTPException(400, "Invalid filename")
        raw = await file.read()
        with open(file_location, "wb") as buffer:
            buffer.write(raw)
        loaded = load_fits(file_location)
        ny, nx = loaded["data"].shape
        # Sensible default outer radius: ~30% of half-FOV
        half = min(nx, ny) / 2
        rout = max(0.3, min(5.0, (half * 0.35) * loaded["pixel_scale"]))
        entry = ImageEntry(
            id=image_id,
            filename=safe,
            path=file_location,
            data=loaded["data"],
            header=loaded["header"],
            pixel_scale=loaded["pixel_scale"],
            params={
                "cx": nx / 2, "cy": ny / 2, "incl": 0, "pa": 0,
                "rout": rout, "fit_rmin": 0, "fit_rmax": 0,
            },
        )
        store.add_image(entry)
        return {
            "id": image_id,
            "filename": safe,
            "status": "loaded",
            "shape": list(loaded["data"].shape),
            "pixel_scale": loaded["pixel_scale"],
            "params": entry.params,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load_local")
def load_local(params: LoadLocalParams):
    clean = os.path.basename(params.filename)
    matches = []
    for name in os.listdir(store.upload_dir):
        if name == clean or name.endswith("_" + clean) or name.endswith(clean):
            matches.append(os.path.join(store.upload_dir, name))
    if not matches:
        raise HTTPException(404, "File not found")
    path = matches[0]
    try:
        loaded = load_fits(path)
        image_id = new_image_id()
        ny, nx = loaded["data"].shape
        half = min(nx, ny) / 2
        rout = max(0.3, min(5.0, (half * 0.35) * loaded["pixel_scale"]))
        entry = ImageEntry(
            id=image_id,
            filename=clean,
            path=path,
            data=loaded["data"],
            header=loaded["header"],
            pixel_scale=loaded["pixel_scale"],
            params={
                "cx": nx / 2, "cy": ny / 2, "incl": 0, "pa": 0,
                "rout": rout, "fit_rmin": 0, "fit_rmax": 0,
            },
        )
        store.add_image(entry)
        return {
            "id": image_id,
            "status": "loaded",
            "filename": clean,
            "shape": list(loaded["data"].shape),
            "pixel_scale": loaded["pixel_scale"],
            "params": entry.params,
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/images")
def list_images():
    return {"images": store.list_images(), "active_id": store.active_id}


@router.post("/images/active")
def set_active(params: SetActiveParams):
    try:
        img = store.set_active(params.image_id)
    except KeyError:
        raise HTTPException(404, "Image not found")
    return {
        "id": img.id,
        "filename": img.filename,
        "shape": list(img.data.shape),
        "pixel_scale": img.pixel_scale,
        "params": img.params,
    }


@router.delete("/images/{image_id}")
def delete_image(image_id: str):
    store.remove_image(image_id)
    return {"status": "ok"}


@router.get("/header")
@router.get("/get_header")
def get_header(image_id: str | None = None):
    img = _resolve_image(image_id)
    return {"header": header_to_list(img.header)}


@router.get("/pixels")
def get_pixels(image_id: str | None = None, product: str = "data"):
    """Legacy full-buffer endpoint. Rejected for large images — use /api/raster."""
    img = _resolve_image(image_id)
    if product == "data" or product not in img.results:
        arr = img.data
    else:
        arr = np.asarray(img.results[product])
    if arr.size > PIXELS_LEGACY_MAX:
        raise HTTPException(
            413,
            detail=(
                f"Image too large for /api/pixels ({arr.shape[0]}x{arr.shape[1]}). "
                "Use /api/raster or /api/tiles instead."
            ),
        )
    arr = np.asarray(arr, dtype="<f4")
    stats = {}
    try:
        ensure_pyramid(img, product)
        stats = (img.pyramid_stats or {}).get(product, {})
    except Exception:
        stats = {
            "min": float(np.nanmin(arr)),
            "max": float(np.nanmax(arr)),
            "p995": float(np.nanpercentile(arr, 99.5)),
            "p999": float(np.nanpercentile(arr, 99.9)),
        }
    headers = {
        "X-DISCO-Width": str(arr.shape[1]),
        "X-DISCO-Height": str(arr.shape[0]),
        "X-DISCO-Min": str(stats.get("min", 0)),
        "X-DISCO-Max": str(stats.get("max", 1)),
        "X-DISCO-P995": str(stats.get("p995", 1)),
        "X-DISCO-P999": str(stats.get("p999", 1)),
        "X-DISCO-PixelScale": str(img.pixel_scale),
        "Content-Disposition": f'inline; filename="{product}.f32"',
    }
    return Response(content=arr.tobytes(order="C"), media_type="application/octet-stream", headers=headers)


@router.get("/pixels/meta")
def get_pixels_meta(image_id: str | None = None, product: str = "data"):
    img = _resolve_image(image_id)
    if product == "data" or product not in img.results:
        arr = img.data
    else:
        arr = img.results[product]
    ensure_pyramid(img, product)
    stats = (img.pyramid_stats or {}).get(product, {})
    return {
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "product": product,
        "pixel_scale": img.pixel_scale,
        "min": stats.get("min", float(np.nanmin(arr))),
        "max": stats.get("max", float(np.nanmax(arr))),
        "p995": stats.get("p995", float(np.nanpercentile(arr, 99.5))),
        "p999": stats.get("p999", float(np.nanpercentile(arr, 99.9))),
        "median": stats.get("median", float(np.nanmedian(arr))),
    }


@router.post("/probe")
def probe_pixel(params: PixelProbeParams):
    """Probe a pixel. x,y are FITS array coordinates (origin bottom-left, y north)."""
    img = _resolve_image(params.image_id)
    if params.product == "data" or params.product not in img.results:
        arr = img.data
        header = img.header
    else:
        arr = img.results[params.product]
        header = img.header
    ix = int(round(params.x))
    iy = int(round(params.y))
    if ix < 0 or iy < 0 or iy >= arr.shape[0] or ix >= arr.shape[1]:
        return {"value": None, "ra": None, "dec": None, "x": params.x, "y": params.y}
    value = float(arr[iy, ix])
    # WCS pixel_to_world expects FITS 0-based array coords matching our convention
    ra_s, dec_s, ra_d, dec_d = pixel_to_world_strings(header, params.x, params.y)
    return {
        "x": params.x,
        "y": params.y,
        "ix": ix,
        "iy": iy,
        "value": value,
        "ra": ra_s,
        "dec": dec_s,
        "ra_deg": ra_d,
        "dec_deg": dec_d,
        "pixel_scale": img.pixel_scale or get_pixel_scale_arcsec(header),
    }
