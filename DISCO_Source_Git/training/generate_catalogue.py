#!/usr/bin/env python3
"""Generate a pilot catalogue for CASA simulations / CNN training."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

B6_CONFIGS = ["alma.cycle9.6.cfg", "alma.cycle9.7.cfg", "alma.cycle9.8.cfg"]
B6_PROBS = [0.20, 0.35, 0.45]
B8_CONFIGS = ["alma.cycle9.5.cfg", "alma.cycle9.6.cfg", "alma.cycle9.7.cfg"]
B8_PROBS = [0.20, 0.35, 0.45]
B6_ARRAY_LO = "alma.cycle9.5.cfg"
B8_ARRAY_LO = "alma.cycle9.5.cfg"

def build_catalog(n_disks: int, seed: int):
    rng = np.random.RandomState(seed)
    catalog_data = []

    for i in range(1, n_disks + 1):
        obj_id = f"Disk_{i:03d}"

        incl_range = rng.choice(["low", "high"], p=[0.40, 0.60])
        if incl_range == "low":
            incl = rng.uniform(0.0, 30.0)
        else:
            incl = rng.uniform(30.0, 80.0)

        pa = rng.uniform(0.0, 180.0)

        size_mode = rng.choice(["compact", "large", "intermediate"], p=[0.35, 0.35, 0.30])
        if size_mode == "compact":
            r_out = rng.uniform(0.10, 0.50)
        elif size_mode == "large":
            r_out = rng.uniform(0.60, 1.80)
        else:
            r_out = rng.uniform(0.35, 0.90)

        r_min = round(rng.uniform(0.05, r_out * 0.55), 3) if rng.rand() < 0.30 else 0.0

        dx_arcsec = float(np.clip(rng.normal(0.0, 0.035), -0.12, 0.12))
        dy_arcsec = float(np.clip(rng.normal(0.0, 0.035), -0.12, 0.12))

        band = int(rng.choice([6, 8], p=[0.70, 0.30]))

        if band == 6:
            flux = float(np.exp(rng.uniform(np.log(0.005), np.log(0.080))))
            array_cfg = rng.choice(B6_CONFIGS, p=B6_PROBS)
            array_lo = B6_ARRAY_LO
            pwv = round(rng.uniform(0.8, 2.5), 2)
        else:
            flux = float(np.exp(rng.uniform(np.log(0.005), np.log(0.040))))
            array_cfg = rng.choice(B8_CONFIGS, p=B8_PROBS)
            array_lo = B8_ARRAY_LO
            pwv = round(rng.uniform(0.4, 1.2), 2)

        time_s = int(rng.choice([1200, 1800, 2400, 3600]))
        niter = int(rng.uniform(300, 1500))

        catalog_data.append(
            [
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
                round(dx_arcsec, 5),
                round(dy_arcsec, 5),
            ]
        )
    return catalog_data


def write_catalog(catalog_data, output_file: Path):
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ID",
                "incl_deg",
                "pa_deg",
                "rout_arcsec",
                "rmin_arcsec",
                "flux_jy",
                "time_s",
                "array_cfg",
                "pwv",
                "niter",
                "band",
                "array_lo",
                "dx_arcsec",
                "dy_arcsec",
            ]
        )
        writer.writerows(catalog_data)


def print_summary(catalog_data):
    data_array = np.array(catalog_data, dtype=object)
    rout_array = data_array[:, 3].astype(float)
    band_array = data_array[:, 10].astype(int)
    cfg_array = data_array[:, 7]
    flux_array = data_array[:, 5].astype(float)
    mc_mask = rout_array > 0.80

    print(
        f"\n  rout:  min={rout_array.min():.2f}\"  "
        f"median={np.median(rout_array):.2f}\"  max={rout_array.max():.2f}\""
    )
    print(f"  Band 6: {np.sum(band_array == 6)}  |  Band 8: {np.sum(band_array == 8)}")
    print(f"  Multi-config disks (rout > 0.8\"): {mc_mask.sum()}")
    print(
        f"  B6 Flux [mJy]: p10={np.percentile(flux_array[band_array == 6] * 1e3, 10):.1f}  "
        f"median={np.median(flux_array[band_array == 6] * 1e3):.1f}  "
        f"p90={np.percentile(flux_array[band_array == 6] * 1e3, 90):.1f}"
    )
    print("\n  Configuration distribution:")
    for cfg in np.unique(cfg_array):
        print(f"    {cfg}: {np.sum(cfg_array == cfg)}")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=100, help="Number of disks (release target ≥300–500)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default="catalogo_piloto.csv")
    return p.parse_args()


def main():
    args = parse_args()
    catalog_data = build_catalog(args.n, args.seed)
    out = Path(args.out)
    write_catalog(catalog_data, out)
    print(f"[INFO] Catalog generated: {args.n} disks -> {out}")
    print_summary(catalog_data)


if __name__ == "__main__":
    main()
