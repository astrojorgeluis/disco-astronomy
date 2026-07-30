"""External catalog queries (SIMBAD)."""
from __future__ import annotations

import astropy.units as u
import numpy as np
from astropy.wcs import WCS
from fastapi import APIRouter, HTTPException

from disco.server.session import store

router = APIRouter(tags=["catalogs"])

try:
    from astroquery.simbad import Simbad
    ASTROQUERY_AVAILABLE = True
except ImportError:
    ASTROQUERY_AVAILABLE = False


@router.get("/query_simbad")
def query_simbad(image_id: str | None = None):
    if not ASTROQUERY_AVAILABLE:
        raise HTTPException(501, detail="astroquery is not installed.")
    img = store.images.get(image_id) if image_id else store.active()
    if not img or img.header is None:
        raise HTTPException(400, detail="No header loaded.")
    try:
        wcs = WCS(img.header)
        if wcs.naxis > 2:
            wcs = wcs.celestial
        nx = img.header.get("NAXIS1", img.data.shape[1])
        ny = img.header.get("NAXIS2", img.data.shape[0])
        center_sky = wcs.pixel_to_world(nx / 2, ny / 2)
        custom = Simbad()
        for field in ("otype", "flux(V)", "V", "distance", "mesdistance"):
            try:
                custom.add_votable_fields(field)
            except Exception:
                pass
        result_table = custom.query_region(center_sky, radius=2 * u.arcmin)
        if result_table is None:
            return {"found": False, "data": []}
        json_data = []
        for row in result_table:
            item = {}
            for col in result_table.colnames:
                val = row[col]
                if isinstance(val, bytes):
                    val = val.decode("utf-8")
                if np.ma.is_masked(val):
                    val = ""
                if isinstance(val, (np.integer, int)):
                    val = int(val)
                elif isinstance(val, (np.floating, float)):
                    val = float(val)
                item[col] = val
            json_data.append(item)
        return {"found": True, "data": json_data}
    except Exception as e:
        raise HTTPException(500, detail=str(e))
