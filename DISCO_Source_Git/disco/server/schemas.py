"""Pydantic request/response schemas for the DISCO API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PipelineParams(BaseModel):
    image_id: Optional[str] = None
    cx: float
    cy: float
    pa: float
    incl: float
    rout: float
    fit_rmin: float = 0.0
    fit_rmax: float = 0.0


class OptimizeParams(BaseModel):
    image_id: Optional[str] = None
    cx: float
    cy: float
    pa: float
    incl: float
    rout: float
    fit_rmin: float = 0.0
    fit_rmax: float = 0.0


class LoadLocalParams(BaseModel):
    filename: str


class PlotParams(BaseModel):
    image_id: Optional[str] = None
    type: str
    cmap: str = "magma"
    stretch: str = "asinh"
    vmax_percentile: Optional[float] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    contours: bool = False
    contour_levels: int = 5
    show_beam: bool = False
    show_grid: bool = False
    show_axes: bool = True
    show_colorbar: bool = True
    title: Optional[str] = ""
    dpi: int = 150
    format: str = "png"  # png | pdf | svg


class PixelProbeParams(BaseModel):
    image_id: Optional[str] = None
    x: float
    y: float
    product: str = "data"  # data uses original; others use results


class RegionStatsParams(BaseModel):
    image_id: Optional[str] = None
    region: dict[str, Any]
    product: str = "data"


class SetActiveParams(BaseModel):
    image_id: str


class SessionRestoreParams(BaseModel):
    state: dict[str, Any]


class FigurePanel(BaseModel):
    type: str
    cmap: str = "magma"
    stretch: str = "asinh"
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    title: str = ""
    show_beam: bool = True
    show_colorbar: bool = True
    show_axes: bool = True


class FigureRequest(BaseModel):
    image_id: Optional[str] = None
    panels: list[FigurePanel] = Field(default_factory=list)
    ncols: int = 2
    dpi: int = 150
    format: str = "png"
    title: str = ""
