import os
import csv
import shutil
import time
import numpy as np
from astropy.io import fits
from scipy.ndimage import gaussian_filter
import casatasks

CATALOG_FILE = "catalogo_piloto.csv"
OUTPUT_DIR = "simulations"
IMG_SIZE = 1024     

BANDS = {
    6: dict(freq_ghz=230.0, bw_ghz=7.5, pb_as=25.0, kappa=1.00),
    8: dict(freq_ghz=405.0, bw_ghz=7.5, pb_as=14.3, kappa=2.70),
}

ARRAYS = {
    "alma.cycle9.5.cfg": dict(beam_mas=130, cell_mas=22),
    "alma.cycle9.6.cfg": dict(beam_mas= 80, cell_mas=13),
    "alma.cycle9.7.cfg": dict(beam_mas= 50, cell_mas= 8),
    "alma.cycle9.8.cfg": dict(beam_mas= 28, cell_mas= 5),
    "alma.cycle9.9.cfg": dict(beam_mas= 18, cell_mas= 3),
}

def generate_texture(shape, scale=35, amp=0.08):
    noise = gaussian_filter(np.random.normal(0, 1, shape), sigma=scale)
    noise /= np.max(np.abs(noise)) + 1e-10
    return 1.0 + noise * amp

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

def create_fits_model(out_path, inclination, pos_angle, r_out, r_min, total_flux, band=6, array_cfg="alma.cycle9.7.cfg"):
    band_params = BANDS[band]
    kappa = band_params["kappa"]
    img_params = get_imaging_params(array_cfg, band)
    cell_as = img_params["cell_as"]   

    pixel_scale_res = cell_as / 3.0       
    pixel_scale_fov = (r_out * 2.5 * 1.8) / IMG_SIZE   

    pixel_scale = max(pixel_scale_res, pixel_scale_fov)
    pixel_scale = np.clip(pixel_scale, 0.0007, 0.050)

    x_coords = np.arange(-IMG_SIZE // 2, IMG_SIZE // 2) * pixel_scale
    x_grid, y_grid = np.meshgrid(x_coords, x_coords)

    pa_rad = np.radians(pos_angle)
    cos_i = max(np.cos(np.radians(inclination)), 0.05)

    dx_center = np.random.normal(0, 0.010)
    dy_center = np.random.normal(0, 0.010)

    r_maj = -x_grid * np.sin(pa_rad) + y_grid * np.cos(pa_rad)
    r_min_coord = x_grid * np.cos(pa_rad) + y_grid * np.sin(pa_rad)
    r_min_deprojected = r_min_coord / cos_i                         

    radius = np.sqrt((r_maj - dy_center)**2 + (r_min_deprojected - dx_center)**2)
    theta = np.arctan2(r_min_deprojected - dx_center, r_maj - dy_center)
    radius_safe = np.maximum(radius, pixel_scale * 0.3)

    gamma = np.random.uniform(0.3, 1.0)
    rc = max(r_out * np.random.uniform(0.35, 0.75), 0.02)

    sigma = (radius_safe / rc) ** (-gamma) * np.exp(-(radius_safe / rc) ** (2.0 - gamma))
    sigma = np.clip(sigma / (sigma.max() + 1e-10), 0.0, 1.0)

    t0 = np.random.uniform(40, 160)
    r_ref = max(r_out * 0.05, pixel_scale * 2)
    q = np.random.uniform(0.35, 0.55)
    t_r = np.clip(t0 * (radius_safe / r_ref) ** (-q), 5.0, 2000.0)

    tau_max = np.random.uniform(1.5, 10.0) * kappa
    disk = t_r * (1.0 - np.exp(-tau_max * sigma))

    if r_min > 0.025:
        w_rim = r_min * np.random.uniform(0.20, 0.45)
        taper = 0.5 * (1.0 + np.tanh((radius_safe - r_min) / (w_rim + 1e-5)))
        dep_cav = np.random.uniform(0.70, 0.95)
        disk *= 1.0 - dep_cav * (1.0 - taper)

        if np.random.rand() < 0.60:   
            peak_val = np.percentile(disk[disk > 0], 90) if np.any(disk > 0) else 1.0
            amp_wall = np.random.uniform(0.10, 0.50) * peak_val
            w_wall = r_min * np.random.uniform(0.08, 0.22)
            disk += amp_wall * np.exp(-((radius_safe - r_min) / (w_wall + 1e-5)) ** 2)

    morphology = np.random.choice(["smooth", "simple", "complex"], p=[0.25, 0.40, 0.35])
    if morphology == "smooth":
        n_gaps = 0
    elif morphology == "simple":
        n_gaps = np.random.randint(1, 3)
    else:
        n_gaps = np.random.randint(3, 6)

    r_features = [r_min if r_min > 0.025 else 0.0]

    for _ in range(n_gaps):
        r0_gap = max(r_min + 0.03, r_out * 0.08)
        r_gap = np.random.uniform(r0_gap, r_out * 0.88)

        if any(abs(r_gap - rf) < r_out * 0.10 for rf in r_features):
            continue
        r_features.append(r_gap)

        w_gap = r_gap * np.random.uniform(0.04, 0.14)
        depth = np.random.uniform(0.35, 0.80)
        disk *= 1.0 - depth * np.exp(-0.5 * ((radius_safe - r_gap) / (w_gap + 1e-5)) ** 2)

        if np.random.rand() < 0.80:
            r_ring = r_gap + w_gap * np.random.uniform(0.8, 2.5)
            if r_ring < r_out * 0.95:
                w_ring = w_gap * np.random.uniform(0.5, 1.5)
                amp_ring = np.random.uniform(0.08, 0.40) * (np.max(disk) + 1e-15)
                disk += amp_ring * np.exp(-0.5 * ((radius_safe - r_ring) / (w_ring + 1e-5)) ** 2)
                r_features.append(r_ring)

    if np.random.rand() < 0.20:
        r_v = np.random.uniform(max(r_min + 0.02, r_out * 0.25), r_out * 0.80)
        phi_v = np.random.uniform(0, 2 * np.pi)
        w_r_v = r_v * np.random.uniform(0.10, 0.25)
        w_p_v = np.random.uniform(0.5, 1.8)
        dphi = np.angle(np.exp(1j * (theta - phi_v)))

        mask_annulus = np.abs(radius_safe - r_v) < w_r_v * 2
        bg_intensity = np.median(disk[mask_annulus]) if np.any(mask_annulus) else 1e-15

        contrast = np.random.uniform(3, 8)
        crescent = contrast * bg_intensity * np.exp(-0.5 * ((radius_safe - r_v) / (w_r_v + 1e-5)) ** 2) * np.exp(-0.5 * (dphi / (w_p_v + 1e-5)) ** 2)
        disk += crescent

    if np.random.rand() < 0.80:
        peak_disk = np.max(disk) + 1e-15
        amp_c = np.random.uniform(0.15, 0.60) * peak_disk
        r_c = pixel_scale * np.random.uniform(0.5, 1.5)
        disk += amp_c * np.exp(-(radius_safe / (r_c + 1e-5)) ** 2)

    disk *= generate_texture(
        (IMG_SIZE, IMG_SIZE),
        scale=np.random.randint(35, 70),
        amp=0.012
    )

    halo_amp = np.random.uniform(0.008, 0.035) * np.max(disk)
    halo_scale = r_out * np.random.uniform(1.5, 3.0)
    disk += halo_amp * np.exp(-(radius_safe / (halo_scale + 1e-5)) ** 0.7)

    n_exp = np.random.uniform(1.5, 3.5)
    disk *= np.exp(-(radius_safe / (r_out + 1e-5)) ** n_exp)
    disk = np.maximum(disk, 0.0)

    total_sum = disk.sum()
    if total_sum > 0:
        disk = disk * (total_flux / total_sum)

    beam_as = img_params["beam_as"]                      
    sigma_smooth = (beam_as / 6.0) / pixel_scale         
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
    hdu.writeto(out_path, overwrite=True)
    
    return out_path, pixel_scale

def simulate_disk(row):
    row = list(row)
    obj_id, inclination, pos_angle, r_out, r_min, flux_jy, time_s, array_cfg, pwv, niter, band = row[:11]
    band = int(band)
    band_params = BANDS[band]

    print(f"\n{'='*60}")
    print(f"  {obj_id} | Band {band} ({band_params['freq_ghz']} GHz) | {array_cfg} | PWV {pwv} mm")
    print(f"{'='*60}")

    base_dir = os.path.abspath(os.getcwd())
    obj_dir = os.path.join(os.path.abspath(OUTPUT_DIR), obj_id)
    os.makedirs(obj_dir, exist_ok=True)

    img_params = get_imaging_params(array_cfg, band)

    fits_model_name = f"{obj_id}_model.fits"
    fits_model_path = os.path.join(obj_dir, fits_model_name)
    _, pixel_scale = create_fits_model(
        fits_model_path,
        float(inclination), float(pos_angle), float(r_out), float(r_min),
        float(flux_jy), band=band, array_cfg=array_cfg
    )
    
    print(f"  Sky model: pixel_scale = {pixel_scale*1000:.2f} mas/px  cell_tclean = {img_params['cell']}  ratio = {pixel_scale*1000/img_params['cell_mas']:.2f}x")
    print(f"  FOV sky model = {pixel_scale*IMG_SIZE*1000:.0f} mas  (r_out = {float(r_out)*1000:.0f} mas)")

    os.chdir(obj_dir)
    project = "sim"
    if os.path.exists(project):
        shutil.rmtree(project)

    print(f"  -> simobserve ...")
    try:
        casatasks.simobserve(
            project=project,
            skymodel=fits_model_name,
            indirection="J2000 16h40m0s -30d0m0s",
            incell=f"{pixel_scale}arcsec",
            incenter=f"{band_params['freq_ghz']}GHz",
            inwidth=f"{band_params['bw_ghz']}GHz",
            antennalist=array_cfg,
            totaltime=f"{time_s}s",
            thermalnoise="tsys-atm",
            user_pwv=float(pwv),
            graphics="none"
        )
    except Exception as e:
        print(f"  [ERROR] simobserve: {e}")
        os.chdir(base_dir)
        return

    cfg_base = array_cfg.replace(".cfg", "")
    ms_file = os.path.join(project, f"sim.{cfg_base}.ms")

    if not os.path.exists(ms_file):
        candidates = [f for f in os.listdir(project) if f.endswith(".ms")]
        if candidates:
            ms_file = os.path.join(project, candidates[0])
            print(f"  MS found: {candidates[0]}")
        else:
            print(f"  [ERROR] MS file not found in {project}/")
            os.chdir(base_dir)
            return

    img_base = f"{obj_id}_B{band}"
    eff_niter = min(int(niter), 800)

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
        os.chdir(base_dir)
        return

    img_casa = img_base + ".image"
    fits_final = f"{obj_id}_B{band}_simulated.fits"

    if os.path.exists(img_casa):
        casatasks.exportfits(
            imagename=img_casa,
            fitsimage=fits_final,
            overwrite=True,
            dropdeg=True,
        )
        try:
            with fits.open(fits_final, mode="update") as hdul:
                data = hdul[0].data.astype(np.float64)
                data2d = data.squeeze()
                ny, nx = data2d.shape

                cy, cx = ny // 2, nx // 2
                yy, xx = np.ogrid[:ny, :nx]
                rr = np.sqrt((yy - cy)**2 + (xx - cx)**2)
                r_max = min(cy, cx)
                border_mask = rr > 0.80 * r_max

                bg_rms = np.std(data2d[border_mask])
                if bg_rms > 0:
                    fine_noise = np.random.normal(0, 1, data2d.shape)
                    fine_noise = gaussian_filter(fine_noise, sigma=0.5)
                    fine_noise *= 0.25 * bg_rms / (np.std(fine_noise) + 1e-20)

                    lf_noise = np.random.normal(0, 1, data2d.shape)
                    lf_noise = gaussian_filter(lf_noise, sigma=8.0)
                    lf_noise *= 0.15 * bg_rms / (np.std(lf_noise) + 1e-20)

                    data2d = data2d + fine_noise + lf_noise

                    hdul[0].data = data2d.reshape(data.shape).astype(np.float32)
                    hdul.flush()
                    print(f"  [NOISE] bg_rms={bg_rms*1e6:.2f} uJy/beam  + fine 25% + LF 15%")
        except Exception as e:
            print(f"  [WARN] Noise post-processing failed: {e}")

        try:
            with fits.open(fits_final) as hdul:
                shape = hdul[0].data.shape
            print(f"  [OK] -> {fits_final}  shape={shape}")
        except Exception as e:
            print(f"  [WARN] FITS exported but verification failed: {e}")
    else:
        print(f"  [ERROR] tclean did not generate .image")

    os.chdir(base_dir)

def simulate_disk_multiconfig(row, array_lo="alma.cycle9.5.cfg", time_lo_s=3600):
    row = list(row)
    obj_id, inclination, pos_angle, r_out, r_min, flux_jy, time_s, array_cfg, pwv, niter, band = row[:11]
    band = int(band)
    band_params = BANDS[band]

    print(f"\n{'='*60}")
    print(f"  {obj_id} | MULTI-CONFIG | Band {band}")
    print(f"  Hi-res: {array_cfg}   Lo-res: {array_lo}")
    print(f"{'='*60}")

    base_dir = os.path.abspath(os.getcwd())
    obj_dir = os.path.join(os.path.abspath(OUTPUT_DIR), obj_id)
    os.makedirs(obj_dir, exist_ok=True)

    img_params = get_imaging_params(array_cfg, band)

    fits_model_name = f"{obj_id}_model.fits"
    fits_model_path = os.path.join(obj_dir, fits_model_name)
    _, pixel_scale = create_fits_model(
        fits_model_path,
        float(inclination), float(pos_angle), float(r_out), float(r_min),
        float(flux_jy), band=band, array_cfg=array_cfg
    )

    os.chdir(obj_dir)

    def _simobserve(proj, cfg, ttime):
        if os.path.exists(proj):
            shutil.rmtree(proj)
        casatasks.simobserve(
            project=proj, skymodel=fits_model_name,
            indirection="J2000 16h40m0s -30d0m0s",
            incell=f"{pixel_scale}arcsec",
            incenter=f"{band_params['freq_ghz']}GHz",
            inwidth=f"{band_params['bw_ghz']}GHz",
            antennalist=cfg, totaltime=f"{ttime}s",
            thermalnoise="tsys-atm", user_pwv=float(pwv), graphics="none"
        )
        for f in os.listdir(proj):
            if f.endswith(".ms"):
                return os.path.join(proj, f)
        return None

    print("  -> simobserve HI ...")
    ms_hi = _simobserve("sim_hi", array_cfg, time_s)
    if ms_hi is None:
        print("  [ERROR] simobserve HI failed"); os.chdir(base_dir); return

    print("  -> simobserve LO ...")
    ms_lo = _simobserve("sim_lo", array_lo, time_lo_s)
    if ms_lo is None:
        print("  [ERROR] simobserve LO failed"); os.chdir(base_dir); return

    ms_combined = f"{obj_id}_combined.ms"
    if os.path.exists(ms_combined):
        shutil.rmtree(ms_combined)
    print("  -> concat ...")
    casatasks.concat(vis=[ms_hi, ms_lo], concatvis=ms_combined)

    img_base = f"{obj_id}_B{band}_mc"
    eff_niter = min(int(niter), 800)

    print(f"  -> tclean multi-config (niter={eff_niter}) ...")
    try:
        casatasks.tclean(
            vis=ms_combined, imagename=img_base,
            imsize=img_params["imsize"], cell=img_params["cell"],
            specmode="mfs", deconvolver="multiscale",
            scales=img_params["scales"], smallscalebias=0.9,
            niter=eff_niter, nsigma=4.5, pblimit=0.1,
            weighting="briggs", robust=0.5,
            cyclefactor=2.0, gain=0.1, pbcor=False, interactive=False,
        )
    except Exception as e:
        print(f"  [ERROR] tclean: {e}"); os.chdir(base_dir); return

    img_casa = img_base + ".image"
    fits_final = f"{obj_id}_B{band}_mc_simulated.fits"
    if os.path.exists(img_casa):
        casatasks.exportfits(imagename=img_casa, fitsimage=fits_final,
                             overwrite=True, dropdeg=True)
        try:
            with fits.open(fits_final, mode="update") as hdul:
                data = hdul[0].data.astype(np.float64)
                data2d = data.squeeze()
                ny, nx = data2d.shape
                cy, cx = ny // 2, nx // 2
                yy, xx = np.ogrid[:ny, :nx]
                rr = np.sqrt((yy - cy)**2 + (xx - cx)**2)
                border_mask = rr > 0.80 * min(cy, cx)
                bg_rms = np.std(data2d[border_mask])
                if bg_rms > 0:
                    fine_noise = gaussian_filter(
                        np.random.normal(0, 1, data2d.shape), sigma=0.5)
                    fine_noise *= 0.25 * bg_rms / (np.std(fine_noise) + 1e-20)
                    lf_noise = gaussian_filter(
                        np.random.normal(0, 1, data2d.shape), sigma=8.0)
                    lf_noise *= 0.15 * bg_rms / (np.std(lf_noise) + 1e-20)
                    hdul[0].data = (data2d + fine_noise + lf_noise).reshape(data.shape).astype(np.float32)
                    hdul.flush()
        except Exception as e:
            print(f"  [WARN] Noise post-processing MC failed: {e}")
        print(f"  [OK] -> {fits_final}")
    else:
        print("  [ERROR] tclean multi-config did not generate .image")

    os.chdir(base_dir)

if __name__ == "__main__":
    if not os.path.exists(CATALOG_FILE):
        print(f"[ERROR] '{CATALOG_FILE}' not found.")
    else:
        with open(CATALOG_FILE, newline="") as f:
            reader = csv.reader(f)
            _ = next(reader)   
            rows = list(reader)

        print(f"[INFO] {len(rows)} disks found in the catalog.")
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        success_count = 0
        error_count = 0
        exec_times = []

        for row in rows:
            start_time = time.time()
            try:
                r_out_val = float(row[3])
                array_cfg = row[7]
                
                if r_out_val > 0.80 and any(c in array_cfg for c in ["cycle9.7", "cycle9.8", "cycle9.9"]):
                    simulate_disk_multiconfig(row)
                else:
                    simulate_disk(row)
                success_count += 1
            except Exception as e:
                print(f"[ERROR] {row[0]}: {e}")
                error_count += 1
                
            elapsed_time = time.time() - start_time
            exec_times.append(elapsed_time)
            print(f"[TIME] {row[0]}: {elapsed_time:.1f} s")

        avg_time = np.mean(exec_times) if exec_times else 0
        print(f"\n[DONE] {success_count} OK  |  {error_count} errors")
        print(f"[EST.] Average execution time: {avg_time:.1f} s  ->  100 disks ≈ {avg_time*100/3600:.1f} h")