"""Session lifecycle, history, and reproducibility exports."""
from __future__ import annotations

import os

from fastapi import APIRouter

from disco.core.fits_io import load_fits
from disco.server.schemas import SessionRestoreParams
from disco.server.session import ImageEntry, new_image_id, store

router = APIRouter(tags=["session"])


@router.post("/reset_session")
def reset_session(wipe_disk: bool = False):
    """Clear in-memory session. Does not wipe uploads by default (fixes restore)."""
    store.clear(wipe_disk=wipe_disk)
    return {"status": "Session cleared"}


@router.get("/session")
def get_session():
    return store.export_state()


@router.post("/session/restore")
def restore_session(params: SessionRestoreParams):
    state = params.state
    store.clear(wipe_disk=False)
    store.regions = state.get("regions", [])
    store.layout = state.get("layout")
    store.viz = state.get("viz", {})
    for item in state.get("images", []):
        basename = item.get("path") or item.get("filename")
        if not basename:
            continue
        # Find file in uploads
        matches = []
        for name in os.listdir(store.upload_dir):
            if name == basename or name.endswith("_" + basename) or basename in name:
                matches.append(os.path.join(store.upload_dir, name))
        if not matches:
            continue
        loaded = load_fits(matches[0])
        image_id = item.get("id") or new_image_id()
        entry = ImageEntry(
            id=image_id,
            filename=item.get("filename", basename),
            path=matches[0],
            data=loaded["data"],
            header=loaded["header"],
            pixel_scale=loaded["pixel_scale"],
            params=item.get("params") or {},
        )
        store.add_image(entry, set_active=False)
    if state.get("active_id") and state["active_id"] in store.images:
        store.set_active(state["active_id"])
    elif store.images:
        store.active_id = next(iter(store.images))
    store.log("restore_session", {"n_images": len(store.images)})
    return store.export_state()


@router.get("/history")
def get_history():
    return {"history": store.history}


@router.get("/history/script")
def export_python_script():
    """Export a reproducible Python script summarizing the session actions."""
    lines = [
        "# DISCO session script (auto-generated)",
        "from disco.core.fits_io import load_fits",
        "from disco.core.profiles import run_analysis_pipeline",
        "",
    ]
    for event in store.history:
        action = event.get("action")
        payload = event.get("payload") or {}
        if action == "load_image":
            lines.append(f"# load {payload.get('filename')}")
            lines.append(f"# img = load_fits('<path_to_{payload.get('filename')}>')")
        elif action == "run_pipeline":
            p = payload.get("params") or {}
            lines.append(
                "result = run_analysis_pipeline("
                f"img['data'], img['header'], cx={p.get('cx')}, cy={p.get('cy')}, "
                f"pa={p.get('pa')}, incl={p.get('incl')}, rout={p.get('rout')}, "
                f"fit_rmin={p.get('fit_rmin', 0)}, fit_rmax={p.get('fit_rmax', 0)})"
            )
        elif action == "optimize_geometry":
            lines.append(f"# optimize -> incl={payload.get('incl')}, pa={payload.get('pa')}")
    script = "\n".join(lines) + "\n"
    return {"script": script}


@router.post("/session/regions")
def set_regions(regions: list):
    store.regions = regions
    store.log("set_regions", {"n": len(regions)})
    return {"regions": store.regions}


@router.get("/session/regions")
def get_regions():
    return {"regions": store.regions}
