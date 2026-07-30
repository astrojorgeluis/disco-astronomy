"""Raster overview and tile endpoints."""
from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from disco.server.pyramid import (
    TILE_SIZE,
    ensure_pyramid,
    extract_tile,
    overview,
    pyramid_meta,
)
from disco.server.session import store

router = APIRouter(tags=["tiles"])


def _resolve(image_id: str | None = None):
    if image_id:
        img = store.images.get(image_id)
        if not img:
            raise HTTPException(404, "Image not found")
        return img
    img = store.active()
    if not img:
        raise HTTPException(400, "No image loaded")
    return img


def _float_headers(meta: dict) -> dict:
    return {
        "X-DISCO-Width": str(meta["width"]),
        "X-DISCO-Height": str(meta["height"]),
        "X-DISCO-Min": str(meta.get("min", 0)),
        "X-DISCO-Max": str(meta.get("max", 1)),
        "X-DISCO-P995": str(meta.get("p995", 1)),
        "X-DISCO-P999": str(meta.get("p999", 1)),
        "X-DISCO-PixelScale": str(meta.get("pixel_scale", 0.03)),
        "X-DISCO-Decimation": str(meta.get("decimation", 1)),
        "X-DISCO-FullWidth": str(meta.get("full_width", meta["width"])),
        "X-DISCO-FullHeight": str(meta.get("full_height", meta["height"])),
        "X-DISCO-TileSize": str(meta.get("tile_size", TILE_SIZE)),
        "X-DISCO-Level": str(meta.get("level", 0)),
    }


@router.get("/raster/meta")
def get_raster_meta(image_id: str | None = None, product: str = "data"):
    img = _resolve(image_id)
    return pyramid_meta(img, product)


@router.get("/raster")
def get_raster(image_id: str | None = None, product: str = "data", max_size: int = 2048):
    """Return a float32 overview (max dimension <= max_size)."""
    img = _resolve(image_id)
    max_size = max(64, min(int(max_size), 4096))
    arr, decim, stats = overview(img, product, max_size=max_size)
    arr = np.ascontiguousarray(arr, dtype="<f4")
    levels = ensure_pyramid(img, product)
    meta = {
        "width": arr.shape[1],
        "height": arr.shape[0],
        "min": stats.get("min", 0),
        "max": stats.get("max", 1),
        "p995": stats.get("p995", 1),
        "p999": stats.get("p999", 1),
        "pixel_scale": img.pixel_scale,
        "decimation": decim,
        "full_width": levels[0].shape[1],
        "full_height": levels[0].shape[0],
        "tile_size": TILE_SIZE,
        "level": int(round(math.log2(decim))) if decim > 0 else 0,
    }
    return Response(
        content=arr.tobytes(order="C"),
        media_type="application/octet-stream",
        headers=_float_headers(meta),
    )


@router.get("/tiles/{image_id}/{product}/{z}/{tx}/{ty}")
def get_tile(image_id: str, product: str, z: int, tx: int, ty: int):
    """Return a 256x256 float32 tile at pyramid level z."""
    img = _resolve(image_id)
    levels = ensure_pyramid(img, product)
    if z < 0 or z >= len(levels):
        raise HTTPException(404, f"Level {z} out of range (0..{len(levels) - 1})")
    level = levels[z]
    ny, nx = level.shape
    ntx = math.ceil(nx / TILE_SIZE)
    nty = math.ceil(ny / TILE_SIZE)
    if tx < 0 or ty < 0 or tx >= ntx or ty >= nty:
        raise HTTPException(404, "Tile out of range")
    tile = extract_tile(level, tx, ty, TILE_SIZE)
    stats = img.pyramid_stats.get(product, {}) if img.pyramid_stats else {}
    headers = _float_headers({
        "width": TILE_SIZE,
        "height": TILE_SIZE,
        "min": stats.get("min", 0),
        "max": stats.get("max", 1),
        "p995": stats.get("p995", 1),
        "p999": stats.get("p999", 1),
        "pixel_scale": img.pixel_scale,
        "decimation": 2 ** z,
        "full_width": levels[0].shape[1],
        "full_height": levels[0].shape[0],
        "tile_size": TILE_SIZE,
        "level": z,
    })
    headers["X-DISCO-TileX"] = str(tx)
    headers["X-DISCO-TileY"] = str(ty)
    return Response(
        content=np.ascontiguousarray(tile, dtype="<f4").tobytes(order="C"),
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/tiles/{product}/{z}/{tx}/{ty}")
def get_tile_active(product: str, z: int, tx: int, ty: int):
    img = _resolve(None)
    return get_tile(img.id, product, z, tx, ty)
