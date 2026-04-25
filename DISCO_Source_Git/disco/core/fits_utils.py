import numpy as np
import matplotlib.pyplot as plt
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord, skycoord_to_pixel
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from scipy.ndimage import (
    map_coordinates, gaussian_filter, gaussian_filter1d,
    center_of_mass, binary_fill_holes, label
)

try:
    from astroquery.gaia import Gaia as _GaiaCatalog
    import logging
    logging.getLogger('astroquery').setLevel(logging.ERROR)
    _ASTROQUERY_AVAILABLE = True
except ImportError:
    print("Warning: astroquery is not available. Gaia-based center refinement will be disabled.")
    _ASTROQUERY_AVAILABLE = False


def get_alma_beam(sigma_maj, sigma_min, bpa_rad, size=15):
    x = np.arange(-size, size + 1)
    X, Y = np.meshgrid(x, x)
    Xrot = X * np.cos(bpa_rad) + Y * np.sin(bpa_rad)
    Yrot = -X * np.sin(bpa_rad) + Y * np.cos(bpa_rad)
    kernel = np.exp(-(Xrot**2 / (2 * sigma_maj**2) + Yrot**2 / (2 * sigma_min**2)))
    return kernel / kernel.sum()


def deconvolve_beams(bmaj_t, bmin_t, pa_t, bmaj_i, bmin_i, pa_i):
    bmaj_t = bmaj_t * (1.0 + 1e-10)
    bmin_t = bmin_t * (1.0 + 1e-10)
    fwhm2sig = 2.3548200450309493

    def to_cov(bmaj, bmin, pa):
        sig_maj = bmaj / fwhm2sig
        sig_min = bmin / fwhm2sig
        th = np.radians(90.0 - pa)
        c, s = np.cos(th), np.sin(th)
        R = np.array([[c, -s], [s, c]])
        S = np.array([[sig_maj**2, 0], [0, sig_min**2]])
        return R @ S @ R.T

    C_t = to_cov(bmaj_t, bmin_t, pa_t)
    C_i = to_cov(bmaj_i, bmin_i, pa_i)
    C_c = C_t - C_i

    vals, vecs = np.linalg.eigh(C_c)

    if np.any(vals < 0):
        return None, None, None

    sig_min, sig_maj = np.sqrt(vals[0]), np.sqrt(vals[1])
    bmaj_c = sig_maj * fwhm2sig
    bmin_c = sig_min * fwhm2sig

    dy = vecs[1, 1]
    dx = vecs[0, 1]
    phi_c = np.degrees(np.arctan2(dy, dx))
    pa_c = (90.0 - phi_c) % 180.0

    return bmaj_c, bmin_c, pa_c


def make_gaussian_kernel_casa(bmaj_c, bmin_c, pa_c, pixel_scale):
    sigma_maj = (bmaj_c / pixel_scale) / 2.35482
    sigma_min = (bmin_c / pixel_scale) / 2.35482

    size = int(np.ceil(sigma_maj * 5))
    if size % 2 == 0:
        size += 1

    x = np.arange(-size, size + 1)
    X, Y = np.meshgrid(x, x)

    th = np.radians(90.0 - pa_c)
    Xrot = X * np.cos(th) + Y * np.sin(th)
    Yrot = -X * np.sin(th) + Y * np.cos(th)

    kernel = np.exp(-(Xrot**2 / (2 * sigma_maj**2) + Yrot**2 / (2 * sigma_min**2)))
    return kernel / np.sum(kernel)




def find_center_robust(data, pixel_scale, header):
    cy_cen, cx_cen = data.shape[0] // 2, data.shape[1] // 2
    search_rad_pix = int(3.0 / pixel_scale)

    y_min = max(0, cy_cen - search_rad_pix)
    y_max = min(data.shape[0], cy_cen + search_rad_pix)
    x_min = max(0, cx_cen - search_rad_pix)
    x_max = min(data.shape[1], cx_cen + search_rad_pix)
    crop = data[y_min:y_max, x_min:x_max]

    bmaj_arcsec = header.get('BMAJ', 0) * 3600
    sigma_as    = max(bmaj_arcsec / 2.355, 0.08)
    sigma_pix   = sigma_as / pixel_scale
    smoothed    = gaussian_filter(crop, sigma=sigma_pix)

    peak = np.nanmax(smoothed)
    mask = smoothed > (peak * 0.20)

    labeled, num_features = label(mask)
    if num_features > 0:
        sizes = np.bincount(labeled.ravel())
        sizes[0] = 0
        main_comp = np.argmax(sizes)
        main_mask = (labeled == main_comp)
    else:
        main_mask = mask

    filled      = binary_fill_holes(main_mask)
    pixels_orig = np.sum(main_mask)
    pixels_fill = np.sum(filled)

    if pixels_orig > 0 and (pixels_fill > pixels_orig * 1.03):
        y_idx, x_idx = np.where(filled)
        cy_local = (np.min(y_idx) + np.max(y_idx)) / 2.0
        cx_local = (np.min(x_idx) + np.max(x_idx)) / 2.0
    else:
        if np.any(main_mask):
            cy_local, cx_local = center_of_mass(main_mask)
        else:
            cy_local, cx_local = np.unravel_index(np.argmax(smoothed), smoothed.shape)

    return float(cx_local + x_min), float(cy_local + y_min)


def auto_detect_parameters(data, header, pixel_scale, cx, cy):
    bmaj = header.get('BMAJ', 0) * 3600
    rmin = max(bmaj * 1.2, 0.15) if bmaj > 0 else 0.2

    y, x = np.indices(data.shape)
    r    = np.hypot(x - cx, y - cy) * pixel_scale

    bins      = np.arange(0, 10.0, pixel_scale)
    prof, _   = np.histogram(r, bins=bins, weights=data)
    counts, _ = np.histogram(r, bins=bins)
    prof_mean = prof / np.maximum(counts, 1)

    prof_smooth = gaussian_filter1d(prof_mean, sigma=2)

    edge = np.concatenate([data[:10, :].ravel(), data[-10:, :].ravel(),
                           data[:, :10].ravel(), data[:, -10:].ravel()])
    rms = np.nanstd(edge)
    if rms <= 0:
        rms = 1e-9

    snr_threshold = 3.0
    above_snr = prof_smooth > (snr_threshold * rms)

    max_gap_bins = int(0.3 / pixel_scale)
    rout_idx = 0
    gap_counter = 0

    for i in range(len(above_snr)):
        if above_snr[i]:
            rout_idx = i
            gap_counter = 0
        else:
            gap_counter += 1
            if gap_counter > max_gap_bins:
                break

    rout = bins[rout_idx] + (pixel_scale * 2.0)
    rout += 0.05
    rout = np.clip(rout, 0.15, 8.0)

    return float(rmin), float(rout), float(bmaj)



def extract_profile(data, header, incl, pa, pixel_scale, cx, cy, limit_arcsec):
    pa_rad, incl_rad = np.radians(pa), np.radians(incl)

    dim  = 1000
    X, Y = np.meshgrid(np.arange(dim) - dim / 2.0, np.arange(dim) - dim / 2.0)

    Xc   = X * np.cos(incl_rad)
    Xrot = np.cos(pa_rad) * Xc + np.sin(pa_rad) * Y
    Yrot = -np.sin(pa_rad) * Xc + np.cos(pa_rad) * Y

    coords = [Yrot + cy, -Xrot + cx]
    deproj = map_coordinates(data, coords, order=3, mode='constant', cval=0.0)

    max_radius_pix = int(dim / 2.0)
    R, TH = np.meshgrid(np.linspace(0, max_radius_pix, max_radius_pix), np.linspace(-180, 180, 361))
    polar_coords = [R * np.sin(np.radians(TH)) + dim / 2.0, R * np.cos(np.radians(TH)) + dim / 2.0]
    polar_full   = map_coordinates(np.fliplr(deproj), polar_coords, order=1, mode='constant', cval=0.0)

    polar_flipped = np.flipud(polar_full)
    prof_full     = np.nanmean(polar_flipped, axis=0)
    std_full      = np.nanstd(polar_flipped, axis=0)

    r_arcsec = np.linspace(0, max_radius_pix, max_radius_pix) * pixel_scale
    bmaj     = header.get('BMAJ', 0) * 3600
    if bmaj > 0:
        n_eff = np.maximum(1.0, 2 * np.pi * np.maximum(r_arcsec, pixel_scale) / bmaj)
    else:
        n_eff = np.ones_like(r_arcsec) * 361.0
    err_full = std_full / np.sqrt(n_eff)

    restfrq = header.get('RESTFRQ', 0)
    if restfrq == 0:
        if 'CTYPE3' in header and 'FREQ' in header['CTYPE3']:
            restfrq = header.get('CRVAL3', 230e9)
        elif 'CTYPE4' in header and 'FREQ' in header['CTYPE4']:
            restfrq = header.get('CRVAL4', 230e9)
        else:
            restfrq = 230e9

    bmaj = header.get('BMAJ', 0) * 3600
    bmin = header.get('BMIN', 0) * 3600

    if bmaj > 0 and bmin > 0:
        beam_sr = (np.pi * bmaj * bmin / (4 * np.log(2))) / 206265**2
        factor  = ((3e10)**2 * 1e-23) / (2 * 1.38e-16 * restfrq**2 * beam_sr * 1000.0)
        tb_prof = prof_full * factor
        tb_err  = err_full  * factor
    else:
        tb_prof = prof_full
        tb_err  = err_full

    limit_idx = min(np.searchsorted(r_arcsec, limit_arcsec), len(r_arcsec))
    return r_arcsec[:limit_idx], tb_prof[:limit_idx], tb_err[:limit_idx]


def save_debug_deproj_center(image, cx, cy, incl, pa, rout_arcsec, pixel_scale, out_png, title):
    dim = 500
    x = np.arange(dim) - dim / 2.0
    X, Y = np.meshgrid(x, x)

    Xc = X * np.cos(np.radians(incl))
    Xrot = np.cos(np.radians(pa)) * Xc + np.sin(np.radians(pa)) * Y
    Yrot = -np.sin(np.radians(pa)) * Xc + np.cos(np.radians(pa)) * Y

    crop_rad = int((rout_arcsec / pixel_scale) * 1.5) + 15
    crop_rad = min(crop_rad, image.shape[0]//2, image.shape[1]//2)

    scale = (crop_rad * 2) / dim
    coords = [Yrot * scale + cy, -Xrot * scale + cx]

    deproj = map_coordinates(image, coords, order=1, mode='constant', cval=0.0)

    fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
    vmin, vmax = np.percentile(deproj, [2, 99.5]) if deproj.size > 0 else (np.min(deproj), np.max(deproj))
    ax.imshow(deproj, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)

    center_x, center_y = (dim - 1) / 2.0, (dim - 1) / 2.0
    ax.scatter([center_x], [center_y], c='white', s=60, marker='x', linewidths=1.5)

    r_pix = (rout_arcsec / pixel_scale) / scale
    circ = plt.Circle((center_x, center_y), r_pix, fill=False, ec='cyan', lw=1.8, ls='--')
    ax.add_patch(circ)

    ax.set_title(title)
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(out_png, bbox_inches='tight')
    plt.close(fig)


def measure_rout_deproj(data, header, pixel_scale, cx, cy, incl, pa, rmin=0.0):
    SNR_THR  = 2.0
    gap_tol  = 0.50

    pa_rad   = np.radians(pa)
    incl_rad = np.radians(incl)
    cos_i    = max(np.cos(incl_rad), 0.05)

    bmaj_as = header.get('BMAJ', 0) * 3600.0

    ny, nx = data.shape
    r_max_pix = min(ny // 2, nx // 2, 800)

    y_idx = np.arange(-r_max_pix, r_max_pix + 1)
    x_idx = np.arange(-r_max_pix, r_max_pix + 1)
    Xf, Yf = np.meshgrid(x_idx, y_idx)

    R_maj   = -Xf * np.sin(pa_rad) + Yf * np.cos(pa_rad)
    R_min   =  Xf * np.cos(pa_rad) + Yf * np.sin(pa_rad)
    R_min_dep = R_min / cos_i

    R_pix_fits = np.sqrt(R_maj**2 + R_min_dep**2)
    R_arcsec   = R_pix_fits * pixel_scale

    samp_y = R_maj  * np.cos(pa_rad) + R_min * np.sin(pa_rad) + cy
    samp_x = -R_maj * np.sin(pa_rad) + R_min * np.cos(pa_rad) + cx
    deproj = map_coordinates(data, [samp_y, samp_x], order=1, mode='constant', cval=0.0)

    r_arr = R_arcsec.ravel()
    d_arr = deproj.ravel()

    r_max_as   = r_max_pix * pixel_scale
    bin_size   = pixel_scale
    bins       = np.arange(0, r_max_as + bin_size, bin_size)
    prof       = np.zeros(len(bins) - 1)

    for k in range(len(bins) - 1):
        m = (r_arr >= bins[k]) & (r_arr < bins[k + 1])
        if m.sum() > 3:
            prof[k] = np.nanmean(d_arr[m])

    r_centers = (bins[:-1] + bins[1:]) / 2.0

    r_85 = r_max_as * 0.85
    edge_mask = r_arr > r_85
    if edge_mask.sum() > 50:
        rms = max(float(np.nanstd(d_arr[edge_mask])), 1e-10)
    else:
        edge = np.concatenate([data[:8, :].ravel(), data[-8:, :].ravel(),
                               data[:, :8].ravel(), data[:, -8:].ravel()])
        rms = max(float(np.nanstd(edge)), 1e-10)

    prof_s = gaussian_filter1d(prof, sigma=2)

    gap_bins  = max(1, int(gap_tol / bin_size))
    rout_idx  = 0
    gap_count = 0

    for k, (r, v) in enumerate(zip(r_centers, prof_s)):
        if r < rmin:
            continue
        if v > SNR_THR * rms:
            rout_idx  = k
            gap_count = 0
        else:
            gap_count += 1
            if gap_count > gap_bins:
                break

    margin = max(bmaj_as * 1.0, pixel_scale * 3, 0.03)
    rout   = float(np.clip(r_centers[rout_idx] + margin, 0.10, 8.0))

    return rout



def refine_center_local(data, header, pixel_scale, cx_init, cy_init):
    bmaj_arcsec = header.get('BMAJ', 0) * 3600
    search_rad_arcsec = max(bmaj_arcsec * 0.6, 0.15) if bmaj_arcsec > 0 else 0.25
    search_rad_pix = max(int(np.ceil(search_rad_arcsec / pixel_scale)), 3)

    y_min = max(0, int(round(cy_init)) - search_rad_pix)
    y_max = min(data.shape[0], int(round(cy_init)) + search_rad_pix + 1)
    x_min = max(0, int(round(cx_init)) - search_rad_pix)
    x_max = min(data.shape[1], int(round(cx_init)) + search_rad_pix + 1)

    if y_max - y_min < 3 or x_max - x_min < 3:
        return cx_init, cy_init

    crop = data[y_min:y_max, x_min:x_max].copy()
    sigma_pix = max((bmaj_arcsec / 2.355) / pixel_scale, 1.0) if bmaj_arcsec > 0 else 1.5
    smoothed = gaussian_filter(crop, sigma=sigma_pix)

    peak = np.nanmax(smoothed)
    if peak <= 0:
        return cx_init, cy_init

    mask = smoothed > (peak * 0.25)
    if not np.any(mask):
        return cx_init, cy_init

    cy_local, cx_local = center_of_mass(smoothed * mask)

    cx_ref = cx_init - x_min
    cy_ref = cy_init - y_min
    if abs(cx_local - cx_ref) > search_rad_pix or abs(cy_local - cy_ref) > search_rad_pix:
        return cx_init, cy_init

    return float(cx_local + x_min), float(cy_local + y_min)


def deg_to_sex(deg):
    sign = '+' if deg >= 0 else '-'
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60.0) * 3600.0
    return f"{sign}{d:03d}:{m:02d}:{s:06.3f}"


def pixel_to_icrs(header, cx, cy):
    wcs = WCS(header).celestial
    coord = pixel_to_skycoord(cx, cy, wcs, origin=0)
    icrs = coord.icrs
    return float(icrs.ra.deg), float(icrs.dec.deg)


def icrs_to_pixel(header, ra_deg, dec_deg):
    wcs = WCS(header).celestial
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame='icrs')
    x, y = skycoord_to_pixel(coord, wcs, origin=0)
    return float(x), float(y)


def get_obs_epoch(header):
    date_obs = header.get('DATE-OBS', None)
    if date_obs:
        try:
            return Time(str(date_obs).strip(), format='isot', scale='utc')
        except Exception:
            try:
                return Time(str(date_obs).strip(), scale='utc')
            except Exception:
                pass
    mjd_obs = header.get('MJD-OBS', None)
    if mjd_obs is not None:
        try:
            return Time(float(mjd_obs), format='mjd', scale='utc')
        except Exception:
            pass
    return None


def query_gaia_proper_motion(ra_deg, dec_deg, search_radius_arcsec=3.0):
    if not _ASTROQUERY_AVAILABLE:
        return None, None, None
    try:
        _GaiaCatalog.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
        _GaiaCatalog.ROW_LIMIT = 20
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame='icrs')
        radius = u.Quantity(search_radius_arcsec, u.arcsec)
        job = _GaiaCatalog.cone_search_async(coord, radius=radius, verbose=False)
        r = job.get_results()
        if len(r) == 0:
            return None, None, None
        gaia_coords = SkyCoord(
            ra=np.array(r['ra'],  dtype=float) * u.deg,
            dec=np.array(r['dec'], dtype=float) * u.deg,
            frame='icrs'
        )
        seps = coord.separation(gaia_coords).arcsec
        order = np.argsort(seps)
        for idx in order:
            row = r[idx]
            try:
                pmra_raw  = row['pmra']
                pmdec_raw = row['pmdec']
                if np.ma.is_masked(pmra_raw) or np.ma.is_masked(pmdec_raw):
                    continue
                pmra_val  = float(pmra_raw)
                pmdec_val = float(pmdec_raw)
                if not (np.isfinite(pmra_val) and np.isfinite(pmdec_val)):
                    continue
                return pmra_val, pmdec_val, float(seps[idx])
            except Exception:
                continue
        return None, None, None
    except Exception:
        return None, None, None


def apply_proper_motion_correction(ra_deg, dec_deg, pmra_masyr, pmdec_masyr, dt_yr):
    cos_dec   = np.cos(np.radians(dec_deg))
    delta_ra  = (pmra_masyr  * dt_yr) / (cos_dec * 3.6e6)
    delta_dec = (pmdec_masyr * dt_yr) / 3.6e6
    return float(ra_deg + delta_ra), float(dec_deg + delta_dec)
