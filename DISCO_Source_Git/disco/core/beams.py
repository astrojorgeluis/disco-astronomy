"""Beam convolution / deconvolution helpers."""
from __future__ import annotations

import numpy as np


def get_alma_beam(sigma_maj, sigma_min, bpa_rad, size=15):
    x = np.arange(-size, size + 1)
    X, Y = np.meshgrid(x, x)
    Xrot = X * np.cos(bpa_rad) + Y * np.sin(bpa_rad)
    Yrot = -X * np.sin(bpa_rad) + Y * np.cos(bpa_rad)
    kernel = np.exp(-(Xrot ** 2 / (2 * sigma_maj ** 2) + Yrot ** 2 / (2 * sigma_min ** 2)))
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
        S = np.array([[sig_maj ** 2, 0], [0, sig_min ** 2]])
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
    kernel = np.exp(-(Xrot ** 2 / (2 * sigma_maj ** 2) + Yrot ** 2 / (2 * sigma_min ** 2)))
    return kernel / np.sum(kernel)
