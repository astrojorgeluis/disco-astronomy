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

from astropy.io import fits
from astropy.wcs import WCS
import astropy.units as u
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize, curve_fit
from astropy.visualization import ImageNormalize, AsinhStretch, LogStretch, LinearStretch, SqrtStretch

try:
    from astroquery.simbad import Simbad
    ASTROQUERY_AVAILABLE = True
except ImportError:
    ASTROQUERY_AVAILABLE = False

# PATH CONFIGURATION
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(os.getcwd(), "disco_uploads")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GLOBAL STATE & SESSION MANAGEMENT
class GlobalState:
    data = None
    header = None
    filename = None
    results = {} 
    extents = {} 
    profile_data = None 

state = GlobalState()

def wipe_session_logic():
    state.data = None
    state.header = None
    state.filename = None
    state.results = {}
    state.extents = {}
    state.profile_data = None
    
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

wipe_session_logic()

@app.post("/reset_session")
def reset_session_endpoint():
    wipe_session_logic()
    return {"status": "Session cleared"}

# PYDANTIC MODELS
class PlotParams(BaseModel):
    type: str 
    cmap: str = 'magma'
    stretch: str = 'asinh'
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

class PipelineParams(BaseModel):
    cx: float
    cy: float
    pa: float
    incl: float
    rout: float
    contrast: float = 2.0
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

# UTILITY FUNCTIONS
def array_to_base64(data_array, cmap='magma', stretch_val=0.03):
    mx = np.nanmax(data_array)
    if np.isnan(mx) or mx <= 0: mx = 1.0
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
    return a * np.exp(-(x - x0)**2 / (2 * sigma**2)) + c

def geometric_loss(params, image, local_cx, local_cy, crop_rad, rmin_pix, rmax_pix, dim=200, order=1):
    incl, pa = params
    if not (0 <= incl < 90): return 1e12 
    
    x = np.arange(dim) - dim/2
    X, Y = np.meshgrid(x, x)
    
    incl_rad = np.radians(incl)
    pa_rad = np.radians(pa)
    
    Xc = X * np.cos(incl_rad)
    Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
    Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y
    
    scale = (crop_rad * 2) / dim
    
    # SAMPLING COORDINATES
    coords = [Yrot * scale + local_cy, -Xrot * scale + local_cx]
    
    deproj = map_coordinates(image, coords, order=order, mode='constant', cval=0.0)
    
    r_steps, th_steps = int(dim/2), 180
    r = np.linspace(0, dim/2, r_steps)
    th = np.linspace(-np.pi, np.pi, th_steps)
    R, TH = np.meshgrid(r, th)
    Xd = R * np.cos(TH) + dim/2
    Yd = R * np.sin(TH) + dim/2
    
    polar = map_coordinates(deproj, [Yd, Xd], order=1, mode='constant', cval=0.0)
    
    scale_polar = r_steps / crop_rad
    idx_min = int(rmin_pix * scale_polar)
    idx_max = int(rmax_pix * scale_polar)
    
    idx_min = max(0, idx_min)
    idx_max = min(r_steps, idx_max)
    
    if idx_max <= idx_min + 2: 
        idx_min, idx_max = 0, r_steps

    polar_crop = polar[:, idx_min:idx_max]
    profile = np.mean(polar_crop, axis=0)
    model = np.tile(profile, (th_steps, 1))
    
    residual = np.sum((polar_crop - model)**2)
    return residual

# ENDPOINTS: FILE MANAGEMENT
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_location = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        with fits.open(file_location) as hdul:
            state.data = np.nan_to_num(np.squeeze(hdul[0].data))
            state.header = hdul[0].header
            state.filename = file_location
            state.results = {}
            if np.max(state.data) < 0.1:
                state.data *= 1000
            cdelt = state.header.get('CDELT2', 0.03) 
            pixel_scale = abs(cdelt) * 3600
        return {"filename": file.filename, "status": "loaded", "shape": state.data.shape, "pixel_scale": pixel_scale}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/load_local")
def load_local(params: LoadLocalParams):
    clean_name = os.path.basename(params.filename)
    file_path = os.path.join(UPLOAD_DIR, clean_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with fits.open(file_path) as hdul:
            state.data = np.nan_to_num(np.squeeze(hdul[0].data))
            state.header = hdul[0].header
            state.filename = file_path
            state.results = {}
            if np.max(state.data) < 0.1:
                state.data *= 1000
            cdelt = state.header.get('CDELT2', 0.03)
            pixel_scale = abs(cdelt) * 3600
        return {"status": "loaded", "filename": clean_name, "shape": state.data.shape, "pixel_scale": pixel_scale}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/preview")
def get_preview():
    if state.data is None: raise HTTPException(status_code=404, detail="No data")
    img_b64 = array_to_base64(state.data, cmap='inferno', stretch_val=0.02)
    return {"image": f"data:image/png;base64,{img_b64}"}

@app.get("/get_header")
def get_header():
    if state.header is None: return {"header": []}
    header_list = []
    for key, value in state.header.items():
        if key == 'COMMENT' or key == 'HISTORY': continue 
        header_list.append({"key": key, "value": str(value), "comment": state.header.comments[key]})
    return {"header": header_list}

# ENDPOINTS: GEOMETRY OPTIMIZATION
@app.post("/optimize_geometry")
def optimize_geometry(params: OptimizeParams):
    if state.data is None: raise HTTPException(status_code=400, detail="No Data")
    
    data = state.data
    ny, nx = data.shape
    
    # COORDINATE FLIP FOR KONVA/MATPLOTLIB COMPATIBILITY
    eff_cy = ny - params.cy
    eff_cx = params.cx

    pad = 1000
    d_pad = np.pad(data, pad, mode='constant', constant_values=0)
    
    real_cy_int = int(eff_cy) + pad
    real_cx_int = int(eff_cx) + pad
    
    offset_y = (eff_cy + pad) - real_cy_int
    offset_x = (eff_cx + pad) - real_cx_int
    
    pixel_scale = abs(state.header.get('CDELT2', 0.03)) * 3600
    
    search_rad = max(params.rout, params.fit_rmax)
    search_rad_pix = int(search_rad / pixel_scale)
    crop_rad = int(search_rad_pix * 1.2) + 10 
    
    dc = d_pad[real_cy_int - crop_rad : real_cy_int + crop_rad, 
               real_cx_int - crop_rad : real_cx_int + crop_rad]
    
    local_c_y = crop_rad + offset_y
    local_c_x = crop_rad + offset_x
    
    rmin_pix = params.fit_rmin / pixel_scale
    rmax_pix = params.fit_rmax / pixel_scale
    
    best_guess = [params.incl, params.pa]
    
    # GRID SEARCH PHASE
    if params.incl < 5.0 or True:
        test_incls = [10, 30, 50, 70]
        test_pas = range(0, 180, 30)
        
        min_loss = geometric_loss(best_guess, dc, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, dim=100, order=1)
        
        for ti in test_incls:
            for tp in test_pas:
                l = geometric_loss([ti, tp], dc, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, dim=100, order=1)
                if l < min_loss:
                    min_loss = l
                    best_guess = [ti, tp]

    # FINE TUNING PHASE
    res = minimize(
        geometric_loss, 
        best_guess, 
        args=(dc, local_c_x, local_c_y, crop_rad, rmin_pix, rmax_pix, 400, 3), 
        method='Nelder-Mead',
        bounds=[(0, 85), (0, 180)],
        tol=0.01
    )
    
    best_incl, best_pa = res.x
    best_pa = best_pa % 180
    if best_pa < 0: best_pa += 180
    
    return {"optimized_incl": float(best_incl), "optimized_pa": float(best_pa)}

# ENDPOINTS: PROCESSING PIPELINE
@app.post("/run_pipeline")
def run_pipeline(params: PipelineParams):
    if state.data is None:
        raise HTTPException(status_code=400, detail="No FITS data loaded.")
    data = state.data
    ny, nx = data.shape
    
    # COORDINATE SYSTEM ALIGNMENT
    eff_cy = ny - params.cy
    eff_cx = params.cx
    
    pa_rad = np.radians(params.pa)
    incl_rad = np.radians(params.incl)
    pixel_scale = abs(state.header.get('CDELT2', 0.03)) * 3600
    
    crop_size = 2000
    crop_rad = crop_size // 2 
    pad = crop_rad 
    d_pad = np.pad(data, pad, mode='constant', constant_values=0)
    
    y_start_int = int(eff_cy) + pad - crop_rad
    x_start_int = int(eff_cx) + pad - crop_rad
    
    local_cy = (eff_cy + pad) - y_start_int
    local_cx = (eff_cx + pad) - x_start_int
    
    dc = d_pad[y_start_int : y_start_int + crop_size, x_start_int : x_start_int + crop_size]
    
    if dc.shape != (crop_size, crop_size):
        temp = np.zeros((crop_size, crop_size))
        h, w = dc.shape
        temp[0:h, 0:w] = dc
        dc = temp

    beam_info = None
    try:
        if 'BMAJ' in state.header:
            beam_info = {
                "major": state.header['BMAJ'] * 3600,
                "minor": state.header['BMIN'] * 3600,
                "pa": state.header.get('BPA', 0.0)
            }
    except: pass

    # DEPROJECTION
    dim = 1000
    x = np.arange(dim) - 500
    X, Y = np.meshgrid(x, x)
    Xc = X * np.cos(incl_rad)
    Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
    Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y
    
    coords_deproj = [Yrot + local_cy, -Xrot + local_cx]
    
    deproj = map_coordinates(dc, coords_deproj, order=3, cval=0.0)
    deproj = np.fliplr(deproj)

    # POLAR MAPPING
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
    d_map = np.sqrt(X**2 + Y**2)
    mod = np.interp(d_map.flatten(), r_full, prof_full).reshape(dim, dim)
    res = deproj - mod
    
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
            beam_sr = (np.pi * bmaj * bmin / (4 * np.log(2))) / 206265**2
            kB = 1.38e-16; c = 3e10
            tb_prof = (c**2 * 1e-23 * prof_display/1000) / (2 * kB * restfrq**2 * beam_sr)
        else: tb_prof = prof_display
    except: tb_prof = prof_display

    r_arcsec = r_display * pixel_scale
    start = crop_rad - 500
    end = crop_rad + 500
    dc_view = dc[start:end, start:end]

    fov_arcsec = 1000 * pixel_scale
    limit_arcsec = fov_arcsec / 2
    ext_cartesian = [limit_arcsec, -limit_arcsec, -limit_arcsec, limit_arcsec]
    ext_polar = [0, params.rout, -180, 180]

    state.results = {'data': dc_view, 'deproj': deproj, 'polar': polar_display, 'model': mod, 'residuals': res}
    state.extents = {'data': ext_cartesian, 'deproj': ext_cartesian, 'model': ext_cartesian, 'residuals': ext_cartesian, 'polar': ext_polar}
    state.profile_data = {'radius': r_arcsec.tolist(), 'tb': tb_prof.tolist()}
    
    # GAUSSIAN FITTING
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
        except Exception as e:
            print(f"Fit error: {e}")
            fit_stats = None

    fov_cartesian = 1000 * pixel_scale
    fov_polar = params.rout 

    return {
        "images": {
            "data": f"data:image/png;base64,{array_to_base64(dc_view, cmap='inferno')}",
            "deproj": f"data:image/png;base64,{array_to_base64(deproj, cmap='inferno')}",
            "polar": f"data:image/png;base64,{array_to_base64(polar_display, cmap='inferno', stretch_val=0.1)}",
            "model": f"data:image/png;base64,{array_to_base64(mod, cmap='inferno')}",
            "residuals": f"data:image/png;base64,{array_to_base64(res, cmap='magma', stretch_val=0.9)}"
        },
        "profile": {"radius": r_arcsec.tolist(), "intensity": tb_prof.tolist()},
        "geometry": {"fov_cartesian": fov_cartesian, "fov_polar": fov_polar, "beam": beam_info, "pixel_scale": pixel_scale},
        "fit": fit_stats 
    }

# ENDPOINTS: PLOTTING
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
        if vmin is None: vmin = np.min(safe_y) if len(safe_y)>0 else 0.1
        if vmax is None: vmax = np.max(safe_y) if len(safe_y)>0 else 100
        
        ax.set_xlim(0, x[-1] if len(x)>0 else 1)
        ax.set_ylim(vmin, vmax)
        
        ax.set_xlabel("Radius [arcsec]", fontsize=12)
        ax.set_ylabel("Tb [K]", fontsize=12)
        ax.tick_params(direction='in', labelsize=10)
        if params.show_grid: ax.grid(True, which='both', color='gray', alpha=0.3, linestyle='--')
            
        title_txt = params.title if params.title else "Radial Profile"
        ax.set_title(title_txt, fontweight='bold', fontsize=14)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, facecolor='white') 
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return {"image": f"data:image/png;base64,{img_b64}", "stats": {"min": float(np.min(safe_y)), "max": float(np.max(safe_y)), "vmin_used": float(vmin), "vmax_used": float(vmax)}}

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
        else: vmin = 0.0
    
    if vmax is None:
        if params.type != 'residuals': vmax = np.percentile(image_data, 100)

    if vmax <= vmin: vmax = vmin + 1e-10

    if params.stretch == 'log': norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=LogStretch())
    elif params.stretch == 'linear': norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=LinearStretch())
    elif params.stretch == 'sqrt': norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=SqrtStretch())
    else: norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.02))

    aspect = 'auto' if params.type == 'polar' else 'equal'
    extent = state.extents.get(params.type, None)
    
    im = ax.imshow(image_data, origin='lower', cmap=params.cmap, norm=norm, aspect=aspect, extent=extent)
    
    if params.show_axes:
        if params.title: ax.set_title(params.title, fontweight='bold', fontsize=14)
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

        if params.show_grid: ax.grid(True, color='white', alpha=0.3, linestyle='--')
            
        if params.show_colorbar:
            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            if vmax <= 10 and params.stretch == 'asinh':
                 cbar.locator = FixedLocator([0.0, 0.2, 0.5, 1.0, 2.0, 4.0])
                 cbar.update_ticks()
            cbar.set_label('Intensity', fontsize=10)
            cbar.ax.tick_params(labelsize=9)

    if params.contours:
        try:
            ax.contour(image_data, levels=params.contour_levels, colors='white', alpha=0.5, linewidths=0.8, extent=extent)
        except Exception: pass

    if params.show_beam and params.type != 'polar' and params.show_axes:
        try:
            if 'BMAJ' in state.header:
                bmaj = state.header['BMAJ'] * 3600
                bmin = state.header['BMIN'] * 3600
                bpa = state.header.get('BPA', 0.0)
                if extent:
                    width_phys = abs(extent[1] - extent[0])
                    height_phys = abs(extent[3] - extent[2])
                    bx = extent[0] + width_phys * 0.1
                    by = extent[2] + height_phys * 0.1
                    beam_patch = Ellipse((bx, by), width=bmin, height=bmaj, angle=bpa, facecolor='white', edgecolor='black', zorder=20)
                    ax.add_patch(beam_patch)
        except Exception: pass

    buf = io.BytesIO()
    is_transparent = not params.show_axes 
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1 if params.show_axes else 0, transparent=is_transparent, facecolor='white') 
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    
    return {
        "image": f"data:image/png;base64,{img_b64}",
        "stats": {
            "min": float(np.min(image_data)),
            "max": float(np.max(image_data)),
            "vmin_used": float(vmin),
            "vmax_used": float(vmax)
        }
    }

# ENDPOINTS: DOWNLOAD & EXTERNAL SERVICES
@app.get("/download_fits")
def download_fits(type: str):
    if type in state.results: data_to_save = state.results[type]
    elif type == 'data' and state.data is not None: data_to_save = state.data
    else: raise HTTPException(status_code=400, detail="Data not found")
    hdu = fits.PrimaryHDU(data=data_to_save, header=state.header)
    buf = io.BytesIO()
    hdu.writeto(buf)
    buf.seek(0)
    return Response(content=buf.read(), media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=result_{type}.fits"})

@app.get("/query_simbad")
def query_simbad():
    if not ASTROQUERY_AVAILABLE: raise HTTPException(status_code=501, detail="Librería 'astroquery' no instalada.")
    if state.header is None: raise HTTPException(status_code=400, detail="No header loaded.")
    try:
        wcs = WCS(state.header)
        if wcs.naxis > 2: wcs = wcs.celestial
        nx = state.header.get('NAXIS1', 0); ny = state.header.get('NAXIS2', 0)
        center_sky = wcs.pixel_to_world(nx/2, ny/2)
        custom_simbad = Simbad(); custom_simbad.add_votable_fields('otype', 'flux(V)', 'distance')
        result_table = custom_simbad.query_region(center_sky, radius=2 * u.arcmin)
        if result_table is None: return {"found": False, "data": []}
        json_data = []
        for row in result_table:
            item = {}
            for col in result_table.colnames:
                val = row[col]
                if isinstance(val, bytes): val = val.decode('utf-8')
                if np.ma.is_masked(val): val = ""
                if isinstance(val, (np.integer, int)): val = int(val)
                elif isinstance(val, (np.floating, float)): val = float(val)
                item[col] = val
            json_data.append(item)
        return {"found": True, "data": json_data}
    except Exception as e:
        print(f"Simbad Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# STATIC FILES SERVING (SPA Support)
app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):

    potential_file = os.path.join(STATIC_DIR, full_path)
    if os.path.isfile(potential_file):
        return FileResponse(potential_file)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# ENTRY POINT FOR PIP SCRIPT

def open_browser_delayed():
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000")

def start_server():
    print(f"--- Launching DISCO Analysis Tool ---")
    print(f"Working Directory: {os.getcwd()}")
    threading.Thread(target=open_browser_delayed).start()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    start_server()
