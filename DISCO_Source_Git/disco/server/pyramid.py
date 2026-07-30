"""Lazy image pyramid for tiled raster delivery."""
from __future__ import annotations

from typing import Any

import numpy as np

from disco.server.session import ImageEntry

TILE_SIZE = 256
MIN_LEVEL_SIZE = 512
PIXELS_LEGACY_MAX = 1024 * 1024  # ~1M pixels for legacy /api/pixels


def _block_mean_downsample(arr: np.ndarray) -> np.ndarray:
    """
    Downsample by 2 using a 2x2 block mean, ignoring NaN (odd edges truncated).
    Blanked/uncovered pixels must not bleed into coarser levels.
    """
    a = np.asarray(arr, dtype=np.float32)
    ny, nx = a.shape
    ny2, nx2 = (ny // 2) * 2, (nx // 2) * 2
    a = a[:ny2, :nx2]
    blocks = (ny2 // 2, 2, nx2 // 2, 2)
    good = np.isfinite(a)
    if good.all():
        return a.reshape(blocks).mean(axis=(1, 3))
    total = np.where(good, a, 0.0).reshape(blocks).sum(axis=(1, 3))
    count = good.reshape(blocks).sum(axis=(1, 3))
    out = np.full(total.shape, np.nan, dtype=np.float32)
    np.divide(total, count, out=out, where=count > 0)
    return out


def _compute_stats(arr: np.ndarray) -> dict[str, float]:
    flat = np.asarray(arr, dtype=np.float32).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return {
            "min": 0.0, "max": 1.0, "p995": 1.0, "p999": 1.0, "median": 0.0,
            "histogram": {"counts": [], "edges": []},
        }
    # Sample for percentiles / histogram on large arrays
    if finite.size > 500_000:
        idx = np.linspace(0, finite.size - 1, 500_000, dtype=np.int64)
        sample = np.sort(finite[idx])
        hist_sample = finite[idx]
    else:
        sample = np.sort(finite)
        hist_sample = finite

    def pct(p):
        return float(sample[min(len(sample) - 1, int((p / 100.0) * len(sample)))])

    # Intensity histogram over [min, p999] so the stretch-relevant range is visible
    lo = float(sample[0])
    hi = pct(99.9)
    if not np.isfinite(hi) or hi <= lo:
        hi = float(sample[-1])
    if hi <= lo:
        hi = lo + 1.0
    counts, edges = np.histogram(hist_sample, bins=40, range=(lo, hi))
    return {
        "min": float(sample[0]),
        "max": float(sample[-1]),
        "p995": pct(99.5),
        "p999": pct(99.9),
        "median": pct(50),
        "histogram": {
            "counts": [int(c) for c in counts.tolist()],
            "edges": [float(e) for e in edges.tolist()],
        },
    }


def resolve_array(img: ImageEntry, product: str = "data") -> np.ndarray:
    if product == "data" or product not in img.results:
        return np.asarray(img.data)
    return np.asarray(img.results[product])


def ensure_pyramid(img: ImageEntry, product: str = "data") -> list[np.ndarray]:
    """
    Build (lazily) a pyramid for the given product.

    Level 0 = full resolution; each subsequent level is /2.
    Stored on ImageEntry.pyramid keyed implicitly for product=='data';
    For analysis products we build on the fly and cache under pyramid_stats key.
    """
    lock = img._pyramid_lock
    if lock is None:
        import threading
        lock = threading.RLock()
        img._pyramid_lock = lock

    cache_key = product
    with lock:
        if img.pyramid is None:
            img.pyramid = {}
        if img.pyramid_stats is None:
            img.pyramid_stats = {}

        if cache_key in img.pyramid and img.pyramid[cache_key]:
            return img.pyramid[cache_key]

        arr = resolve_array(img, product).astype(np.float32, copy=False)
        levels = [arr]
        cur = arr
        while max(cur.shape) > MIN_LEVEL_SIZE:
            cur = _block_mean_downsample(cur)
            if cur.size == 0:
                break
            levels.append(cur)

        # Stats from coarsest level (fast) — good enough for stretch defaults
        stats = _compute_stats(levels[-1])
        # Refine p995/p999 and histogram from a mid level if available
        mid = levels[min(2, len(levels) - 1)]
        mid_stats = _compute_stats(mid)
        stats["p995"] = mid_stats["p995"]
        stats["p999"] = mid_stats["p999"]
        stats["min"] = mid_stats["min"]
        stats["max"] = mid_stats["max"]
        stats["median"] = mid_stats.get("median", stats.get("median"))
        if mid_stats.get("histogram", {}).get("counts"):
            stats["histogram"] = mid_stats["histogram"]
        elif "histogram" not in stats:
            stats["histogram"] = {"counts": [], "edges": []}

        img.pyramid[cache_key] = levels
        img.pyramid_stats[cache_key] = stats
        return levels


def pyramid_meta(img: ImageEntry, product: str = "data") -> dict[str, Any]:
    levels = ensure_pyramid(img, product)
    stats = img.pyramid_stats.get(product, {})
    return {
        "image_id": img.id,
        "product": product,
        "full_width": int(levels[0].shape[1]),
        "full_height": int(levels[0].shape[0]),
        "tile_size": TILE_SIZE,
        "n_levels": len(levels),
        "levels": [
            {"z": i, "width": int(lv.shape[1]), "height": int(lv.shape[0])}
            for i, lv in enumerate(levels)
        ],
        "pixel_scale": img.pixel_scale,
        "stats": stats,
    }


def extract_tile(level: np.ndarray, tx: int, ty: int, tile_size: int = TILE_SIZE) -> np.ndarray:
    """Extract tile (ty, tx) as float32 C-order, padded with NaN to tile_size if needed."""
    ny, nx = level.shape
    y0 = ty * tile_size
    x0 = tx * tile_size
    if y0 >= ny or x0 >= nx or y0 < 0 or x0 < 0:
        return np.full((tile_size, tile_size), np.nan, dtype=np.float32)
    y1 = min(ny, y0 + tile_size)
    x1 = min(nx, x0 + tile_size)
    patch = level[y0:y1, x0:x1]
    if patch.shape == (tile_size, tile_size):
        return np.ascontiguousarray(patch, dtype=np.float32)
    out = np.full((tile_size, tile_size), np.nan, dtype=np.float32)
    out[: patch.shape[0], : patch.shape[1]] = patch
    return out


def overview(img: ImageEntry, product: str = "data", max_size: int = 2048) -> tuple[np.ndarray, int, dict]:
    """
    Return (array, decimation_factor, stats) where max(array.shape) <= max_size.
    Decimation factor is relative to full resolution (power of 2).
    """
    levels = ensure_pyramid(img, product)
    stats = img.pyramid_stats.get(product, {})
    for z, lv in enumerate(levels):
        if max(lv.shape) <= max_size:
            return lv, 2 ** z, stats
    # Extra downsample beyond pyramid if still too large
    z = len(levels) - 1
    cur = levels[z]
    while max(cur.shape) > max_size:
        cur = _block_mean_downsample(cur)
        z += 1
        if cur.size == 0:
            break
    return cur, 2 ** z, stats
