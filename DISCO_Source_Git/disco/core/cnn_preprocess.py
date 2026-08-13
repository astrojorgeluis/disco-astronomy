"""Shared CNN preprocess helpers for training and inference.

Label units
-----------
* Inclination: stored as ``incl_deg / 90``.
* PA: stored as ``(sin 2θ, cos 2θ)`` with ``θ`` in radians (180° wrap).
* Center offsets ``dx``, ``dy``: FOV-normalized coordinates where the crop
  spans ``[-1, 1]`` on each axis. Network targets are ``dx / CENTER_SCALE``
  and ``dy / CENTER_SCALE`` with ``CENTER_SCALE = 0.14``.
  Convert to image pixels with :func:`fov_offset_to_pixels` using half the
  crop size in pixels (``crop_rad`` in inference).
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import zoom

IMG_SIZE = 128
CENTER_SCALE = 0.14
NUM_OUTPUTS = 5
OUTPUT_NAMES = [
    "incl/90",
    "sin2PA",
    "cos2PA",
    f"dx/{CENTER_SCALE}",
    f"dy/{CENTER_SCALE}",
]


def normalize_percentile(image, p_lo=1.0, p_hi=99.9):
    """Percentile normalize to [0, 1] as float32."""
    data = np.asarray(image, dtype=np.float64)
    lo, hi = np.percentile(data, (p_lo, p_hi))
    return np.clip((data - lo) / (hi - lo + 1e-8), 0.0, 1.0).astype(np.float32)


def resize_to_square(image, img_size=IMG_SIZE):
    """Bilinear resize to ``img_size`` × ``img_size``."""
    data = np.asarray(image, dtype=np.float64)
    if data.shape[0] == img_size and data.shape[1] == img_size:
        return data
    zoom_y = img_size / max(data.shape[0], 1)
    zoom_x = img_size / max(data.shape[1], 1)
    return zoom(data, (zoom_y, zoom_x), order=1)


def elliptical_beam_map(
    bmaj_arcsec,
    bmin_arcsec,
    bpa_deg,
    cell_arcsec,
    img_size=IMG_SIZE,
):
    """Normalized elliptical Gaussian beam map in the image pixel frame.

    ``cell_arcsec`` is the effective pixel scale of the CNN crop
    (``fov_arcsec / img_size``). BPA follows the FITS convention (degrees,
    north through east) applied in the image x/y plane.
    """
    beam = np.zeros((img_size, img_size), dtype=np.float32)
    if not (bmaj_arcsec > 0 and bmin_arcsec > 0 and cell_arcsec > 0):
        return beam

    sigma_maj = (bmaj_arcsec / cell_arcsec) / 2.355
    sigma_min = (bmin_arcsec / cell_arcsec) / 2.355
    sigma_maj = float(np.clip(sigma_maj, 0.5, img_size / 4.0))
    sigma_min = float(np.clip(sigma_min, 0.5, img_size / 4.0))

    bpa_rad = np.radians(float(bpa_deg))
    c = img_size // 2
    y_g, x_g = np.ogrid[:img_size, :img_size]
    xr = (x_g - c) * np.cos(bpa_rad) + (y_g - c) * np.sin(bpa_rad)
    yr = -(x_g - c) * np.sin(bpa_rad) + (y_g - c) * np.cos(bpa_rad)
    g = np.exp(-(xr**2 / (2 * sigma_maj**2 + 1e-8) + yr**2 / (2 * sigma_min**2 + 1e-8)))
    mx = float(g.max())
    if mx > 0:
        beam = (g / mx).astype(np.float32)
    return beam


def scale_value(bmaj_arcsec, fov_arcsec):
    """Scalar beam/FOV ratio clipped to [0, 1]."""
    return float(np.clip(bmaj_arcsec / (fov_arcsec + 1e-6), 0.0, 1.0))


def scale_map(bmaj_arcsec, fov_arcsec, img_size=IMG_SIZE):
    val = scale_value(bmaj_arcsec, fov_arcsec)
    return np.full((img_size, img_size), val, dtype=np.float32)


def encode_labels(inclination_deg, pa_deg, dx_fov=0.0, dy_fov=0.0):
    """Encode geometry labels for DiscoNet (length ``NUM_OUTPUTS``)."""
    pa_rad = np.radians(pa_deg)
    return np.array(
        [
            float(inclination_deg) / 90.0,
            float(np.sin(2.0 * pa_rad)),
            float(np.cos(2.0 * pa_rad)),
            float(dx_fov) / CENTER_SCALE,
            float(dy_fov) / CENTER_SCALE,
        ],
        dtype=np.float32,
    )


def decode_labels(predictions, crop_half_pix=None):
    """Decode network outputs to physical / FOV quantities.

    Parameters
    ----------
    predictions : array-like
        Length ≥ 3 (incl, sin2PA, cos2PA); indices 3–4 optional (dx, dy).
    crop_half_pix : float, optional
        Half-width of the inference crop in native image pixels. If given,
        also returns ``dx_pix`` / ``dy_pix``.
    """
    if hasattr(predictions, "detach"):
        predictions = predictions.detach().cpu().numpy()
    predictions = np.asarray(predictions, dtype=np.float64).ravel()

    inclination = float(np.clip(predictions[0] * 90.0, 0.0, 85.0))
    pa = float((np.degrees(np.arctan2(predictions[1], predictions[2])) / 2.0) % 180.0)

    dx_fov = float(predictions[3]) * CENTER_SCALE if predictions.size > 3 else 0.0
    dy_fov = float(predictions[4]) * CENTER_SCALE if predictions.size > 4 else 0.0

    out = dict(inclination=inclination, pa=pa, dx_fov=dx_fov, dy_fov=dy_fov)
    if crop_half_pix is not None:
        dx_pix, dy_pix = fov_offset_to_pixels(dx_fov, dy_fov, crop_half_pix)
        out["dx_pix"] = dx_pix
        out["dy_pix"] = dy_pix
    return out


def fov_offset_to_pixels(dx_fov, dy_fov, crop_half_pix):
    """Map FOV-normalized offsets (crop spans [-1, 1]) to image pixels."""
    half = float(crop_half_pix)
    return float(dx_fov) * half, float(dy_fov) * half


def stack_cnn_channels(img_norm, beam, scale):
    """Stack image / beam / scale channels → (3, H, W) float32."""
    return np.stack(
        [
            np.asarray(img_norm, dtype=np.float32),
            np.asarray(beam, dtype=np.float32),
            np.asarray(scale, dtype=np.float32),
        ],
        axis=0,
    )


def transform_beam_map(beam, flip_lr=False, flip_ud=False, rot90_k=0):
    """Apply the same geometric augmentations used on the intensity image."""
    out = np.asarray(beam, dtype=np.float32).copy()
    if flip_lr:
        out = np.fliplr(out).copy()
    if flip_ud:
        out = np.flipud(out).copy()
    if rot90_k:
        out = np.rot90(out, k=int(rot90_k) % 4).copy()
    return out


def rotate_pa_deg(pa_deg, flip_lr=False, flip_ud=False, rot90_k=0):
    """Update PA under flip / 90° rotations (180° wrap)."""
    pa = float(pa_deg) % 180.0
    if flip_lr:
        pa = (180.0 - pa) % 180.0
    if flip_ud:
        pa = (180.0 - pa) % 180.0
    if rot90_k:
        pa = (pa + 90.0 * (int(rot90_k) % 4)) % 180.0
    return pa


def transform_center_fov(dx_fov, dy_fov, flip_lr=False, flip_ud=False, rot90_k=0):
    """Transform FOV-normalized center offsets with image augmentations."""
    dx, dy = float(dx_fov), float(dy_fov)
    if flip_lr:
        dx = -dx
    if flip_ud:
        dy = -dy
    k = int(rot90_k) % 4
    for _ in range(k):
        dx, dy = -dy, dx
    return dx, dy
