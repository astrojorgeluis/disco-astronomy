"""ALMA disk catalogue simulator (CASA simobserve / tclean / exportfits)."""

import argparse
import csv
import os
import shutil
import time
import zlib

import numpy as np
from astropy.io import fits
from scipy.ndimage import gaussian_filter

CATALOG_FILE = "catalogo_piloto.csv"
OUTPUT_DIR = "simulations"
IMG_SIZE = 1024
OFFSETS_CSV = "center_offsets.csv"
DEFAULT_ARRAY_LO = "alma.cycle9.5.cfg"
_BASE_SEED = 0

BANDS = {
    6: dict(freq_ghz=230.0, bw_ghz=7.5, pb_as=25.0, kappa=1.00),
    8: dict(freq_ghz=405.0, bw_ghz=7.5, pb_as=14.3, kappa=2.70),
}

ARRAYS = {
    "alma.cycle9.5.cfg": dict(beam_mas=130, cell_mas=22),
    "alma.cycle9.6.cfg": dict(beam_mas=80, cell_mas=13),
    "alma.cycle9.7.cfg": dict(beam_mas=50, cell_mas=8),
    "alma.cycle9.8.cfg": dict(beam_mas=28, cell_mas=5),
    "alma.cycle9.9.cfg": dict(beam_mas=18, cell_mas=3),
}


def generate_texture(shape, scale=35, amp=0.08, rng=None):
    rng = np.random if rng is None else rng
    noise = gaussian_filter(rng.normal(0, 1, shape), sigma=scale)
    noise /= np.max(np.abs(noise)) + 1e-10
    return 1.0 + noise * amp


def _morph_rng(obj_id, base_seed=0):
    """Stable per-object RNG so morphology does not depend on catalogue order."""
    h = zlib.adler32(str(obj_id).encode("utf-8")) & 0xFFFFFFFF
    return np.random.RandomState((int(base_seed) ^ h) & 0xFFFFFFFF)


def get_imaging_params(array_cfg, band):
    array = ARRAYS.get(array_cfg, ARRAYS["alma.cycle9.7.cfg"])
    band_params = BANDS[band]
    freq_scale = 230.0 / band_params["freq_ghz"]
    cell_mas = max(int(array["cell_mas"] * freq_scale), 2)
    beam_pix = max(int((array["beam_mas"] * freq_scale) / cell_mas), 4)
    pb_pix = int(band_params["pb_as"] * 1000.0 / cell_mas * 1.2)
    imsize = max(256, min(1024, int(2 ** np.ceil(np.log2(pb_pix)))))
    scales = sorted(set([
        0,
        max(1, beam_pix // 2),
        beam_pix,
        beam_pix * 2,
    ]))
    return dict(
        cell=f"{cell_mas}mas",
        imsize=imsize,
        scales=scales,
        cell_mas=cell_mas,
        cell_as=cell_mas / 1000.0,
        beam_pix=beam_pix,
        beam_as=(array["beam_mas"] * freq_scale) / 1000.0,
    )


def create_fits_model(
    out_path,
    inclination,
    pos_angle,
    r_out,
    r_min,
    total_flux,
    band=6,
    array_cfg="alma.cycle9.7.cfg",
    dx_arcsec=None,
    dy_arcsec=None,
    pre_smooth="light",
    rng=None,
):
    """Build a Jy/pixel sky model (optional center offsets in arcsec)."""
    rng = np.random if rng is None else rng
    band_params = BANDS[band]
    kappa = band_params["kappa"]
    img_params = get_imaging_params(array_cfg, band)
    cell_as = img_params["cell_as"]

    pixel_scale_res = cell_as / 3.0
    pixel_scale_fov = (r_out * 2.5 * 1.8) / IMG_SIZE
    pixel_scale = float(np.clip(max(pixel_scale_res, pixel_scale_fov), 0.0007, 0.050))

    x_coords = np.arange(-IMG_SIZE // 2, IMG_SIZE // 2) * pixel_scale
    x_grid, y_grid = np.meshgrid(x_coords, x_coords)

    pa_rad = np.radians(pos_angle)
    cos_i = max(np.cos(np.radians(inclination)), 0.05)

    dx_center = float(dx_arcsec) if dx_arcsec is not None else float(rng.normal(0, 0.035))
    dy_center = float(dy_arcsec) if dy_arcsec is not None else float(rng.normal(0, 0.035))

    x_rel = x_grid - dx_center
    y_rel = y_grid - dy_center

    r_maj = -x_rel * np.sin(pa_rad) + y_rel * np.cos(pa_rad)
    r_min_coord = x_rel * np.cos(pa_rad) + y_rel * np.sin(pa_rad)
    r_min_deprojected = r_min_coord / cos_i

    radius = np.sqrt(r_maj ** 2 + r_min_deprojected ** 2)
    theta = np.arctan2(r_min_deprojected, r_maj)
    radius_safe = np.maximum(radius, pixel_scale * 0.3)

    gamma = rng.uniform(0.3, 1.0)
    rc = max(r_out * rng.uniform(0.35, 0.75), 0.02)
    sigma = (radius_safe / rc) ** (-gamma) * np.exp(-(radius_safe / rc) ** (2.0 - gamma))
    sigma = np.clip(sigma / (sigma.max() + 1e-10), 0.0, 1.0)

    t0 = rng.uniform(40, 160)
    r_ref = max(r_out * 0.05, pixel_scale * 2)
    q = rng.uniform(0.35, 0.55)
    t_r = np.clip(t0 * (radius_safe / r_ref) ** (-q), 5.0, 2000.0)

    tau_max = rng.uniform(1.5, 10.0) * kappa
    disk = t_r * (1.0 - np.exp(-tau_max * sigma))

    if r_min > 0.025:
        w_rim = r_min * rng.uniform(0.20, 0.45)
        taper = 0.5 * (1.0 + np.tanh((radius_safe - r_min) / (w_rim + 1e-5)))
        dep_cav = rng.uniform(0.70, 0.95)
        disk *= 1.0 - dep_cav * (1.0 - taper)
        if rng.rand() < 0.60:
            peak_val = np.percentile(disk[disk > 0], 90) if np.any(disk > 0) else 1.0
            amp_wall = rng.uniform(0.10, 0.50) * peak_val
            w_wall = r_min * rng.uniform(0.08, 0.22)
            disk += amp_wall * np.exp(-((radius_safe - r_min) / (w_wall + 1e-5)) ** 2)

    morphology = rng.choice(["smooth", "simple", "complex"], p=[0.25, 0.40, 0.35])
    if morphology == "smooth":
        n_gaps = 0
    elif morphology == "simple":
        n_gaps = rng.randint(1, 3)
    else:
        n_gaps = rng.randint(3, 6)

    r_features = [r_min if r_min > 0.025 else 0.0]
    for _ in range(n_gaps):
        r0_gap = max(r_min + 0.03, r_out * 0.08)
        r_gap = rng.uniform(r0_gap, r_out * 0.88)
        if any(abs(r_gap - rf) < r_out * 0.10 for rf in r_features):
            continue
        r_features.append(r_gap)
        w_gap = r_gap * rng.uniform(0.04, 0.14)
        depth = rng.uniform(0.35, 0.80)
        disk *= 1.0 - depth * np.exp(-0.5 * ((radius_safe - r_gap) / (w_gap + 1e-5)) ** 2)
        if rng.rand() < 0.80:
            r_ring = r_gap + w_gap * rng.uniform(0.8, 2.5)
            if r_ring < r_out * 0.95:
                w_ring = w_gap * rng.uniform(0.5, 1.5)
                amp_ring = rng.uniform(0.08, 0.40) * (np.max(disk) + 1e-15)
                disk += amp_ring * np.exp(-0.5 * ((radius_safe - r_ring) / (w_ring + 1e-5)) ** 2)
                r_features.append(r_ring)

    if rng.rand() < 0.20:
        r_v = rng.uniform(max(r_min + 0.02, r_out * 0.25), r_out * 0.80)
        phi_v = rng.uniform(0, 2 * np.pi)
        w_r_v = r_v * rng.uniform(0.10, 0.25)
        w_p_v = rng.uniform(0.5, 1.8)
        dphi = np.angle(np.exp(1j * (theta - phi_v)))
        mask_annulus = np.abs(radius_safe - r_v) < w_r_v * 2
        bg_intensity = np.median(disk[mask_annulus]) if np.any(mask_annulus) else 1e-15
        contrast = rng.uniform(3, 8)
        crescent = (
            contrast * bg_intensity
            * np.exp(-0.5 * ((radius_safe - r_v) / (w_r_v + 1e-5)) ** 2)
            * np.exp(-0.5 * (dphi / (w_p_v + 1e-5)) ** 2)
        )
        disk += crescent

    if rng.rand() < 0.80:
        peak_disk = np.max(disk) + 1e-15
        amp_c = rng.uniform(0.15, 0.60) * peak_disk
        r_c = pixel_scale * rng.uniform(0.5, 1.5)
        disk += amp_c * np.exp(-(radius_safe / (r_c + 1e-5)) ** 2)

    disk *= generate_texture(
        (IMG_SIZE, IMG_SIZE),
        scale=int(rng.randint(35, 70)),
        amp=0.012,
        rng=rng,
    )

    halo_amp = rng.uniform(0.008, 0.035) * np.max(disk)
    halo_scale = r_out * rng.uniform(1.5, 3.0)
    disk += halo_amp * np.exp(-(radius_safe / (halo_scale + 1e-5)) ** 0.7)

    n_exp = rng.uniform(1.5, 3.5)
    disk *= np.exp(-(radius_safe / (r_out + 1e-5)) ** n_exp)
    disk = np.maximum(disk, 0.0)

    total_sum = disk.sum()
    if total_sum > 0:
        disk = disk * (total_flux / total_sum)

    if pre_smooth != "off":
        beam_as = img_params["beam_as"]
        denom = 12.0 if pre_smooth == "light" else 6.0
        sigma_smooth = (beam_as / denom) / pixel_scale
        if sigma_smooth > 0.5:
            disk = gaussian_filter(disk.astype(np.float64), sigma=sigma_smooth)
        disk = np.maximum(disk, 0.0)

    hdu = fits.PrimaryHDU(disk.astype(np.float32))
    header = hdu.header
    header["BUNIT"] = "Jy/pixel"
    header["CTYPE1"] = "RA---SIN"
    header["CTYPE2"] = "DEC--SIN"
    header["RADESYS"] = "ICRS"
    header["EQUINOX"] = 2000.0
    header["CDELT1"] = -pixel_scale / 3600.0
    header["CDELT2"] = pixel_scale / 3600.0
    header["CRPIX1"] = IMG_SIZE // 2 + 1
    header["CRPIX2"] = IMG_SIZE // 2 + 1
    header["CRVAL1"] = 250.0
    header["CRVAL2"] = -30.0
    header["CUNIT1"] = "deg"
    header["CUNIT2"] = "deg"
    header["RESTFRQ"] = band_params["freq_ghz"] * 1e9
    header["PIXSCALE"] = pixel_scale
    header["BAND"] = band
    header["ARRAYCFG"] = array_cfg
    header["DX_AS"] = dx_center
    header["DY_AS"] = dy_center
    hdu.writeto(out_path, overwrite=True)

    return out_path, pixel_scale, dx_center, dy_center


def _parse_optional_float(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    return float(s)


def _col(row, *names):
    """Return first non-empty value among candidate header names."""
    for name in names:
        if name in row and row[name] is not None and str(row[name]).strip() != "":
            return row[name]
    raise KeyError(f"none of {names} found in catalogue row")


def _row_fields(row):
    """Extract catalogue fields by header name (see generate_catalogue.py)."""
    obj_id = str(_col(row, "ID", "id", "obj_id"))
    return dict(
        obj_id=obj_id,
        inclination=float(_col(row, "incl_deg", "inclination")),
        pos_angle=float(_col(row, "pa_deg", "pos_angle")),
        r_out=float(_col(row, "rout_arcsec", "r_out")),
        r_min=float(_col(row, "rmin_arcsec", "r_min")),
        flux_jy=float(_col(row, "flux_jy")),
        time_s=float(_col(row, "time_s")),
        array_cfg=str(_col(row, "array_cfg")),
        pwv=float(_col(row, "pwv")),
        niter=int(float(_col(row, "niter"))),
        band=int(float(_col(row, "band"))),
        dx_arcsec=_parse_optional_float(row.get("dx_arcsec")),
        dy_arcsec=_parse_optional_float(row.get("dy_arcsec")),
        array_lo=(str(row.get("array_lo") or "").strip() or DEFAULT_ARRAY_LO),
    )


def _final_fits_name(obj_id, band, multi=False):
    if multi:
        return f"{obj_id}_B{band}_mc_simulated.fits"
    return f"{obj_id}_B{band}_simulated.fits"


def _final_fits_path(out_dir, obj_id, band, multi=False):
    return os.path.join(os.path.abspath(out_dir), obj_id, _final_fits_name(obj_id, band, multi=multi))


def _read_beam_from_fits(fits_path):
    bmaj = bmin = bpa = ""
    try:
        with fits.open(fits_path) as hdul:
            hdr = hdul[0].header
            if "BMAJ" in hdr:
                bmaj = float(hdr["BMAJ"])
            if "BMIN" in hdr:
                bmin = float(hdr["BMIN"])
            if "BPA" in hdr:
                bpa = float(hdr["BPA"])
    except Exception:
        pass
    return bmaj, bmin, bpa


def _update_offsets_csv(out_dir, obj_id, dx_arcsec, dy_arcsec, fits_name, fits_path):
    csv_path = os.path.join(os.path.abspath(out_dir), OFFSETS_CSV)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    bmaj, bmin, bpa = _read_beam_from_fits(fits_path)
    fieldnames = ["ID", "dx_arcsec", "dy_arcsec", "fits_name", "bmaj_deg", "bmin_deg", "bpa_deg"]
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("ID") == obj_id and r.get("fits_name") == fits_name:
                    continue
                rows.append({k: r.get(k, "") for k in fieldnames})
    rows.append({
        "ID": obj_id,
        "dx_arcsec": dx_arcsec,
        "dy_arcsec": dy_arcsec,
        "fits_name": fits_name,
        "bmaj_deg": bmaj,
        "bmin_deg": bmin,
        "bpa_deg": bpa,
    })
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _add_domain_noise(fits_final):
    """Add fine + large-scale noise after exportfits."""
    with fits.open(fits_final, mode="update") as hdul:
        data = hdul[0].data.astype(np.float64)
        data2d = data.squeeze()
        ny, nx = data2d.shape
        cy, cx = ny // 2, nx // 2
        yy, xx = np.ogrid[:ny, :nx]
        rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        border_mask = rr > 0.80 * min(cy, cx)
        bg_rms = np.std(data2d[border_mask])
        if bg_rms > 0:
            fine_noise = gaussian_filter(np.random.normal(0, 1, data2d.shape), sigma=0.5)
            fine_noise *= 0.25 * bg_rms / (np.std(fine_noise) + 1e-20)
            lf_noise = gaussian_filter(np.random.normal(0, 1, data2d.shape), sigma=8.0)
            lf_noise *= 0.15 * bg_rms / (np.std(lf_noise) + 1e-20)
            hdul[0].data = (data2d + fine_noise + lf_noise).reshape(data.shape).astype(np.float32)
            hdul.flush()
            print(f"  [NOISE] bg_rms={bg_rms * 1e6:.2f} uJy/beam  + fine 25% + LF 15%")


def _stamp_training_keywords(fits_path, row_fields, dx_as, dy_as, band_params):
    """Stamp geometry labels needed for CNN training onto the FITS product."""
    with fits.open(fits_path, mode="update") as hdul:
        hdr = hdul[0].header
        hdr["DX_AS"] = (float(dx_as), "Sky-plane center offset x [arcsec]")
        hdr["DY_AS"] = (float(dy_as), "Sky-plane center offset y [arcsec]")
        hdr["INCL"] = (float(row_fields["inclination"]), "True inclination [deg]")
        hdr["PA"] = (float(row_fields["pos_angle"]), "True PA [deg]")
        hdr["ROUT"] = (float(row_fields["r_out"]), "True Rout [arcsec]")
        hdr["RMIN"] = (float(row_fields["r_min"]), "True Rmin [arcsec]")
        hdr["RESTFRQ"] = (float(band_params["freq_ghz"]) * 1e9, "Rest frequency [Hz]")
        hdr["OBJECT"] = (str(row_fields["obj_id"]), "Catalogue object ID")
        hdr["ARRAYCFG"] = (str(row_fields["array_cfg"]), "ALMA antenna config")
        hdul.flush()


def simulate_disk(row, out_dir, pre_smooth="light"):
    import casatasks

    f = _row_fields(row)
    obj_id = f["obj_id"]
    band = f["band"]
    array_cfg = f["array_cfg"]
    band_params = BANDS[band]

    print(f"\n{'=' * 60}")
    print(f"  {obj_id} | Band {band} ({band_params['freq_ghz']} GHz) | {array_cfg} | PWV {f['pwv']} mm")
    print(f"{'=' * 60}")

    base_dir = os.path.abspath(os.getcwd())
    obj_dir = os.path.join(os.path.abspath(out_dir), obj_id)
    os.makedirs(obj_dir, exist_ok=True)

    img_params = get_imaging_params(array_cfg, band)
    fits_model_name = f"{obj_id}_model.fits"
    fits_model_path = os.path.join(obj_dir, fits_model_name)
    _, pixel_scale, dx_as, dy_as = create_fits_model(
        fits_model_path,
        f["inclination"], f["pos_angle"], f["r_out"], f["r_min"],
        f["flux_jy"], band=band, array_cfg=array_cfg,
        dx_arcsec=f["dx_arcsec"], dy_arcsec=f["dy_arcsec"],
        pre_smooth=pre_smooth,
        rng=_morph_rng(obj_id, _BASE_SEED),
    )
    print(
        f"  Sky model: pixel_scale = {pixel_scale * 1000:.2f} mas/px  "
        f"cell_tclean = {img_params['cell']}  "
        f"ratio = {pixel_scale * 1000 / img_params['cell_mas']:.2f}x"
    )
    print(f"  FOV sky model = {pixel_scale * IMG_SIZE * 1000:.0f} mas  (r_out = {f['r_out'] * 1000:.0f} mas)")
    print(f"  Center offset: dx={dx_as:.5f}\"  dy={dy_as:.5f}\"")

    project = "sim"
    img_base = f"{obj_id}_B{band}"
    fits_final_name = _final_fits_name(obj_id, band, multi=False)
    fits_final_abs = os.path.join(obj_dir, fits_final_name)
    eff_niter = min(int(f["niter"]), 800)

    try:
        os.chdir(obj_dir)
        if os.path.exists(project):
            shutil.rmtree(project)

        print("  -> simobserve ...")
        try:
            casatasks.simobserve(
                project=project,
                skymodel=fits_model_name,
                indirection="J2000 16h40m0s -30d0m0s",
                incell=f"{pixel_scale}arcsec",
                incenter=f"{band_params['freq_ghz']}GHz",
                inwidth=f"{band_params['bw_ghz']}GHz",
                antennalist=array_cfg,
                totaltime=f"{f['time_s']}s",
                thermalnoise="tsys-atm",
                user_pwv=float(f["pwv"]),
                graphics="none",
            )
        except Exception as e:
            print(f"  [ERROR] simobserve: {e}")
            return False

        cfg_base = array_cfg.replace(".cfg", "")
        ms_file = os.path.join(project, f"sim.{cfg_base}.ms")
        if not os.path.exists(ms_file):
            candidates = [x for x in os.listdir(project) if x.endswith(".ms")]
            if candidates:
                ms_file = os.path.join(project, candidates[0])
                print(f"  MS found: {candidates[0]}")
            else:
                print(f"  [ERROR] MS file not found in {project}/")
                return False

        print(f"  -> tclean (multiscale, niter={eff_niter}, robust=0.5, nsigma=4.5) ...")
        try:
            casatasks.tclean(
                vis=ms_file,
                imagename=img_base,
                imsize=img_params["imsize"],
                cell=img_params["cell"],
                specmode="mfs",
                deconvolver="multiscale",
                scales=img_params["scales"],
                smallscalebias=0.9,
                niter=eff_niter,
                nsigma=4.5,
                pblimit=0.1,
                weighting="briggs",
                robust=0.5,
                cyclefactor=2.0,
                gain=0.1,
                pbcor=False,
                interactive=False,
            )
        except Exception as e:
            print(f"  [ERROR] tclean: {e}")
            return False

        img_casa = img_base + ".image"
        if not os.path.exists(img_casa):
            print("  [ERROR] tclean did not generate .image")
            return False

        casatasks.exportfits(
            imagename=img_casa,
            fitsimage=fits_final_name,
            overwrite=True,
            dropdeg=True,
        )
        try:
            _add_domain_noise(fits_final_name)
        except Exception as e:
            print(f"  [WARN] Noise post-processing failed: {e}")

        try:
            _stamp_training_keywords(fits_final_name, f, dx_as, dy_as, band_params)
        except Exception as e:
            print(f"  [WARN] Keyword stamp failed: {e}")

        try:
            with fits.open(fits_final_name) as hdul:
                shape = hdul[0].data.shape
            print(f"  [OK] -> {fits_final_name}  shape={shape}")
        except Exception as e:
            print(f"  [WARN] FITS exported but verification failed: {e}")

        _update_offsets_csv(out_dir, obj_id, dx_as, dy_as, fits_final_name, fits_final_abs)
        return True
    finally:
        os.chdir(base_dir)


def simulate_disk_multiconfig(row, out_dir, pre_smooth="light", time_lo_s=3600):
    import casatasks

    f = _row_fields(row)
    obj_id = f["obj_id"]
    band = f["band"]
    array_cfg = f["array_cfg"]
    array_lo = f["array_lo"]
    band_params = BANDS[band]

    print(f"\n{'=' * 60}")
    print(f"  {obj_id} | MULTI-CONFIG | Band {band}")
    print(f"  Hi-res: {array_cfg}   Lo-res: {array_lo}")
    print(f"{'=' * 60}")

    base_dir = os.path.abspath(os.getcwd())
    obj_dir = os.path.join(os.path.abspath(out_dir), obj_id)
    os.makedirs(obj_dir, exist_ok=True)

    img_params = get_imaging_params(array_cfg, band)
    fits_model_name = f"{obj_id}_model.fits"
    fits_model_path = os.path.join(obj_dir, fits_model_name)
    _, pixel_scale, dx_as, dy_as = create_fits_model(
        fits_model_path,
        f["inclination"], f["pos_angle"], f["r_out"], f["r_min"],
        f["flux_jy"], band=band, array_cfg=array_cfg,
        dx_arcsec=f["dx_arcsec"], dy_arcsec=f["dy_arcsec"],
        pre_smooth=pre_smooth,
        rng=_morph_rng(obj_id, _BASE_SEED),
    )
    print(f"  Center offset: dx={dx_as:.5f}\"  dy={dy_as:.5f}\"")

    fits_final_name = _final_fits_name(obj_id, band, multi=True)
    fits_final_abs = os.path.join(obj_dir, fits_final_name)
    eff_niter = min(int(f["niter"]), 800)

    try:
        os.chdir(obj_dir)

        def _simobserve(proj, cfg, ttime):
            if os.path.exists(proj):
                shutil.rmtree(proj)
            casatasks.simobserve(
                project=proj,
                skymodel=fits_model_name,
                indirection="J2000 16h40m0s -30d0m0s",
                incell=f"{pixel_scale}arcsec",
                incenter=f"{band_params['freq_ghz']}GHz",
                inwidth=f"{band_params['bw_ghz']}GHz",
                antennalist=cfg,
                totaltime=f"{ttime}s",
                thermalnoise="tsys-atm",
                user_pwv=float(f["pwv"]),
                graphics="none",
            )
            for name in os.listdir(proj):
                if name.endswith(".ms"):
                    return os.path.join(proj, name)
            return None

        print("  -> simobserve HI ...")
        ms_hi = _simobserve("sim_hi", array_cfg, f["time_s"])
        if ms_hi is None:
            print("  [ERROR] simobserve HI failed")
            return False

        print("  -> simobserve LO ...")
        ms_lo = _simobserve("sim_lo", array_lo, time_lo_s)
        if ms_lo is None:
            print("  [ERROR] simobserve LO failed")
            return False

        ms_combined = f"{obj_id}_combined.ms"
        if os.path.exists(ms_combined):
            shutil.rmtree(ms_combined)
        print("  -> concat ...")
        casatasks.concat(vis=[ms_hi, ms_lo], concatvis=ms_combined)

        img_base = f"{obj_id}_B{band}_mc"
        print(f"  -> tclean multi-config (niter={eff_niter}) ...")
        try:
            casatasks.tclean(
                vis=ms_combined,
                imagename=img_base,
                imsize=img_params["imsize"],
                cell=img_params["cell"],
                specmode="mfs",
                deconvolver="multiscale",
                scales=img_params["scales"],
                smallscalebias=0.9,
                niter=eff_niter,
                nsigma=4.5,
                pblimit=0.1,
                weighting="briggs",
                robust=0.5,
                cyclefactor=2.0,
                gain=0.1,
                pbcor=False,
                interactive=False,
            )
        except Exception as e:
            print(f"  [ERROR] tclean: {e}")
            return False

        img_casa = img_base + ".image"
        if not os.path.exists(img_casa):
            print("  [ERROR] tclean multi-config did not generate .image")
            return False

        casatasks.exportfits(
            imagename=img_casa,
            fitsimage=fits_final_name,
            overwrite=True,
            dropdeg=True,
        )
        try:
            _add_domain_noise(fits_final_name)
        except Exception as e:
            print(f"  [WARN] Noise post-processing MC failed: {e}")

        try:
            _stamp_training_keywords(fits_final_name, f, dx_as, dy_as, band_params)
        except Exception as e:
            print(f"  [WARN] Keyword stamp failed: {e}")

        print(f"  [OK] -> {fits_final_name}")
        _update_offsets_csv(out_dir, obj_id, dx_as, dy_as, fits_final_name, fits_final_abs)
        return True
    finally:
        os.chdir(base_dir)


def _use_multiconfig(r_out, array_cfg):
    return r_out > 0.80 and any(c in array_cfg for c in ["cycle9.7", "cycle9.8", "cycle9.9"])


def parse_args():
    p = argparse.ArgumentParser(
        description="Simulate ALMA continuum disks from a catalogue CSV.",
    )
    p.add_argument("--catalog", default=CATALOG_FILE, help="Catalogue CSV path")
    p.add_argument("--out-dir", default=OUTPUT_DIR, help="Output simulations directory")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="Process at most N rows")
    p.add_argument("--seed", type=int, default=None, help="RNG seed")
    p.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-simulate even if *_simulated.fits already exists",
    )
    p.add_argument(
        "--pre-smooth",
        choices=["off", "light"],
        default="light",
        help="Sky-model pre-smooth: light=beam/12 (default), off=disable (was beam/6)",
    )
    return p.parse_args()


def main():
    global _BASE_SEED
    args = parse_args()
    if args.seed is not None:
        np.random.seed(args.seed)
        _BASE_SEED = int(args.seed)

    catalog = os.path.abspath(args.catalog)
    out_dir = os.path.abspath(args.out_dir)

    if not os.path.exists(catalog):
        print(f"[ERROR] '{catalog}' not found.")
        return

    with open(catalog, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    print(f"[INFO] {len(rows)} disks from {catalog}")
    print(f"[INFO] out-dir={out_dir}  pre-smooth={args.pre_smooth}  skip={not args.no_skip}")
    os.makedirs(out_dir, exist_ok=True)

    success_count = 0
    error_count = 0
    skip_count = 0
    exec_times = []

    for row in rows:
        start_time = time.time()
        try:
            f = _row_fields(row)
            multi = _use_multiconfig(f["r_out"], f["array_cfg"])
            final_path = _final_fits_path(out_dir, f["obj_id"], f["band"], multi=multi)

            if not args.no_skip and os.path.exists(final_path):
                print(f"[SKIP] {f['obj_id']}: {os.path.basename(final_path)} exists")
                skip_count += 1
                continue

            ok = False
            if multi:
                ok = simulate_disk_multiconfig(row, out_dir, pre_smooth=args.pre_smooth)
            else:
                ok = simulate_disk(row, out_dir, pre_smooth=args.pre_smooth)

            if ok:
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            obj = row.get("ID", row.get(list(row.keys())[0], "?"))
            print(f"[ERROR] {obj}: {e}")
            error_count += 1

        elapsed_time = time.time() - start_time
        exec_times.append(elapsed_time)
        obj = row.get("ID", "?")
        print(f"[TIME] {obj}: {elapsed_time:.1f} s")

    avg_time = float(np.mean(exec_times)) if exec_times else 0.0
    print(f"\n[DONE] {success_count} OK  |  {skip_count} skipped  |  {error_count} errors")
    print(f"[EST.] Average execution time: {avg_time:.1f} s  ->  100 disks ≈ {avg_time * 100 / 3600:.1f} h")


if __name__ == "__main__":
    main()
