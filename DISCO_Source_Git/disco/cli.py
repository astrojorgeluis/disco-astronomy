import sys
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import re
import warnings
import argparse
import csv
import numpy as np
import torch   
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs import FITSFixedWarning
from astropy.wcs.utils import pixel_to_skycoord, skycoord_to_pixel
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from disco.core.cnn_inference import DiscoNet, predict_with_cnn
from disco.core.optimization import (geometric_loss, auto_tune_geometry_hybrid, estimate_geometry_errors, refine_center_geometry)
from disco.core.fits_utils import (
    get_alma_beam, deconvolve_beams, make_gaussian_kernel_casa,
    find_center_robust, auto_detect_parameters, extract_profile,
    save_debug_deproj_center, measure_rout_deproj, refine_center_local,
    deg_to_sex, pixel_to_icrs, icrs_to_pixel, get_obs_epoch,
    query_gaia_proper_motion, apply_proper_motion_correction,
    _ASTROQUERY_AVAILABLE
)
warnings.filterwarnings("ignore", category=FITSFixedWarning)
from scipy.ndimage import (
    map_coordinates, gaussian_filter, gaussian_filter1d,
    zoom, center_of_mass, binary_fill_holes, label
)
from scipy.optimize import minimize, differential_evolution
from scipy.signal import fftconvolve
from tqdm import tqdm



def discover_groups(base_dir):
    groups = []

    for root, _, files in os.walk(base_dir):
        fits_files = [os.path.join(root, f) for f in files if f.lower().endswith('.fits')]

        if not fits_files:
            continue

        parent_name = os.path.basename(os.path.dirname(root))

        grouped = {}
        for fpath in fits_files:
            stem = os.path.splitext(os.path.basename(fpath))[0]
            parts = re.split(r'_?[Bb]and_?\d+', stem, maxsplit=1)
            prefix = parts[0].rstrip('_') if parts[0] else stem
            grouped.setdefault(prefix, []).append(fpath)

        for prefix, group_files in grouped.items():
            group_name = f"{parent_name}_{prefix}" if parent_name else prefix
            output_dir = os.path.join(root, prefix)
            groups.append({
                "name": group_name,
                "files": sorted(group_files),
                "output_dir": output_dir,
            })

    return groups

def run_pipeline(files_to_process, group_name, output_dir, args, cnn_model):
    tqdm.write(f"\n{'='*60}")
    tqdm.write(f"[START] Group: {group_name}  ({len(files_to_process)} file(s))")
    tqdm.write(f"{'='*60}")

    pbar = tqdm(total=5, desc=f"Pipeline [{group_name}]", leave=False, dynamic_ncols=True)

    pbar.set_postfix_str("Phase 1/5: Reading FITS")
    temp_data     = []
    max_auto_rout = 0.0

    for filepath in files_to_process:
        filename = os.path.basename(filepath)
        try:
            with fits.open(filepath, memmap=True) as hdul:
                data   = np.nan_to_num(np.squeeze(hdul[0].data).astype(np.float32))
                header = hdul[0].header

                bunit = str(header.get('BUNIT', '')).strip().upper()
                if bunit == 'JY/BEAM':
                    data *= 1000
                    header['BUNIT'] = 'mJy/beam'
                elif bunit == '' and np.max(data) < 5.0:
                    data *= 1000

                pixel_scale = abs(header.get('CDELT2', 0.03)) * 3600
                cx, cy      = find_center_robust(data, pixel_scale, header)

                auto_rmin, auto_rout, bmaj = auto_detect_parameters(data, header, pixel_scale, cx, cy)
                bmin = header.get('BMIN', 0) * 3600
                max_auto_rout = max(max_auto_rout, auto_rout)

                temp_data.append({
                    "filename": filename, "data": data, "header": header,
                    "pixel_scale": pixel_scale, "cx": cx, "cy": cy,
                    "auto_rmin": auto_rmin, "auto_rout": auto_rout,
                    "bmaj": bmaj, "bmin": bmin,
                    "obs_epoch": get_obs_epoch(header)
                })
        except Exception as e:
            tqdm.write(f"[ERROR] Failed to read {filename}: {str(e)}")

    if not temp_data:
        tqdm.write(f"[WARN] No readable FITS files for group '{group_name}'. Skipping.")
        pbar.close()
        return

    best_score   = -1
    best_img_idx = 0

    for i, item in enumerate(temp_data):
        d    = item["data"]
        edge = np.concatenate([d[:10, :].ravel(), d[-10:, :].ravel(),
                               d[:, :10].ravel(), d[:, -10:].ravel()])
        rms  = np.nanstd(edge)
        snr  = np.nanmax(d) / rms if rms > 0 else 0
        item["snr"] = snr

        bmaj_as  = item["bmaj"]
        bmin_as  = item["bmin"] if item["bmin"] > 0 else bmaj_as
        beam_area = bmaj_as * bmin_as
        score = snr / (beam_area ** 1.5) if beam_area > 0 and snr > 3.0 else 0.0

        if score > best_score:
            best_score   = score
            best_img_idx = i

    best_item    = temp_data[best_img_idx]
    geom_rout    = max_auto_rout
    unified_rout = args.rout if args.rout is not None else max_auto_rout
    final_rmin   = args.rmin if args.rmin > 0.0 else best_item["auto_rmin"]

    ref_ra, ref_dec = None, None
    pmra_gaia, pmdec_gaia, gaia_sep = None, None, None
    ra_vals, dec_vals, snr_weights = [], [], []
    for item in temp_data:
        try:
            ra_i, dec_i = pixel_to_icrs(item["header"], item["cx"], item["cy"])
            ra_vals.append(ra_i)
            dec_vals.append(dec_i)
            snr_weights.append(max(item.get("snr", 1.0), 0.01))
        except Exception:
            pass

    if ra_vals:
        w = np.array(snr_weights, dtype=float)
        w /= w.sum()
        ra_rad = np.radians(ra_vals)
        ref_ra  = float(np.degrees(np.arctan2(
            np.sum(np.sin(ra_rad) * w),
            np.sum(np.cos(ra_rad) * w)
        )) % 360.0)
        ref_dec = float(np.sum(np.array(dec_vals) * w))

        pmra_gaia, pmdec_gaia, gaia_sep = query_gaia_proper_motion(ref_ra, ref_dec)

        best_epoch = best_item.get("obs_epoch", None)
        for item in temp_data:
            if item is best_item:
                continue
            try:
                apply_ra, apply_dec = ref_ra, ref_dec
                if pmra_gaia is not None and best_epoch is not None:
                    item_epoch = item.get("obs_epoch", None)
                    if item_epoch is not None:
                        dt_yr = item_epoch.jyear - best_epoch.jyear
                        apply_ra, apply_dec = apply_proper_motion_correction(
                            ref_ra, ref_dec, pmra_gaia, pmdec_gaia, dt_yr
                        )
                px, py = icrs_to_pixel(item["header"], apply_ra, apply_dec)
                #px, py = refine_center_local(item["data"], item["header"], item["pixel_scale"], px, py)
                item["cx"], item["cy"] = px, py
            except Exception:
                pass

    pbar.update(1)

    pbar.set_postfix_str("Phase 2/5: Optimizing Geometry")
    cnn_i, cnn_p = None, None
    if args.incl is not None and args.pa is not None:
        master_incl, master_pa, err_incl, err_pa = args.incl, args.pa, 0.0, 0.0
    else:
        if cnn_model:
            cnn_context_rad = geom_rout * 1.1
            geom_rmin = max(final_rmin, 1.5 * best_item["bmaj"])

            incl, pa, cnn_i, cnn_p, dx, dy = auto_tune_geometry_hybrid(
                best_item["data"], best_item["header"], best_item["pixel_scale"],
                best_item["cx"], best_item["cy"],
                cnn_model, cnn_context_rad, geom_rmin
            )

            try:
                new_cx = best_item["cx"] + dx
                new_cy = best_item["cy"] + dy
                ref_ra, ref_dec = pixel_to_icrs(best_item["header"], new_cx, new_cy)
                best_item["cx"], best_item["cy"] = new_cx, new_cy
                best_epoch = best_item.get("obs_epoch", None)
                for item in temp_data:
                    if item is best_item:
                        continue
                    try:
                        apply_ra, apply_dec = ref_ra, ref_dec
                        if pmra_gaia is not None and best_epoch is not None:
                            item_epoch = item.get("obs_epoch", None)
                            if item_epoch is not None:
                                dt_yr = item_epoch.jyear - best_epoch.jyear
                                apply_ra, apply_dec = apply_proper_motion_correction(
                                    ref_ra, ref_dec, pmra_gaia, pmdec_gaia, dt_yr
                                )
                        px, py = icrs_to_pixel(item["header"], apply_ra, apply_dec)
                        #px, py = refine_center_geometry(
                        #    item["data"], item["header"], item["pixel_scale"],
                        #    px, py, incl, pa, final_rmin, geom_rout
                        #)
                        item["cx"], item["cy"] = px, py
                    except Exception:
                        item["cx"] += dx
                        item["cy"] += dy
            except Exception:
                for item in temp_data:
                    item["cx"] += dx
                    item["cy"] += dy
        else:
            pad      = 500
            d_pad    = np.pad(best_item["data"], pad, mode='constant', constant_values=0)
            crop_rad = int((geom_rout / best_item["pixel_scale"]) * 1.5) + 10
            dc = d_pad[int(best_item["cy"]) + pad - crop_rad : int(best_item["cy"]) + pad + crop_rad,
                       int(best_item["cx"]) + pad - crop_rad : int(best_item["cx"]) + pad + crop_rad]
            res = minimize(
                geometric_loss,
                x0=[30.0, 45.0, 0.0, 0.0],
                args=(dc, crop_rad, crop_rad, crop_rad,
                    final_rmin / best_item["pixel_scale"],
                    geom_rout / best_item["pixel_scale"],
                    150, 1),
                method='Nelder-Mead',
                options={'xatol': 0.05, 'fatol': 1e-5}
            )
            incl, pa = res.x[0], res.x[1] % 180

        master_incl, master_pa = float(incl), float(pa)
    pbar.update(1)

    pbar.set_postfix_str("Phase 3/5: Estimating Errors")
    if args.incl is None or args.pa is None:
        err_incl, err_pa = estimate_geometry_errors(
            best_item["data"], best_item["pixel_scale"],
            best_item["cx"], best_item["cy"],
            master_incl, master_pa,
            final_rmin, geom_rout
        )

    if args.rout is None:
        rout_deproj = measure_rout_deproj(
            best_item["data"], best_item["header"],
            best_item["pixel_scale"], best_item["cx"], best_item["cy"],
            master_incl, master_pa, rmin=final_rmin
        )

        ratio = max_auto_rout / (rout_deproj + 1e-6)
        incl_factor = np.clip((master_incl - 60.0) / 30.0, 0.0, 1.0)
        w_deproj = 0.60 - 0.25 * incl_factor
        w_heur   = 1.0 - w_deproj

        if ratio > 1.5 and master_incl < 55.0:
            unified_rout = rout_deproj * 1.15
            fusion_mode  = "deproj×1.15"
        elif ratio > 1.5 and master_incl >= 55.0:
            unified_rout = 0.50 * rout_deproj * 1.15 + 0.50 * max_auto_rout
            fusion_mode  = "mean (high-incl)"
        elif ratio < 0.8:
            unified_rout = max_auto_rout
            fusion_mode  = "heuristic"
        else:
            unified_rout = w_deproj * rout_deproj + w_heur * max_auto_rout
            fusion_mode  = "weighted mean"

        bmaj_ref = best_item["bmaj"]
        unified_rout = max(unified_rout, bmaj_ref * 1.5, 0.10)

    tqdm.write(
        f"[RESULT] Reference : {best_item['filename']}"
        f"  |  SNR: {best_item['snr']:.1f}"
        f"  |  Beam: {best_item['bmaj']:.3f}\""
    )
    tqdm.write(
        f"         Geometry  : i = {master_incl:.1f}° ± {err_incl:.1f}°"
        f"  |  PA = {master_pa:.1f}° ± {err_pa:.1f}°"
    )
    tqdm.write(
        f"         Extent    : Rout = {unified_rout:.3f}\"  |  Rmin = {final_rmin:.3f}\""
        + (f"  [{fusion_mode}]" if args.rout is None else "  [forced]")
    )
    if cnn_model and cnn_i is not None:
        tqdm.write(f"         CNN prior : i = {cnn_i:.1f}°  |  PA = {cnn_p:.1f}°")
    if ref_ra is not None:
        center_coord = SkyCoord(ra=ref_ra * u.deg, dec=ref_dec * u.deg, frame='icrs')
        tqdm.write(
            f"         Center    : RA = {center_coord.ra.to_string(unit=u.hour, sep=':', precision=3)}"
            f"  |  Dec = {center_coord.dec.to_string(sep=':', precision=2)}  (ICRS)"
        )
    if pmra_gaia is not None:
        tqdm.write(
            f"         Gaia PM   : pmRA = {pmra_gaia:.3f} mas/yr"
            f"  |  pmDec = {pmdec_gaia:.3f} mas/yr"
            f"  |  match = {gaia_sep:.2f}\""
        )
    elif _ASTROQUERY_AVAILABLE and ref_ra is not None:
        tqdm.write(f"         Gaia PM   : no match within 3\" — PM correction skipped")

    pbar.update(1)

    pbar.set_postfix_str("Phase 4/5: Extracting Profiles")

    if args.debug == 'on':
        debug_dir = os.path.join(output_dir, "debug_pipeline")
        os.makedirs(debug_dir, exist_ok=True)
        out_png = os.path.join(debug_dir, f"{group_name}_debug_center_rout.png")
        save_debug_deproj_center(
            best_item["data"], best_item["cx"], best_item["cy"],
            master_incl, master_pa, unified_rout, best_item["pixel_scale"],
            out_png, title=f"{group_name} | i={master_incl:.1f} PA={master_pa:.1f}"
        )

    if args.homobeam == 'on':
        try:
            if args.beam is not None:
                t_bmaj, t_bmin, t_bpa = args.beam, args.beam, 0.0
            else:
                max_bmaj = max(float(img["header"].get('BMAJ', 0)) for img in temp_data) * 3600.0
                t_bmaj, t_bmin, t_bpa = max_bmaj * 1.01, max_bmaj * 1.01, 0.0
        except Exception:
            t_bmaj, t_bmin, t_bpa = 0.0, 0.0, 0.0

        if t_bmaj > 0:
            for img in temp_data:
                i_bmaj = img["header"].get('BMAJ', 0) * 3600.0
                i_bmin = img["header"].get('BMIN', 0) * 3600.0
                i_bpa  = img["header"].get('BPA', 0)

                if i_bmaj == 0 or i_bmin == 0 or (np.isclose(i_bmaj, t_bmaj) and np.isclose(i_bmin, t_bmin)):
                    continue

                bmaj_c, bmin_c, pa_c = deconvolve_beams(t_bmaj, t_bmin, t_bpa, i_bmaj, i_bmin, i_bpa)

                if bmaj_c is not None:
                    kernel = make_gaussian_kernel_casa(bmaj_c, bmin_c, pa_c, img["pixel_scale"])
                    img["data"] = fftconvolve(img["data"], kernel, mode='same')
                    scale_factor = (t_bmaj * t_bmin) / (i_bmaj * i_bmin)
                    img["data"] *= scale_factor

                    img["header"]['BMAJ'] = t_bmaj / 3600.0
                    img["header"]['BMIN'] = t_bmin / 3600.0
                    img["header"]['BPA']  = t_bpa
                    img["bmaj"] = t_bmaj
                    img["bmin"] = t_bmin

    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    ax.set_facecolor('white')
    limit_plot = unified_rout

    def band_snr(item):
        d    = item["data"]
        edge = np.concatenate([d[:10, :].ravel(), d[-10:, :].ravel(),
                               d[:, :10].ravel(), d[:, -10:].ravel()])
        rms  = np.nanstd(edge)
        return np.nanmax(d) / rms if rms > 0 else 0.0

    snr_map  = {img["filename"]: band_snr(img) for img in temp_data}
    csv_data = {}
    max_pts  = 0

    for img in sorted(temp_data, key=lambda x: snr_map[x["filename"]], reverse=True):
        band_bmaj = img["bmaj"]

        lbl = img["filename"]
        m   = re.search(r'(Band_\d+)', lbl, re.IGNORECASE)
        if m:
            lbl = m.group(1).replace('_', ' ')

        r_arcsec, tb_prof, tb_err = extract_profile(
            img["data"], img["header"], master_incl, master_pa,
            img["pixel_scale"], img["cx"], img["cy"], limit_arcsec=limit_plot
        )

        limit_idx = min(np.searchsorted(r_arcsec, limit_plot), len(r_arcsec))
        r_plot    = r_arcsec[:limit_idx]
        y_plot    = tb_prof[:limit_idx]
        err_plot  = tb_err[:limit_idx]

        max_val = np.nanmax(y_plot)
        y_norm  = y_plot / max_val if max_val > 0 else y_plot
        e_norm  = err_plot / max_val if max_val > 0 else err_plot

        mx2 = np.nanmax(y_norm)
        if mx2 > 0:
            y_norm = y_norm / mx2
            e_norm = e_norm / mx2

        y_norm_clip = np.clip(y_norm, -0.05, 1.05)
        ax.plot(r_plot, y_norm_clip, lw=2.5, label=lbl)

        lbl_clean = lbl.replace(' ', '_')
        csv_data[lbl_clean] = {
            'filename': img["filename"],
            'snr': snr_map[img["filename"]],
            'cx': img["cx"],
            'cy': img["cy"],
            'bmaj': img["bmaj"],
            'bmin': img.get("bmin", 0.0),
            'max_flux': max_val,
            'r': r_plot,
            'i_raw': y_plot,
            'e_raw': err_plot,
            'i_norm': y_norm_clip,
            'e_norm': e_norm
        }
        max_pts = max(max_pts, len(r_plot))
    pbar.update(1)

    pbar.set_postfix_str("Phase 5/5: Saving Results")
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlim(0, limit_plot)
    ax.set_xlabel("r / arcsec", fontsize=12)
    ax.set_ylabel("Normalized Intensity", fontsize=12)
    ax.tick_params(direction='in', labelsize=10)
    ax.grid(True, which='both', color='gray', alpha=0.3, linestyle='--')
    ax.set_title(
        f"Radial Profiles — {group_name}\n"
        f"i={master_incl:.1f}°±{err_incl:.1f}°   PA={master_pa:.1f}°±{err_pa:.1f}°",
        fontweight='bold', fontsize=13
    )
    ax.legend(fontsize=10)

    os.makedirs(output_dir, exist_ok=True)
    output_png = os.path.join(output_dir, f"RP_{group_name}.PNG")
    plt.savefig(output_png, format='png', bbox_inches='tight', facecolor='white')
    plt.close(fig)

    if args.csv == 'on':
        try:
            ellipse_smaj = unified_rout
            ellipse_smin = unified_rout * np.cos(np.radians(master_incl))

            with open(os.path.join(output_dir, f"RP_{group_name}_global.csv"), mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["parameter", "value", "uncertainty"])
                writer.writerow(["Rout_arcsec",         f"{unified_rout:.4f}",  ""])
                writer.writerow(["Rmin_arcsec",         f"{final_rmin:.4f}",   ""])
                writer.writerow(["Inclination_deg",     f"{master_incl:.3f}",  f"{err_incl:.3f}"])
                writer.writerow(["PA_deg",              f"{master_pa:.3f}",    f"{err_pa:.3f}"])
                writer.writerow(["Ellipse_smaj_arcsec", f"{ellipse_smaj:.4f}", ""])
                writer.writerow(["Ellipse_smin_arcsec", f"{ellipse_smin:.4f}", ""])
                if ref_ra is not None:
                    writer.writerow(["Center_RA_deg",  f"{ref_ra:.8f}",  ""])
                    writer.writerow(["Center_Dec_deg", f"{ref_dec:.8f}", ""])
                if pmra_gaia is not None:
                    writer.writerow(["Gaia_pmRA_masyr",   f"{pmra_gaia:.4f}",  ""])
                    writer.writerow(["Gaia_pmDec_masyr",  f"{pmdec_gaia:.4f}", ""])
                    writer.writerow(["Gaia_match_arcsec", f"{gaia_sep:.4f}",   ""])

            with open(os.path.join(output_dir, f"RP_{group_name}_bands.csv"), mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["filename", "snr", "cx_pix", "cy_pix", "bmaj_arcsec", "bmin_arcsec", "peak_flux_mJyBeam"])
                for d in csv_data.values():
                    writer.writerow([
                        d['filename'],
                        f"{d['snr']:.1f}",
                        f"{d['cx']:.2f}",
                        f"{d['cy']:.2f}",
                        f"{d['bmaj']:.4f}",
                        f"{d['bmin']:.4f}",
                        f"{d['max_flux']:.6e}"
                    ])

            with open(os.path.join(output_dir, f"RP_{group_name}_profile.csv"), mode='w', newline='') as f:
                writer = csv.writer(f)
                header_row = []
                for lbl_clean in csv_data.keys():
                    header_row.extend([
                        f"R_{lbl_clean}_arcsec",
                        f"Flux_{lbl_clean}_mJy",
                        f"FluxNorm_{lbl_clean}",
                        f"FluxNormErr_{lbl_clean}"
                    ])
                writer.writerow(header_row)
                for i in range(max_pts):
                    row = []
                    for lbl_clean in csv_data.keys():
                        d = csv_data[lbl_clean]
                        if i < len(d['r']):
                            row.extend([
                                f"{d['r'][i]:.6f}",
                                f"{d['i_raw'][i]:.6e}",
                                f"{d['i_norm'][i]:.6f}",
                                f"{d['e_norm'][i]:.6f}"
                            ])
                        else:
                            row.extend(["", "", "", ""])
                    writer.writerow(row)
        except Exception as e:
            tqdm.write(f"[ERROR] Failed to save CSV: {e}")

    pbar.update(1)
    pbar.close()


def main():
    parser = argparse.ArgumentParser(description="DISCO Automated Pipeline")
    parser.add_argument("identifier", nargs="*", help="Object prefix(es) or FITS file path(s)")
    parser.add_argument("--rout",      type=float, default=None,  help="Force Rout (arcsec)")
    parser.add_argument("--rmin",      type=float, default=0.0,   help="Force Rmin (arcsec)")
    parser.add_argument("--incl",      type=float, default=None,  help="Force inclination (deg)")
    parser.add_argument("--pa",        type=float, default=None,  help="Force PA (deg)")
    parser.add_argument("--beam",      type=float, default=None,  help="Force target beam resolution (arcsec)")
    parser.add_argument("--homobeam", type=str,   default="on",  choices=["on", "off"], help="Toggle beam homogenization")
    parser.add_argument("--csv",       type=str,   default="off", choices=["on", "off"], help="Export CSV data")
    parser.add_argument("--debug",     type=str,   default="off", choices=["on", "off"], help="Save debug deprojected image")
    args = parser.parse_args()

    cnn_model  = None
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(BASE_DIR, "models", "disco_model_stable.pth")

    if os.path.exists(model_path):
        try:
            ckpt = torch.load(model_path, map_location='cpu', weights_only=True)
            cnn_model = DiscoNet(n_out=5)
            state = ckpt["model_state"] if isinstance(ckpt, dict) else ckpt
            cnn_model.load_state_dict(state)
            cnn_model.eval()
            print("[INFO] CNN model loaded.")
        except Exception as e:
            print(f"[WARN] CNN model load failed: {e}. Falling back to analytical geometry.")
    else:
        print("[WARN] Model file not found. Falling back to analytical geometry.")

    base_dir   = os.getcwd()
    all_groups = discover_groups(base_dir)

    if not all_groups:
        print("[ERROR] No FITS files found in the current directory tree.")
        sys.exit(1)

    if args.identifier:
        groups    = []
        clean_ids = [ident.strip(',') for ident in args.identifier]

        for g in all_groups:
            path_parts = g['output_dir'].replace('\\', '/').split('/')
            if any(ident in path_parts or ident in g['output_dir'] for ident in clean_ids):
                groups.append(g)
            else:
                matched_files = [
                    f for f in g['files']
                    if any(ident in os.path.basename(f) for ident in clean_ids)
                ]
                if matched_files:
                    groups.append({
                        "name": g['name'],
                        "files": matched_files,
                        "output_dir": g['output_dir']
                    })

        if not groups:
            print(f"[ERROR] No FITS files match the provided identifiers: {clean_ids}")
            sys.exit(1)
    else:
        groups = all_groups

    print(f"[INFO] Found {len(groups)} group(s) to process.\n")

    for group in tqdm(groups, desc="Total Groups", unit="group", dynamic_ncols=True):
        try:
            run_pipeline(group["files"], group["name"], group["output_dir"], args, cnn_model)
        except Exception as e:
            tqdm.write(f"[ERROR] Processing failed for group '{group['name']}': {e}")

    print("\n[INFO] Pipeline execution completed.")


if __name__ == "__main__":
    main()