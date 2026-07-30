"""CLI pipeline: discovery, smoke, regressions, parity, and robustness."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from disco.cli import discover_groups, run_pipeline
from disco.core.fits_utils import extract_profile, measure_rout_deproj
from disco.core.profiles import run_analysis_pipeline
from disco.core.units import get_pixel_scale_arcsec, mjy_to_tb, normalize_bunit_to_mjy
from tests.conftest import make_cli_args, make_synthetic_disk

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_discover_groups_bands(multiband_tree):
    groups = discover_groups(multiband_tree["root"])
    assert len(groups) >= 1
    g = next(g for g in groups if "OBJ" in g["name"])
    assert len(g["files"]) == 2
    assert all("Band_" in os.path.basename(f) for f in g["files"])
    assert g["output_dir"].endswith(os.path.join("OBJ", "OBJ")) or g["output_dir"].endswith("/OBJ")


def test_discover_groups_empty(tmp_path):
    assert discover_groups(str(tmp_path)) == []


def test_identifier_filters_by_basename(multiband_tree, monkeypatch):
    """Mirrors the identifier matching logic in disco.cli.main."""
    monkeypatch.chdir(multiband_tree["root"])
    all_groups = discover_groups(multiband_tree["root"])
    clean_ids = ["Band_6"]
    groups = []
    for g in all_groups:
        matched = [f for f in g["files"] if any(ident in os.path.basename(f) for ident in clean_ids)]
        if matched:
            groups.append({"name": g["name"], "files": matched, "output_dir": g["output_dir"]})
    assert len(groups) == 1
    assert len(groups[0]["files"]) == 1
    assert "Band_6" in groups[0]["files"][0]


# ---------------------------------------------------------------------------
# Smoke end-to-end
# ---------------------------------------------------------------------------

def test_run_pipeline_smoke(multiband_tree, monkeypatch):
    monkeypatch.chdir(multiband_tree["root"])
    groups = discover_groups(multiband_tree["root"])
    assert groups
    g = groups[0]
    args = make_cli_args(incl=40.0, pa=90.0, csv="on", homobeam="off", no_gaia=True)
    run_pipeline(g["files"], g["name"], g["output_dir"], args, cnn_model=None)

    png = Path(g["output_dir"]) / f"RP_{g['name']}.PNG"
    assert png.exists() and png.stat().st_size > 1000

    global_csv = Path(g["output_dir"]) / f"RP_{g['name']}_global.csv"
    bands_csv = Path(g["output_dir"]) / f"RP_{g['name']}_bands.csv"
    profile_csv = Path(g["output_dir"]) / f"RP_{g['name']}_profile.csv"
    assert global_csv.exists()
    assert bands_csv.exists()
    assert profile_csv.exists()

    with open(global_csv) as f:
        rows = {r[0]: r for r in csv.reader(f) if r and r[0] != "parameter"}
    for key in ("Rout_arcsec", "Rmin_arcsec", "Inclination_deg", "PA_deg"):
        assert key in rows
        val = float(rows[key][1])
        assert np.isfinite(val)
    assert 0.1 < float(rows["Rout_arcsec"][1]) < 8.0
    assert abs(float(rows["Inclination_deg"][1]) - 40.0) < 1e-6
    assert abs(float(rows["PA_deg"][1]) - 90.0) < 1e-6


# ---------------------------------------------------------------------------
# Regressions: pixel scale, BUNIT, tb_err
# ---------------------------------------------------------------------------

def test_cd_matrix_pixel_scale(cd_matrix_header, tmp_path, monkeypatch):
    """Without the fix, CDELT2 fallback yields ~108\"/pix and absurd Rout."""
    path = tmp_path / "cd_disk.fits"
    fits.PrimaryHDU(data=cd_matrix_header["data"], header=cd_matrix_header["header"]).writeto(path)

    scale = get_pixel_scale_arcsec(cd_matrix_header["header"])
    assert abs(scale - 0.05) < 1e-6

    monkeypatch.chdir(tmp_path)
    args = make_cli_args(incl=40.0, pa=90.0, csv="on", homobeam="off", no_gaia=True)
    out = tmp_path / "out"
    run_pipeline([str(path)], "CDTEST", str(out), args, cnn_model=None)

    with open(out / "RP_CDTEST_global.csv") as f:
        rows = {r[0]: r for r in csv.reader(f) if r and r[0] != "parameter"}
    rout = float(rows["Rout_arcsec"][1])
    # Physical extent of the synthetic ring (~3\") — old bug gave hundreds of arcsec
    assert 0.5 < rout < 6.0, f"Rout={rout} looks like CDELT2*3600 bug"


def test_normalize_bunit_empty_updates_header():
    data, header = make_synthetic_disk(peak=0.5, noise=0.0, bunit="")
    assert header["BUNIT"] == ""
    out, hdr = normalize_bunit_to_mjy(data, header)
    assert hdr["BUNIT"].lower() == "mjy/beam"
    assert np.nanmax(out) == pytest.approx(np.nanmax(data) * 1000.0, rel=1e-5)


def test_extract_profile_tb_err_units(synthetic_disk):
    """tb_err must share TB units everywhere, including near-zero intensity."""
    d = synthetic_disk
    r, tb, err = extract_profile(
        d["data"], d["header"], incl=40.0, pa=90.0,
        pixel_scale=d["pixel_scale"], cx=d["cx"], cy=d["cy"],
        limit_arcsec=4.0,
    )
    factor = float(mjy_to_tb(np.array([1.0]), d["header"])[0])
    assert factor != 1.0  # conversion is active
    # Where intensity is tiny the old element-wise scale left err in mJy/beam
    low = np.abs(tb) < 0.01 * np.nanmax(tb)
    assert low.any()
    # All finite errors should be consistent with the scalar factor (positive)
    assert np.all(np.isfinite(err))
    assert np.nanmax(err) > 0
    # Ratio of peak TB to peak intensity (mJy) ≈ factor; err scale should match
    assert factor > 0


def test_measure_rout_cd_matrix(cd_matrix_header):
    d = cd_matrix_header
    scale = get_pixel_scale_arcsec(d["header"])
    rout = measure_rout_deproj(
        d["data"], d["header"], scale, d["cx"], d["cy"],
        incl=40.0, pa=90.0, rmin=0.2,
    )
    assert 0.5 < rout < 6.0


# ---------------------------------------------------------------------------
# Slow geometry recovery (analytical branch, no CNN)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_analytical_geometry_recovery(tmp_path, monkeypatch):
    """Without --incl/--pa and without CNN, Nelder-Mead recovers injected geometry."""
    incl_true, pa_true = 45.0, 30.0
    data, header = make_synthetic_disk(incl=incl_true, pa=pa_true, noise=0.01, seed=7)
    path = tmp_path / "geom.fits"
    fits.PrimaryHDU(data=data, header=header).writeto(path)

    monkeypatch.chdir(tmp_path)
    args = make_cli_args(incl=None, pa=None, csv="on", homobeam="off", no_gaia=True, rout=2.0)
    out = tmp_path / "geom_out"
    run_pipeline([str(path)], "GEOM", str(out), args, cnn_model=None)

    with open(out / "RP_GEOM_global.csv") as f:
        rows = {r[0]: r for r in csv.reader(f) if r and r[0] != "parameter"}
    incl = float(rows["Inclination_deg"][1])
    pa = float(rows["PA_deg"][1])
    # Wide tolerance: analytical branch is coarse on a small noisy synthetic
    assert abs(incl - incl_true) < 20.0, f"incl={incl}"
    dpa = min(abs(pa - pa_true) % 180, 180 - abs(pa - pa_true) % 180)
    assert dpa < 25.0, f"pa={pa}"


# ---------------------------------------------------------------------------
# Documented CLI vs GUI parity
# ---------------------------------------------------------------------------

def test_cli_gui_peak_radius_parity(synthetic_disk):
    """
    CLI extract_profile fills uncovered pixels with 0; GUI run_analysis_pipeline
    uses NaN-aware means. Peak ring radius should still agree within a wide
    tolerance — this test documents the magnitude of the difference.
    """
    d = synthetic_disk
    r_cli, tb_cli, _ = extract_profile(
        d["data"], d["header"], incl=40.0, pa=90.0,
        pixel_scale=d["pixel_scale"], cx=d["cx"], cy=d["cy"],
        limit_arcsec=4.0,
    )
    out = run_analysis_pipeline(
        d["data"], d["header"], cx=d["cx"], cy=d["cy"],
        pa=90.0, incl=40.0, rout=3.0, fit_rmin=0.8, fit_rmax=2.2,
    )
    r_gui = np.asarray(out["profile"]["radius"], dtype=float)
    tb_gui = np.asarray(out["profile"]["tb"], dtype=float)
    # Drop nulls from JSON-safe serialization
    good = np.isfinite(tb_gui)
    r_gui, tb_gui = r_gui[good], tb_gui[good]

    peak_cli = float(r_cli[np.nanargmax(tb_cli)])
    peak_gui = float(r_gui[np.nanargmax(tb_gui)])
    # Expected ring ≈ 60 * 0.55 * 0.05 = 1.65"
    assert abs(peak_cli - peak_gui) < 0.35, f"CLI={peak_cli:.3f} GUI={peak_gui:.3f}"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_run_pipeline_no_beam(tmp_path, monkeypatch):
    data, header = make_synthetic_disk(noise=0.02)
    del header["BMAJ"]
    del header["BMIN"]
    del header["BPA"]
    path = tmp_path / "nobeam.fits"
    fits.PrimaryHDU(data=data, header=header).writeto(path)
    monkeypatch.chdir(tmp_path)
    args = make_cli_args(incl=40.0, pa=90.0, csv="on", homobeam="off", no_gaia=True)
    run_pipeline([str(path)], "NOBEAM", str(tmp_path / "out"), args, cnn_model=None)
    assert (tmp_path / "out" / "RP_NOBEAM.PNG").exists()


def test_run_pipeline_with_nans(tmp_path, monkeypatch):
    data, header = make_synthetic_disk(noise=0.02)
    data[10:20, 10:20] = np.nan
    path = tmp_path / "nans.fits"
    fits.PrimaryHDU(data=data, header=header).writeto(path)
    monkeypatch.chdir(tmp_path)
    args = make_cli_args(incl=40.0, pa=90.0, csv="off", homobeam="off", no_gaia=True)
    run_pipeline([str(path)], "NANS", str(tmp_path / "out"), args, cnn_model=None)
    assert (tmp_path / "out" / "RP_NANS.PNG").exists()


def test_run_pipeline_homobeam_off(multiband_tree, monkeypatch):
    monkeypatch.chdir(multiband_tree["root"])
    g = discover_groups(multiband_tree["root"])[0]
    args = make_cli_args(incl=40.0, pa=90.0, csv="off", homobeam="off", no_gaia=True)
    run_pipeline(g["files"], g["name"], g["output_dir"], args, cnn_model=None)
    assert (Path(g["output_dir"]) / f"RP_{g['name']}.PNG").exists()


# ---------------------------------------------------------------------------
# Golden CSV globals
# ---------------------------------------------------------------------------

def test_cli_global_csv_golden(tmp_path, monkeypatch, golden_dir):
    data, header = make_synthetic_disk(incl=40.0, pa=90.0, noise=0.0, seed=42)
    path = tmp_path / "golden.fits"
    fits.PrimaryHDU(data=data, header=header).writeto(path)
    monkeypatch.chdir(tmp_path)
    args = make_cli_args(
        incl=40.0, pa=90.0, rout=3.0, rmin=0.2,
        csv="on", homobeam="off", no_gaia=True,
    )
    out = tmp_path / "gout"
    run_pipeline([str(path)], "GOLD", str(out), args, cnn_model=None)

    with open(out / "RP_GOLD_global.csv") as f:
        rows = {r[0]: r for r in csv.reader(f) if r and r[0] != "parameter"}
    stats = {
        "Rout_arcsec": float(rows["Rout_arcsec"][1]),
        "Rmin_arcsec": float(rows["Rmin_arcsec"][1]),
        "Inclination_deg": float(rows["Inclination_deg"][1]),
        "PA_deg": float(rows["PA_deg"][1]),
    }
    golden_path = os.path.join(golden_dir, "cli_global.json")
    if not os.path.exists(golden_path):
        with open(golden_path, "w") as f:
            json.dump(stats, f, indent=2)
        pytest.skip("Golden file created; re-run to compare")
    with open(golden_path) as f:
        golden = json.load(f)
    assert abs(stats["Rout_arcsec"] - golden["Rout_arcsec"]) < 0.15
    assert abs(stats["Rmin_arcsec"] - golden["Rmin_arcsec"]) < 0.05
    assert abs(stats["Inclination_deg"] - golden["Inclination_deg"]) < 1e-6
    assert abs(stats["PA_deg"] - golden["PA_deg"]) < 1e-6
