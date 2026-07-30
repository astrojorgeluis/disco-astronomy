"""Backward-compatible re-exports from the split core modules. """
import matplotlib

# Optional debug helper kept for CLI --debug
import numpy as np

from disco.core.beams import (  # noqa: F401
    deconvolve_beams,
    get_alma_beam,
    make_gaussian_kernel_casa,
)
from disco.core.fits_io import (  # noqa: F401
    _ASTROQUERY_AVAILABLE,
    apply_proper_motion_correction,
    auto_detect_parameters,
    deg_to_sex,
    find_center_robust,
    get_obs_epoch,
    icrs_to_pixel,
    pixel_to_icrs,
    query_gaia_proper_motion,
    refine_center_local,
)
from disco.core.profiles import (  # noqa: F401
    extract_profile,
    measure_rout_deproj,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import map_coordinates


def save_debug_deproj_center(image, cx, cy, incl, pa, rout_arcsec, pixel_scale, out_png, title):
    dim = 500
    x = np.arange(dim) - dim / 2.0
    X, Y = np.meshgrid(x, x)
    Xc = X * np.cos(np.radians(incl))
    Xrot = np.cos(np.radians(pa)) * Xc + np.sin(np.radians(pa)) * Y
    Yrot = -np.sin(np.radians(pa)) * Xc + np.cos(np.radians(pa)) * Y
    crop_rad = int((rout_arcsec / pixel_scale) * 1.5) + 15
    crop_rad = min(crop_rad, image.shape[0] // 2, image.shape[1] // 2)
    scale = (crop_rad * 2) / dim
    coords = [Yrot * scale + cy, -Xrot * scale + cx]
    deproj = map_coordinates(image, coords, order=1, mode="constant", cval=0.0)
    fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
    vmin, vmax = np.percentile(deproj, [2, 99.5]) if deproj.size > 0 else (np.min(deproj), np.max(deproj))
    ax.imshow(deproj, origin="lower", cmap="inferno", vmin=vmin, vmax=vmax)
    center_x, center_y = (dim - 1) / 2.0, (dim - 1) / 2.0
    ax.scatter([center_x], [center_y], c="white", s=60, marker="x", linewidths=1.5)
    r_pix = (rout_arcsec / pixel_scale) / scale
    circ = plt.Circle((center_x, center_y), r_pix, fill=False, ec="cyan", lw=1.8, ls="--")
    ax.add_patch(circ)
    ax.set_title(title)
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
