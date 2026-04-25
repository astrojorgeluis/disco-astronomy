import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter
from scipy.optimize import minimize, differential_evolution
from disco.core.cnn_inference import predict_with_cnn

def geometric_loss(params, image, base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, dim=150, order=1):
    incl, pa, dcx, dcy = params

    local_cx = base_cx + dcx
    local_cy = base_cy + dcy

    x    = np.arange(dim) - dim / 2
    X, Y = np.meshgrid(x, x)

    Xc   = X * np.cos(np.radians(incl))
    Xrot = np.cos(np.radians(pa)) * Xc + np.sin(np.radians(pa)) * Y
    Yrot = -np.sin(np.radians(pa)) * Xc + np.cos(np.radians(pa)) * Y

    scale  = (crop_rad * 2) / dim
    coords = [Yrot * scale + local_cy, -Xrot * scale + local_cx]

    out_of_bounds = (
        (coords[0] < 0) | (coords[0] >= image.shape[0]) |
        (coords[1] < 0) | (coords[1] >= image.shape[1])
    )
    if np.sum(out_of_bounds) > 0.1 * (dim * dim):
        return 1e12

    deproj  = map_coordinates(image, coords, order=order, mode='constant', cval=0.0)
    r_steps = int(dim / 2)
    R, TH   = np.meshgrid(np.linspace(0, dim / 2, r_steps), np.linspace(-np.pi, np.pi, 180))
    polar   = map_coordinates(deproj, [R * np.sin(TH) + dim / 2, R * np.cos(TH) + dim / 2],
                              order=1, mode='constant', cval=0.0)

    scale_polar = r_steps / crop_rad
    idx_min     = max(0, int(rmin_pix * scale_polar))
    idx_max     = min(r_steps, int(rmax_pix * scale_polar))
    if idx_max <= idx_min + 2:
        idx_min, idx_max = 0, r_steps

    polar_crop = np.clip(polar[:, idx_min:idx_max], 0, None)
    profile = np.mean(polar_crop, axis=0)
    if np.max(profile) < 1e-8:
        return 1e12

    norm_factor = profile + (np.max(profile) * 0.01)
    diff = (polar_crop - np.tile(profile, (180, 1))) / np.tile(norm_factor, (180, 1))

    if np.max(profile) > 0:
        norm_prof = profile / np.max(profile)
        mask = norm_prof > 0.03
        rad = np.linspace(0.25, 1.0, len(profile))
        r_weights = np.sqrt(norm_prof) * mask * rad
    else:
        r_weights = np.ones_like(profile)

    delta = 0.5
    huber = np.where(np.abs(diff) <= delta,
                     0.5 * diff**2,
                     delta * (np.abs(diff) - 0.5 * delta))

    return np.sum(huber * r_weights)


def auto_tune_geometry_hybrid(data, header, pixel_scale, cx, cy, model, search_rad, rmin):
    cnn_incl, cnn_pa = predict_with_cnn(data, header, pixel_scale, cx, cy, search_rad, model)

    pad         = 500
    d_pad       = np.pad(data, pad, mode='constant', constant_values=0)
    real_cy_int = int(cy) + pad
    real_cx_int = int(cx) + pad
    offset_y    = (cy + pad) - real_cy_int
    offset_x    = (cx + pad) - real_cx_int
    search_rad_pix = int(search_rad / pixel_scale)
    crop_rad       = int(search_rad_pix * 1.5) + 10

    dc = d_pad[real_cy_int - crop_rad : real_cy_int + crop_rad,
               real_cx_int - crop_rad : real_cx_int + crop_rad]

    base_cy = crop_rad + offset_y
    base_cx = crop_rad + offset_x

    rmin_pix  = rmin / pixel_scale
    rmax_pix  = search_rad / pixel_scale

    bmaj_pix = (header.get('BMAJ', 0) * 3600) / pixel_scale
    sigma_smooth = max(bmaj_pix * 0.4, 1.0)
    dc_smooth = gaussian_filter(dc, sigma=sigma_smooth)

    largs_coarse = (dc_smooth, base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, 100, 1)
    largs_fine   = (dc,       base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, 400, 3)

    if cnn_incl < 35.0:
        incl_margin = 15.0
        pa_margin   = 25.0
    else:
        incl_margin = 20.0
        pa_margin   = 30.0

    center_lim_1 = 1.5
    bounds_1 = [
        (max(5.0, cnn_incl - incl_margin), min(85.0, cnn_incl + incl_margin)),
        (cnn_pa - pa_margin, cnn_pa + pa_margin),
        (-center_lim_1, center_lim_1),
        (-center_lim_1, center_lim_1),
    ]

    res_global_1 = differential_evolution(
        geometric_loss, bounds=bounds_1, args=largs_coarse,
        maxiter=50, tol=0.02, seed=42, workers=1,
        mutation=(0.5, 1.0), recombination=0.7
    )

    res_final_1 = minimize(
        geometric_loss, x0=res_global_1.x, args=largs_fine,
        method='Nelder-Mead', bounds=bounds_1,
        options={'xatol': 0.05, 'fatol': 1e-5, 'maxiter': 320}
    )

    best_1 = res_final_1.x
    incl_1, pa_1, dcx_1, dcy_1 = float(best_1[0]), float(best_1[1]), float(best_1[2]), float(best_1[3])

    near_edge = (abs(dcx_1) > 0.8 * center_lim_1) or (abs(dcy_1) > 0.8 * center_lim_1)

    if near_edge:
        base_cx_2 = base_cx + dcx_1
        base_cy_2 = base_cy + dcy_1

        largs_coarse_2 = (dc_smooth, base_cx_2, base_cy_2, crop_rad, rmin_pix, rmax_pix, 100, 1)
        largs_fine_2   = (dc,       base_cx_2, base_cy_2, crop_rad, rmin_pix, rmax_pix, 400, 3)

        center_lim_2 = 0.6
        bounds_2 = [
            (max(5.0, cnn_incl - incl_margin), min(85.0, cnn_incl + incl_margin)),
            (cnn_pa - pa_margin, cnn_pa + pa_margin),
            (-center_lim_2, center_lim_2),
            (-center_lim_2, center_lim_2),
        ]

        x0_2 = np.array([incl_1, pa_1, 0.0, 0.0], dtype=float)

        res_global_2 = differential_evolution(
            geometric_loss, bounds=bounds_2, args=largs_coarse_2,
            maxiter=35, tol=0.02, seed=43, workers=1,
            mutation=(0.5, 1.0), recombination=0.7
        )

        x0_mix = 0.5 * x0_2 + 0.5 * res_global_2.x

        res_final_2 = minimize(
            geometric_loss, x0=x0_mix, args=largs_fine_2,
            method='Nelder-Mead', bounds=bounds_2,
            options={'xatol': 0.04, 'fatol': 1e-5, 'maxiter': 260}
        )

        incl_f, pa_f, dcx_2, dcy_2 = res_final_2.x
        best_incl = float(np.clip(incl_f, 0.0, 85.0))
        best_pa   = float(pa_f % 180.0)
        best_dcx = float(dcx_1 + dcx_2)
        best_dcy = float(dcy_1 + dcy_2)
    else:
        best_incl = float(np.clip(incl_1, 0.0, 85.0))
        best_pa   = float(pa_1 % 180.0)
        best_dcx  = float(dcx_1)
        best_dcy  = float(dcy_1)

    if abs(best_incl - cnn_incl) > 20.0:
        best_incl = float(cnn_incl)
        best_pa   = float(cnn_pa)
        best_dcx, best_dcy = 0.0, 0.0

    if best_incl < 5.0:
        best_pa = float(cnn_pa)

    return best_incl, best_pa, float(cnn_incl), float(cnn_pa), best_dcx, best_dcy


def estimate_geometry_errors(data, pixel_scale, cx, cy, incl, pa, rmin, rmax):
    pad         = 500
    d_pad       = np.pad(data, pad, mode='constant', constant_values=0)
    real_cy_int = int(cy) + pad
    real_cx_int = int(cx) + pad
    offset_y    = (cy + pad) - real_cy_int
    offset_x    = (cx + pad) - real_cx_int
    crop_rad    = int(rmax / pixel_scale * 1.5) + 10

    dc = d_pad[
        real_cy_int - crop_rad : real_cy_int + crop_rad,
        real_cx_int - crop_rad : real_cx_int + crop_rad
    ]

    base_cx = crop_rad + offset_x
    base_cy = crop_rad + offset_y
    rmin_pix = rmin / pixel_scale
    rmax_pix = rmax / pixel_scale

    largs = (dc, base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, 320, 3)

    bnds = [(max(0.0, incl - 30.0), min(85.0, incl + 30.0)), (None, None), (0.0, 0.0), (0.0, 0.0)]

    res = minimize(
        geometric_loss,
        x0=[incl, pa, 0.0, 0.0],
        args=largs,
        method='Nelder-Mead',
        bounds=bnds,
        options={'xatol': 0.05, 'fatol': 1e-5, 'maxiter': 600}
    )

    opt_incl = float(np.clip(res.x[0], 0.0, 85.0))
    opt_pa   = float(res.x[1] % 180.0)

    loss_min = geometric_loss([opt_incl, opt_pa, 0.0, 0.0], *largs)
    if not np.isfinite(loss_min) or loss_min >= 1e11:
        return 2.0, 2.0

    deltas = np.arange(0.25, 12.0, 0.25)

    def _parabolic_error(center, fixed, scan_incl):
        pts = np.concatenate([-deltas[::-1], [0.0], deltas])
        losses = np.array([
            geometric_loss(
                [np.clip(center + d, 0, 85), fixed, 0.0, 0.0] if scan_incl
                else [fixed, (center + d) % 180, 0.0, 0.0],
                *largs
            ) for d in pts
        ])
        valid = np.isfinite(losses) & (losses < loss_min * 2.5)
        if valid.sum() < 5:
            return 5.0
        coeffs = np.polyfit(pts[valid], losses[valid], 2)
        a = coeffs[0]
        if a <= 0:
            return 5.0
        return float(np.clip(np.sqrt(loss_min * 5e-3 / a), 0.3, 10.0))

    return _parabolic_error(opt_incl, opt_pa, True), _parabolic_error(opt_pa, opt_incl, False)


def refine_center_geometry(data, header, pixel_scale, cx, cy, incl, pa, rmin, rmax):
    pad = 300
    d_pad = np.pad(data, pad, mode='constant', constant_values=0)
    real_cy_int = int(cy) + pad
    real_cx_int = int(cx) + pad
    offset_y = (cy + pad) - real_cy_int
    offset_x = (cx + pad) - real_cx_int

    crop_rad = int(rmax / pixel_scale * 1.5) + 10
    crop_rad = max(crop_rad, 20)

    if (real_cy_int - crop_rad < 0 or real_cy_int + crop_rad > d_pad.shape[0] or
            real_cx_int - crop_rad < 0 or real_cx_int + crop_rad > d_pad.shape[1]):
        return cx, cy

    dc = d_pad[real_cy_int - crop_rad:real_cy_int + crop_rad,
               real_cx_int - crop_rad:real_cx_int + crop_rad]

    if dc.shape[0] < 10 or dc.shape[1] < 10:
        return cx, cy

    base_cx = float(crop_rad + offset_x)
    base_cy = float(crop_rad + offset_y)
    rmin_pix = max(rmin, 0.0) / pixel_scale
    rmax_pix = rmax / pixel_scale

    bmaj_pix = max((header.get('BMAJ', 0) * 3600) / pixel_scale, 2.0)
    center_lim = max(bmaj_pix * 2.0, 0.15 / pixel_scale)

    largs = (dc, base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, 120, 1)

    loss_ref = geometric_loss([incl, pa, 0.0, 0.0], *largs)
    if not np.isfinite(loss_ref) or loss_ref >= 1e11:
        return cx, cy

    res = minimize(
        lambda p: geometric_loss([incl, pa, p[0], p[1]], *largs),
        x0=[0.0, 0.0],
        method='Nelder-Mead',
        options={'xatol': 0.1, 'fatol': 1e-4, 'maxiter': 300}
    )

    dcx, dcy = float(res.x[0]), float(res.x[1])

    if not np.isfinite(dcx) or not np.isfinite(dcy):
        return cx, cy
    if abs(dcx) > center_lim or abs(dcy) > center_lim:
        return cx, cy
    if res.fun >= loss_ref:
        return cx, cy

    return float(cx + dcx), float(cy + dcy)