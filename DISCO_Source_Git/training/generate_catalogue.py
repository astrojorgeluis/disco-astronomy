import csv
import numpy as np

NUM_DISKS = 100
OUTPUT_FILE = "catalogo_piloto.csv"

np.random.seed(42)

B6_CONFIGS = ["alma.cycle9.6.cfg", "alma.cycle9.7.cfg", "alma.cycle9.8.cfg"]
B6_PROBS = [0.20, 0.35, 0.45]

B8_CONFIGS = ["alma.cycle9.5.cfg", "alma.cycle9.6.cfg", "alma.cycle9.7.cfg"]
B8_PROBS = [0.20, 0.35, 0.45]

B6_ARRAY_LO = "alma.cycle9.5.cfg"
B8_ARRAY_LO = "alma.cycle9.5.cfg"

catalog_data = []

for i in range(1, NUM_DISKS + 1):
    obj_id = f"Disk_{i:03d}"

    incl_range = np.random.choice(["low", "high"], p=[0.40, 0.60])
    if incl_range == "low":
        incl = np.random.uniform(0.0, 30.0)
    else:
        incl = np.random.uniform(30.0, 80.0)
        
    pa = np.random.uniform(0.0, 180.0)

    size_mode = np.random.choice(["compact", "large", "intermediate"], p=[0.35, 0.35, 0.30])
    if size_mode == "compact":
        r_out = np.random.uniform(0.10, 0.50)
    elif size_mode == "large":
        r_out = np.random.uniform(0.60, 1.80)
    else:
        r_out = np.random.uniform(0.35, 0.90)

    r_min = round(np.random.uniform(0.05, r_out * 0.55), 3) if np.random.rand() < 0.30 else 0.0

    band = int(np.random.choice([6, 8], p=[0.70, 0.30]))

    if band == 6:
        flux = float(np.exp(np.random.uniform(np.log(0.005), np.log(0.080))))
        array_cfg = np.random.choice(B6_CONFIGS, p=B6_PROBS)
        array_lo = B6_ARRAY_LO
        pwv = round(np.random.uniform(0.8, 2.5), 2)
    else:
        flux = float(np.exp(np.random.uniform(np.log(0.005), np.log(0.040))))
        array_cfg = np.random.choice(B8_CONFIGS, p=B8_PROBS)
        array_lo = B8_ARRAY_LO
        pwv = round(np.random.uniform(0.4, 1.2), 2)

    time_s = int(np.random.choice([1200, 1800, 2400, 3600]))
    niter = int(np.random.uniform(300, 1500))

    catalog_data.append([
        obj_id,
        round(incl, 2),
        round(pa, 2),
        round(r_out, 3),
        round(r_min, 3),
        round(flux, 6),
        time_s,
        array_cfg,
        pwv,
        niter,
        band,
        array_lo,
    ])

with open(OUTPUT_FILE, mode="w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "ID", "incl_deg", "pa_deg", "rout_arcsec", "rmin_arcsec",
        "flux_jy", "time_s", "array_cfg", "pwv", "niter", "band", "array_lo"
    ])
    writer.writerows(catalog_data)

print(f"[INFO] Catalog generated: {NUM_DISKS} disks -> {OUTPUT_FILE}")

data_array = np.array(catalog_data, dtype=object)
rout_array = data_array[:, 3].astype(float)
band_array = data_array[:, 10].astype(int)
cfg_array = data_array[:, 7]
flux_array = data_array[:, 5].astype(float)
mc_mask = rout_array > 0.80

print(f"\n  rout:  min={rout_array.min():.2f}\"  median={np.median(rout_array):.2f}\"  max={rout_array.max():.2f}\"")
print(f"  Band 6: {np.sum(band_array == 6)}  |  Band 8: {np.sum(band_array == 8)}")
print(f"  Multi-config disks (rout > 0.8\"): {mc_mask.sum()}")
print(f"  B6 Flux [mJy]: p10={np.percentile(flux_array[band_array == 6] * 1e3, 10):.1f}  "
      f"median={np.median(flux_array[band_array == 6] * 1e3):.1f}  "
      f"p90={np.percentile(flux_array[band_array == 6] * 1e3, 90):.1f}")
print(f"\n  Configuration distribution:")
for cfg in np.unique(cfg_array):
    print(f"    {cfg}: {np.sum(cfg_array == cfg)}")