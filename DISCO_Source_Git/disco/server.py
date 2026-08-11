import os
import shutil
import io
import base64
import webbrowser
from typing import Optional

import threading
import time

import uvicorn
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from matplotlib.ticker import FixedLocator

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
import socket

from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize, curve_fit
from astropy.visualization import ImageNormalize, AsinhStretch, LogStretch, LinearStretch, SqrtStretch

from disco.core.optimization import geometric_loss

try:
    from astroquery.simbad import Simbad
    ASTROQUERY_AVAILABLE = True
except ImportError:
    ASTROQUERY_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(os.getcwd(), ".disco_uploads")
DEFAULT_CDELT_DEG = 1e-5  # ~0.036"/pix — typical ALMA-scale fallback
SIMBAD_TIMEOUT_SEC = 15

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class GlobalState:
    data = None
    header = None
    filename = None
    results = {}
    extents = {}
    profile_data = None
    pixel_scale_warning = None

state = GlobalState()

def clear_analysis_state():
    state.results = {}
    state.extents = {}
    state.profile_data = None

def wipe_session_logic():
    state.data = None
    state.header = None
    state.filename = None
    state.pixel_scale_warning = None
    clear_analysis_state()

    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception:
                pass
    else:
        os.makedirs(UPLOAD_DIR, exist_ok=True)

def safe_upload_basename(filename):
    if not filename:
        raise HTTPException(status_code=400, detail="Missing upload filename.")
    name = os.path.basename(filename.replace("\\", "/"))
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid upload filename.")
    return name

def extract_image_from_hdul(hdul):
    """Return (2D float array, header) from the first image HDU with data."""
    for hdu in hdul:
        if hdu.data is None:
            continue
        data = np.squeeze(hdu.data)
        if data.ndim == 0:
            continue
        while data.ndim > 2:
            # Prefer Stokes I / first plane for cubes
            data = data[0]
        if data.ndim != 2:
            continue
        arr = np.nan_to_num(np.asarray(data, dtype=np.float64))
        return arr, hdu.header
    raise HTTPException(
        status_code=400,
        detail="No 2D image data found in FITS file. DISCO expects a 2D image (or a cube from which a plane can be taken).",
    )

def get_pixel_scale_arcsec(header):
    """Pixel scale in arcsec/pix. Warns when CDELT2 is missing or invalid."""
    warning = None
    raw = header.get("CDELT2", None) if header is not None else None
    try:
        cdelt = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        cdelt = None
    if cdelt is None or abs(cdelt) == 0.0:
        cdelt = DEFAULT_CDELT_DEG
        warning = (
            f"CDELT2 missing or zero; using fallback {DEFAULT_CDELT_DEG} deg/pix "
            f"({abs(DEFAULT_CDELT_DEG) * 3600:.4f} arcsec/pix). Radii may be wrong."
        )
    pixel_scale = abs(cdelt) * 3600.0
    if pixel_scale <= 0:
        raise HTTPException(status_code=400, detail="Invalid pixel scale (CDELT2).")
    return pixel_scale, warning

def ensure_2d_data(data):
    if data is None:
        raise HTTPException(status_code=400, detail="No FITS data loaded.")
    if getattr(data, "ndim", None) != 2:
        raise HTTPException(
            status_code=400,
            detail=f"Image must be 2D after load; got shape {getattr(data, 'shape', None)}.",
        )
    return data

wipe_session_logic()

@app.on_event("shutdown")
def cleanup_on_shutdown():
    print("\n[INFO] Cleaning directory and temporary files...")
    wipe_session_logic()

@app.post("/reset_session")
def reset_session_endpoint():
    wipe_session_logic()
    return {"status": "Session cleared"}

class PlotParams(BaseModel):
    type: str
    cmap: str = 'magma'
    stretch: str = 'asinh'
    vmax_percentile: Optional[float] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    contours: bool = False
    contour_levels: int = 5
    contour_mode: str = 'count'  # 'count' | 'percentiles'
    contour_percentiles: Optional[str] = "50,70,90,95,99"
    show_beam: bool = False
    show_grid: bool = False
    show_axes: bool = True
    show_colorbar: bool = True
    title: Optional[str] = ""
    dpi: int = 150

class PipelineParams(BaseModel):
    cx: float
    cy: float
    pa: float
    incl: float
    rout: float
    fit_rmin: float = 0.0
    fit_rmax: float = 0.0

class OptimizeParams(BaseModel):
    cx: float
    cy: float
    pa: float
    incl: float
    rout: float
    fit_rmin: float = 0.0
    fit_rmax: float = 0.0

class LoadLocalParams(BaseModel):
    filename: str

def array_to_base64(data_array, cmap='magma', stretch_val=0.03):
    mx = np.nanmax(data_array)
    if np.isnan(mx) or mx <= 0:
        mx = 1.0
    norm = ImageNormalize(vmin=0.0, vmax=mx, stretch=AsinhStretch(stretch_val))

    fig = plt.figure(figsize=(6, 6), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.imshow(data_array, origin='lower', cmap=cmap, norm=norm, interpolation='nearest', aspect='auto')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

def gaussian(x, a, x0, sigma, c):
    return a * np.exp(-(x - x0) ** 2 / (2 * sigma ** 2)) + c


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        safe_name = safe_upload_basename(file.filename)
        file_location = os.path.join(UPLOAD_DIR, safe_name)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        with fits.open(file_location) as hdul:
            data, header = extract_image_from_hdul(hdul)
            state.data = data
            state.header = header
            state.filename = file_location
            clear_analysis_state()
            if np.max(state.data) < 0.1:
                state.data *= 1000
            pixel_scale, warning = get_pixel_scale_arcsec(state.header)
            state.pixel_scale_warning = warning
        payload = {
            "filename": safe_name,
            "status": "loaded",
            "shape": list(state.data.shape),
            "pixel_scale": pixel_scale,
        }
        if warning:
            payload["warning"] = warning
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/load_local")
def load_local(params: LoadLocalParams):
    clean_name = safe_upload_basename(params.filename)
    file_path = os.path.join(UPLOAD_DIR, clean_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with fits.open(file_path) as hdul:
            data, header = extract_image_from_hdul(hdul)
            state.data = data
            state.header = header
            state.filename = file_path
            clear_analysis_state()
            if np.max(state.data) < 0.1:
                state.data *= 1000
            pixel_scale, warning = get_pixel_scale_arcsec(state.header)
            state.pixel_scale_warning = warning
        payload = {
            "status": "loaded",
            "filename": clean_name,
            "shape": list(state.data.shape),
            "pixel_scale": pixel_scale,
        }
        if warning:
            payload["warning"] = warning
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/preview")
def get_preview():
    if state.data is None:
        raise HTTPException(status_code=404, detail="No data")
    img_b64 = array_to_base64(state.data, cmap='inferno', stretch_val=0.02)
    return {"image": f"data:image/png;base64,{img_b64}"}

@app.get("/get_header")
def get_header():
    if state.header is None:
        return {"header": []}
    header_list = []
    for key, value in state.header.items():
        if key == 'COMMENT' or key == 'HISTORY':
            continue
        try:
            comment = state.header.comments[key]
        except Exception:
            comment = ""
        header_list.append({"key": key, "value": str(value), "comment": comment})
    return {"header": header_list}

@app.post("/optimize_geometry")
def optimize_geometry(params: OptimizeParams):
    try:
        from scipy.ndimage import gaussian_filter

        data = ensure_2d_data(state.data)
        ny, nx = data.shape

        # Display (Konva, origin top-left) → FITS array indexing (origin lower-left)
        eff_cy = ny - params.cy
        eff_cx = params.cx

        pad = 1000
        d_pad = np.pad(data, pad, mode='constant', constant_values=0)

        real_cy_int = int(eff_cy) + pad
        real_cx_int = int(eff_cx) + pad

        offset_y = (eff_cy + pad) - real_cy_int
        offset_x = (eff_cx + pad) - real_cx_int

        pixel_scale, _ = get_pixel_scale_arcsec(state.header)

        # Use Rout when no ring-fit range is set (fit_rmax=0 was starving the loss)
        fit_rmax_eff = params.fit_rmax if params.fit_rmax > params.fit_rmin else params.rout
        search_rad = max(params.rout, fit_rmax_eff, 0.1)
        search_rad_pix = max(int(search_rad / pixel_scale), 5)
        crop_rad = int(search_rad_pix * 1.2) + 10

        dc = d_pad[real_cy_int - crop_rad: real_cy_int + crop_rad, real_cx_int - crop_rad: real_cx_int + crop_rad]
        if dc.size == 0 or min(dc.shape) < 8:
            raise HTTPException(status_code=400, detail="Crop around center is empty. Check Center X/Y and Radius Out.")

        local_c_y = crop_rad + offset_y
        local_c_x = crop_rad + offset_x

        rmin_pix = max(0.0, params.fit_rmin / pixel_scale)
        rmax_pix = max(fit_rmax_eff / pixel_scale, rmin_pix + 5)

        # Mild smooth for the coarse grid search (same idea as CLI hybrid path)
        bmaj_pix = 0.0
        if state.header is not None and state.header.get('BMAJ'):
            try:
                bmaj_pix = float(state.header['BMAJ']) * 3600 / pixel_scale
            except Exception:
                bmaj_pix = 0.0
        sigma_smooth = max(bmaj_pix * 0.4, 1.0)
        dc_smooth = gaussian_filter(dc, sigma=sigma_smooth)

        seed_incl = float(np.clip(params.incl if params.incl > 0 else 30.0, 5.0, 80.0))
        seed_pa = float(params.pa % 180)
        best_guess = [seed_incl, seed_pa, 0.0, 0.0]

        test_incls = [10, 20, 30, 40, 50, 60, 70]
        test_pas = range(0, 180, 15)

        min_loss = geometric_loss(best_guess, dc_smooth, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, dim=100, order=1)

        for ti in test_incls:
            for tp in test_pas:
                l = geometric_loss([ti, tp, 0.0, 0.0], dc_smooth, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, dim=100, order=1)
                if l < min_loss:
                    min_loss = l
                    best_guess = [ti, tp, 0.0, 0.0]

        # L-BFGS-B respects bounds (Nelder-Mead ignores them in SciPy)
        bounds = [(0.0, 85.0), (0.0, 180.0), (-15.0, 15.0), (-15.0, 15.0)]
        res = minimize(
            geometric_loss,
            best_guess,
            args=(dc, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, 300, 3),
            method='L-BFGS-B',
            bounds=bounds,
            options={'maxiter': 400, 'ftol': 1e-8},
        )

        best_incl, best_pa, best_dx, best_dy = [float(v) for v in res.x]
        best_pa = best_pa % 180
        if best_pa < 0:
            best_pa += 180
        best_incl = float(np.clip(best_incl, 0.0, 85.0))

        # Convert optimized center back to display coordinates
        new_eff_cx = eff_cx + best_dx
        new_eff_cy = eff_cy + best_dy
        optimized_cx = float(new_eff_cx)
        optimized_cy = float(ny - new_eff_cy)

        return {
            "optimized_incl": best_incl,
            "optimized_pa": best_pa,
            "optimized_cx": optimized_cx,
            "optimized_cy": optimized_cy,
            "dx": best_dx,
            "dy": best_dy,
            "loss": float(res.fun) if np.isfinite(res.fun) else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {e}")


@app.post("/run_pipeline")
def run_pipeline(params: PipelineParams):
    try:
        data = ensure_2d_data(state.data)
        ny, nx = data.shape

        eff_cy = ny - params.cy
        eff_cx = params.cx

        pa_rad = np.radians(params.pa)
        incl_rad = np.radians(params.incl)
        pixel_scale, _ = get_pixel_scale_arcsec(state.header)

        crop_size = 2000
        crop_rad = crop_size // 2
        pad = crop_rad
        d_pad = np.pad(data, pad, mode='constant', constant_values=0)

        y_start_int = int(eff_cy) + pad - crop_rad
        x_start_int = int(eff_cx) + pad - crop_rad

        local_cy = (eff_cy + pad) - y_start_int
        local_cx = (eff_cx + pad) - x_start_int

        dc = d_pad[y_start_int: y_start_int + crop_size, x_start_int: x_start_int + crop_size]

        if dc.shape != (crop_size, crop_size):
            temp = np.zeros((crop_size, crop_size))
            h, w = dc.shape
            temp[0:h, 0:w] = dc
            dc = temp

        beam_info = None
        try:
            if state.header is not None and 'BMAJ' in state.header and 'BMIN' in state.header:
                beam_info = {
                    "major": state.header['BMAJ'] * 3600,
                    "minor": state.header['BMIN'] * 3600,
                    "pa": state.header.get('BPA', 0.0)
                }
        except Exception:
            pass

        dim = 1000
        x = np.arange(dim) - 500
        X, Y = np.meshgrid(x, x)
        Xc = X * np.cos(incl_rad)
        Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
        Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y

        coords_deproj = [Yrot + local_cy, -Xrot + local_cx]
        deproj = map_coordinates(dc, coords_deproj, order=3, cval=0.0)
        deproj = np.fliplr(deproj)

        max_radius_pix = np.hypot(500, 500)
        n_steps = int(max_radius_pix)
        r_full = np.linspace(0, max_radius_pix, n_steps)
        th = np.linspace(-180, 180, 361)
        R, TH = np.meshgrid(r_full, th)
        Xd = R * np.cos(np.radians(TH))
        Yd = R * np.sin(np.radians(TH))
        coords_polar = [Yd + 500, Xd + 500]
        polar_full = map_coordinates(deproj, coords_polar, order=1)
        polar_full = np.flipud(polar_full)

        prof_full = np.nanmean(polar_full, axis=0)
        d_map = np.sqrt(X ** 2 + Y ** 2)
        mod = np.interp(d_map.flatten(), r_full, prof_full).reshape(dim, dim)
        resi = deproj - mod

        rout_pix = params.rout / pixel_scale
        limit_idx = np.searchsorted(r_full, rout_pix)
        limit_idx = min(limit_idx, n_steps)
        polar_display = polar_full[:, :limit_idx]
        prof_display = prof_full[:limit_idx]
        r_display = r_full[:limit_idx]

        try:
            bmaj = state.header.get('BMAJ', 0) * 3600
            bmin = state.header.get('BMIN', 0) * 3600
            restfrq = state.header.get('RESTFRQ', 230e9)
            if bmaj > 0 and bmin > 0:
                beam_sr = (np.pi * bmaj * bmin / (4 * np.log(2))) / 206265 ** 2
                kB = 1.38e-16
                c = 3e10
                tb_prof = (c ** 2 * 1e-23 * prof_display / 1000) / (2 * kB * restfrq ** 2 * beam_sr)
            else:
                tb_prof = prof_display
        except Exception:
            tb_prof = prof_display

        r_arcsec = r_display * pixel_scale
        start = crop_rad - 500
        end = crop_rad + 500
        dc_view = dc[start:end, start:end]

        fov_arcsec = 1000 * pixel_scale
        limit_arcsec = fov_arcsec / 2
        ext_cartesian = [limit_arcsec, -limit_arcsec, -limit_arcsec, limit_arcsec]
        ext_polar = [0, params.rout, -180, 180]

        state.results = {'data': dc_view, 'deproj': deproj, 'polar': polar_display, 'model': mod, 'residuals': resi}
        state.extents = {'data': ext_cartesian, 'deproj': ext_cartesian, 'model': ext_cartesian, 'residuals': ext_cartesian, 'polar': ext_polar}
        prof_jy = prof_display / 1000.0
        state.profile_data = {'radius': r_arcsec.tolist(), 'tb': tb_prof.tolist(), 'raw': prof_jy.tolist()}

        fit_stats = None
        if params.fit_rmax > params.fit_rmin and (params.fit_rmax - params.fit_rmin) > 0.05:
            try:
                mask = (r_arcsec >= params.fit_rmin) & (r_arcsec <= params.fit_rmax)
                x_region = r_arcsec[mask]
                y_region = tb_prof[mask]

                if len(y_region) > 5:
                    idx_max = np.argmax(y_region)
                    amp_guess = y_region[idx_max]
                    mean_guess = x_region[idx_max]

                    if amp_guess > 0:
                        sigma_guess = (params.fit_rmax - params.fit_rmin) / 4
                        p0 = [amp_guess, mean_guess, sigma_guess, 0.0]
                        popt, _ = curve_fit(gaussian, x_region, y_region, p0=p0, maxfev=2000)
                        fwhm = 2.355 * abs(popt[2])
                        fit_stats = {
                            "peak_radius": float(popt[1]),
                            "fwhm": float(fwhm),
                            "peak_intensity": float(popt[0])
                        }
            except Exception:
                fit_stats = None

        fov_cartesian = 1000 * pixel_scale
        fov_polar = params.rout

        return {
            "images": {
                "data": f"data:image/png;base64,{array_to_base64(dc_view, cmap='inferno')}",
                "deproj": f"data:image/png;base64,{array_to_base64(deproj, cmap='inferno')}",
                "polar": f"data:image/png;base64,{array_to_base64(polar_display, cmap='inferno', stretch_val=0.1)}",
                "model": f"data:image/png;base64,{array_to_base64(mod, cmap='inferno')}",
                "residuals": f"data:image/png;base64,{array_to_base64(resi, cmap='magma', stretch_val=0.9)}"
            },
            "profile": {"radius": r_arcsec.tolist(), "intensity": tb_prof.tolist(), "raw_intensity": prof_jy.tolist()},
            "geometry": {"fov_cartesian": fov_cartesian, "fov_polar": fov_polar, "beam": beam_info, "pixel_scale": pixel_scale},
            "fit": fit_stats
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

@app.post("/render_plot")
def render_plot(params: PlotParams):
    plt.style.use('default')

    if params.type in ['polar', 'profile']:
        fig = plt.figure(figsize=(12, 5), dpi=params.dpi)
    else:
        fig = plt.figure(figsize=(10, 10), dpi=params.dpi)

    if params.type == 'profile':
        if state.profile_data is None:
            plt.close(fig)
            raise HTTPException(status_code=400, detail="Profile data not available.")

        ax = fig.add_subplot(111)
        ax.set_facecolor('white')

        x = np.array(state.profile_data['radius'])
        y = np.array(state.profile_data['tb'])
        safe_y = np.where((y > 0) & np.isfinite(y), y, 1e-10)

        ax.plot(x, safe_y, 'k', lw=1.5)
        ax.set_yscale('log')

        vmin = params.vmin
        vmax = params.vmax
        if vmin is None:
            vmin = np.min(safe_y) if len(safe_y) > 0 else 0.1
        if vmax is None:
            vmax = np.max(safe_y) if len(safe_y) > 0 else 100

        ax.set_xlim(0, x[-1] if len(x) > 0 else 1)
        ax.set_ylim(vmin, vmax)

        ax.set_xlabel("Radius [arcsec]", fontsize=12)
        ax.set_ylabel("Tb [K]", fontsize=12)
        ax.tick_params(direction='in', labelsize=10)
        if params.show_grid:
            ax.grid(True, which='both', color='gray', alpha=0.3, linestyle='--')

        title_txt = params.title if params.title else "Radial Profile"
        ax.set_title(title_txt, fontweight='bold', fontsize=14)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, facecolor='white')
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return {
            "image": f"data:image/png;base64,{img_b64}",
            "stats": {
                "min": float(np.min(safe_y)),
                "max": float(np.max(safe_y)),
                "vmin_used": float(vmin),
                "vmax_used": float(vmax),
                "cmap_used": params.cmap
            }
        }

    image_data = None
    if state.results and params.type in state.results:
        image_data = state.results[params.type]
    elif params.type == 'data' and state.data is not None:
        image_data = state.data

    if image_data is None:
        plt.close(fig)
        raise HTTPException(status_code=400, detail=f"Data for '{params.type}' not available.")

    if params.show_axes:
        ax = fig.add_subplot(111)
        ax.set_facecolor('white')
    else:
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')

    vmin = params.vmin
    vmax = params.vmax

    if vmin is None:
        if params.type == 'residuals':
            limit = np.percentile(np.abs(image_data), 100)
            vmin = -limit
            vmax = limit if vmax is None else vmax
        else:
            vmin = 0.0

    if vmax is None:
        if params.type != 'residuals':
            vmax = np.percentile(image_data, 100)

    if vmax <= vmin:
        vmax = vmin + 1e-10

    if params.stretch == 'log':
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=LogStretch())
    elif params.stretch == 'linear':
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=LinearStretch())
    elif params.stretch == 'sqrt':
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=SqrtStretch())
    else:
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.02))

    aspect = 'auto' if params.type == 'polar' else 'equal'
    extent = state.extents.get(params.type, None) if state.extents else None

    # Fallback extent (arcsec) so beam/axes work even before / after partial pipeline state
    if extent is None and params.type != 'polar':
        try:
            pixel_scale, _ = get_pixel_scale_arcsec(state.header)
            ny_img, nx_img = image_data.shape
            half_x = (nx_img * pixel_scale) / 2.0
            half_y = (ny_img * pixel_scale) / 2.0
            extent = [half_x, -half_x, -half_y, half_y]
        except Exception:
            extent = None

    im = ax.imshow(image_data, origin='lower', cmap=params.cmap, norm=norm, aspect=aspect, extent=extent)

    if params.show_axes:
        if params.title:
            ax.set_title(params.title, fontweight='bold', fontsize=14)
        else:
            titles = {'data': "Input Data", 'deproj': "Deprojected View", 'polar': "Polar Map", 'model': "Azimuthal Model", 'residuals': "Residual Map"}
            ax.set_title(titles.get(params.type, params.type.capitalize()), fontweight='bold', fontsize=14)

        ax.tick_params(direction='in', labelsize=10, color='black')
        if params.type == 'polar':
            ax.set_xlabel("Radius [arcsec]", fontsize=12)
            ax.set_ylabel("Azimuth [deg]", fontsize=12)
        else:
            ax.set_xlabel("RA Offset [arcsec]", fontsize=12)
            ax.set_ylabel("Dec Offset [arcsec]", fontsize=12)

        if params.show_grid:
            ax.grid(True, color='white', alpha=0.3, linestyle='--')

        if params.show_colorbar:
            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            if vmax <= 10 and params.stretch == 'asinh':
                cbar.locator = FixedLocator([0.0, 0.2, 0.5, 1.0, 2.0, 4.0])
                cbar.update_ticks()
            cbar.set_label('Intensity', fontsize=10)
            cbar.ax.tick_params(labelsize=9)

    if params.contours:
        try:
            levels = None
            mode = (params.contour_mode or 'count').lower()
            if mode == 'percentiles' and params.contour_percentiles:
                pcts = []
                for part in str(params.contour_percentiles).split(','):
                    part = part.strip()
                    if not part:
                        continue
                    pcts.append(float(part))
                pcts = [p for p in pcts if 0.0 <= p <= 100.0]
                if pcts:
                    levels = np.percentile(image_data[np.isfinite(image_data)], pcts)
            if levels is None:
                n_levels = max(1, int(params.contour_levels))
                # Explicit values between vmin/vmax keep canvas layout stable vs auto-count
                levels = np.linspace(vmin, vmax, n_levels + 2)[1:-1]
            levels = np.asarray(levels, dtype=float)
            levels = levels[np.isfinite(levels)]
            if levels.size > 0:
                ax.contour(
                    image_data, levels=levels, colors='white', alpha=0.55,
                    linewidths=0.8, extent=extent
                )
        except Exception:
            pass

    if params.show_beam and params.type != 'polar':
        try:
            if state.header is not None and 'BMAJ' in state.header:
                bmaj = float(state.header['BMAJ']) * 3600
                bmin = float(state.header.get('BMIN', state.header['BMAJ'])) * 3600
                bpa = float(state.header.get('BPA', 0.0) or 0.0)
                if extent is not None:
                    width_phys = abs(extent[1] - extent[0])
                    height_phys = abs(extent[3] - extent[2])
                    # Classic ALMA beam placement: bottom-left of frame
                    x0 = min(extent[0], extent[1]) + width_phys * 0.08
                    y0 = min(extent[2], extent[3]) + height_phys * 0.08
                    beam_patch = Ellipse(
                        (x0, y0), width=bmin, height=bmaj, angle=bpa,
                        facecolor='white', edgecolor='black', linewidth=1.0, zorder=20, alpha=0.95
                    )
                    ax.add_patch(beam_patch)
        except Exception:
            pass

    # Fixed margins avoid the "canvas jump" when toggling contours/colorbar
    if params.show_axes:
        fig.subplots_adjust(left=0.12, right=0.90 if params.show_colorbar else 0.96, top=0.90, bottom=0.12)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches=None, pad_inches=0.0, facecolor='white')
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, transparent=True, facecolor='white')
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')

    return {
        "image": f"data:image/png;base64,{img_b64}",
        "stats": {
            "min": float(np.min(image_data)),
            "max": float(np.max(image_data)),
            "vmin_used": float(vmin),
            "vmax_used": float(vmax),
            "cmap_used": params.cmap
        }
    }

@app.get("/download_fits")
def download_fits(type: str):
    if type in state.results:
        data_to_save = state.results[type]
    elif type == 'data' and state.data is not None:
        data_to_save = state.data
    else:
        raise HTTPException(status_code=400, detail="Data not found")
    hdu = fits.PrimaryHDU(data=data_to_save, header=state.header)
    buf = io.BytesIO()
    hdu.writeto(buf)
    buf.seek(0)
    return Response(content=buf.read(), media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=result_{type}.fits"})

@app.get("/query_simbad")
def query_simbad():
    if not ASTROQUERY_AVAILABLE:
        raise HTTPException(status_code=501, detail="astroquery is not installed.")
    if state.header is None:
        raise HTTPException(status_code=400, detail="No header loaded.")
    try:
        wcs = WCS(state.header)
        if wcs.naxis > 2:
            wcs = wcs.celestial
        nx = state.header.get('NAXIS1', 0)
        ny = state.header.get('NAXIS2', 0)
        center_sky = wcs.pixel_to_world(nx / 2, ny / 2)
        custom_simbad = Simbad()
        custom_simbad.add_votable_fields('otype', 'flux(V)', 'distance')
        try:
            custom_simbad.TIMEOUT = SIMBAD_TIMEOUT_SEC
        except Exception:
            pass
        try:
            result_table = custom_simbad.query_region(center_sky, radius=2 * u.arcmin)
        except Exception as net_err:
            raise HTTPException(
                status_code=503,
                detail=f"SIMBAD unavailable (network/timeout after {SIMBAD_TIMEOUT_SEC}s): {net_err}",
            )
        if result_table is None:
            return {"found": False, "data": []}
        json_data = []
        for row in result_table:
            item = {}
            for col in result_table.colnames:
                val = row[col]
                if isinstance(val, bytes):
                    val = val.decode('utf-8')
                if np.ma.is_masked(val):
                    val = ""
                if isinstance(val, (np.integer, int)):
                    val = int(val)
                elif isinstance(val, (np.floating, float)):
                    val = float(val)
                item[col] = val
            json_data.append(item)
        return {"found": True, "data": json_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SIMBAD query failed: {e}")

def _static_ready():
    index_path = os.path.join(STATIC_DIR, "index.html")
    assets_dir = os.path.join(STATIC_DIR, "assets")
    return os.path.isfile(index_path) and os.path.isdir(assets_dir)

if _static_ready():
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    if not _static_ready():
        raise HTTPException(
            status_code=503,
            detail=(
                "GUI static assets missing. Build the frontend first: "
                "cd DISCO_Source_Git/client && npm ci && npm run build"
            ),
        )
    # Prevent path traversal outside STATIC_DIR
    candidate = os.path.normpath(os.path.join(STATIC_DIR, full_path))
    if not candidate.startswith(os.path.normpath(STATIC_DIR) + os.sep) and candidate != os.path.normpath(STATIC_DIR):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if full_path and os.path.isfile(candidate):
        response = FileResponse(candidate)
    else:
        response = FileResponse(os.path.join(STATIC_DIR, "index.html"))

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def get_free_port():
    port = 8000
    for _ in range(1000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
            port += 1
    raise RuntimeError("No free TCP port found starting from 8000.")

def start_server():
    if not _static_ready():
        print("\n[ERROR] GUI static assets not found.")
        print(f"  Expected: {os.path.join(STATIC_DIR, 'index.html')}")
        print("  Build with: cd DISCO_Source_Git/client && npm ci && npm run build")
        print("  (Use npm run build — not build:disco — on v1.)\n")
        raise SystemExit(1)

    port = get_free_port()
    url = f"http://localhost:{port}"
    
    print("\n" + "="*50)
    print("        DISCO GUI IS RUNNING")
    print(f"   URL: {url}")
    print("   Press Ctrl+C to stop the server safely")
    print("="*50 + "\n")
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

if __name__ == "__main__":
    start_server()