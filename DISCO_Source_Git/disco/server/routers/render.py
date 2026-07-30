"""Render / preview / publication figure endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from disco.server.render_utils import array_to_base64, render_multi_panel, render_scientific_plot
from disco.server.schemas import FigureRequest, PlotParams
from disco.server.session import store

router = APIRouter(tags=["render"])


def _resolve(image_id=None):
    if image_id and image_id in store.images:
        return store.images[image_id]
    img = store.active()
    if not img:
        raise HTTPException(400, "No data")
    return img


@router.get("/preview")
def get_preview(image_id: str | None = None):
    img = _resolve(image_id)
    b64 = array_to_base64(img.data, cmap="inferno", stretch_val=0.02)
    return {"image": f"data:image/png;base64,{b64}", "image_id": img.id}


@router.post("/render_plot")
def render_plot(params: PlotParams):
    img = _resolve(params.image_id)
    try:
        return render_scientific_plot(img, params)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/figure")
def build_figure(req: FigureRequest):
    img = _resolve(req.image_id)
    if not req.panels:
        raise HTTPException(400, "No panels specified")
    return render_multi_panel(img, req.panels, ncols=req.ncols, dpi=req.dpi, fmt=req.format, title=req.title)
