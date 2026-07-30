"""Matplotlib rendering helpers (publication figures only)."""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.visualization import AsinhStretch, ImageNormalize, LinearStretch, LogStretch, SqrtStretch
from matplotlib.patches import Ellipse
from matplotlib.ticker import FixedLocator


def array_to_base64(data_array, cmap="magma", stretch_val=0.03):
    mx = np.nanmax(data_array)
    if np.isnan(mx) or mx <= 0:
        mx = 1.0
    norm = ImageNormalize(vmin=0.0, vmax=mx, stretch=AsinhStretch(stretch_val))
    fig = plt.figure(figsize=(6, 6), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.imshow(data_array, origin="lower", cmap=cmap, norm=norm, interpolation="nearest", aspect="equal")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _stretch(name, vmin, vmax):
    if name == "log":
        return ImageNormalize(vmin=vmin, vmax=vmax, stretch=LogStretch())
    if name == "linear":
        return ImageNormalize(vmin=vmin, vmax=vmax, stretch=LinearStretch())
    if name == "sqrt":
        return ImageNormalize(vmin=vmin, vmax=vmax, stretch=SqrtStretch())
    return ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.02))


def render_scientific_plot(img_entry, params) -> dict:
    plt.style.use("default")
    if params.type in ("polar", "profile"):
        fig = plt.figure(figsize=(12, 5), dpi=params.dpi)
    else:
        fig = plt.figure(figsize=(10, 10), dpi=params.dpi)

    if params.type == "profile":
        if img_entry.profile_data is None:
            plt.close(fig)
            raise ValueError("Profile data not available.")
        ax = fig.add_subplot(111)
        ax.set_facecolor("white")
        x = np.array(img_entry.profile_data["radius"])
        y = np.array(img_entry.profile_data.get("tb") or img_entry.profile_data.get("intensity"))
        safe_y = np.where((y > 0) & np.isfinite(y), y, 1e-10)
        ax.plot(x, safe_y, "k", lw=1.5)
        ax.set_yscale("log")
        vmin = params.vmin if params.vmin is not None else float(np.min(safe_y))
        vmax = params.vmax if params.vmax is not None else float(np.max(safe_y))
        ax.set_xlim(0, x[-1] if len(x) else 1)
        ax.set_ylim(vmin, vmax)
        ax.set_xlabel("Radius [arcsec]", fontsize=12)
        ax.set_ylabel("Tb [K]", fontsize=12)
        ax.tick_params(direction="in", labelsize=10)
        if params.show_grid:
            ax.grid(True, which="both", color="gray", alpha=0.3, linestyle="--")
        ax.set_title(params.title or "Radial Profile", fontweight="bold", fontsize=14)
        fmt = params.format if params.format in ("png", "pdf", "svg") else "png"
        buf = io.BytesIO()
        plt.savefig(buf, format=fmt, bbox_inches="tight", pad_inches=0.1, facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return {
            "image": f"data:image/{fmt};base64,{base64.b64encode(buf.read()).decode('utf-8')}",
            "format": fmt,
            "stats": {"min": float(np.min(safe_y)), "max": float(np.max(safe_y)), "vmin_used": float(vmin), "vmax_used": float(vmax), "cmap_used": params.cmap},
        }

    if img_entry.results and params.type in img_entry.results:
        image_data = img_entry.results[params.type]
    elif params.type == "data":
        image_data = img_entry.data
    else:
        plt.close(fig)
        raise ValueError(f"Data for '{params.type}' not available.")

    if params.show_axes:
        ax = fig.add_subplot(111)
        ax.set_facecolor("white")
    else:
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")

    vmin = params.vmin
    vmax = params.vmax
    if vmin is None:
        if params.type == "residuals":
            limit = np.percentile(np.abs(image_data), 99.5 if params.vmax_percentile is None else params.vmax_percentile)
            vmin = -limit
            vmax = limit if vmax is None else vmax
        else:
            vmin = 0.0
    if vmax is None:
        pct = 99.5 if params.vmax_percentile is None else float(params.vmax_percentile)
        pct = min(max(pct, 50.0), 100.0)
        if params.type != "residuals":
            vmax = float(np.percentile(image_data, pct))
    if vmax <= vmin:
        vmax = vmin + 1e-10

    norm = _stretch(params.stretch, vmin, vmax)
    aspect = "auto" if params.type == "polar" else "equal"
    extent = img_entry.extents.get(params.type) if img_entry.extents else None
    im = ax.imshow(image_data, origin="lower", cmap=params.cmap, norm=norm, aspect=aspect, extent=extent)

    if params.show_axes:
        titles = {"data": "Input Data", "deproj": "Deprojected View", "polar": "Polar Map", "model": "Azimuthal Model", "residuals": "Residual Map"}
        ax.set_title(params.title or titles.get(params.type, params.type.capitalize()), fontweight="bold", fontsize=14)
        ax.tick_params(direction="in", labelsize=10, color="black")
        if params.type == "polar":
            ax.set_xlabel("Radius [arcsec]", fontsize=12)
            ax.set_ylabel("Azimuth [deg]", fontsize=12)
        else:
            ax.set_xlabel("RA Offset [arcsec]", fontsize=12)
            ax.set_ylabel("Dec Offset [arcsec]", fontsize=12)
        if params.show_grid:
            ax.grid(True, color="white", alpha=0.3, linestyle="--")
        if params.show_colorbar:
            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            if vmax <= 10 and params.stretch == "asinh":
                cbar.locator = FixedLocator([0.0, 0.2, 0.5, 1.0, 2.0, 4.0])
                cbar.update_ticks()
            cbar.set_label("Intensity", fontsize=10)

    if params.contours:
        try:
            ax.contour(image_data, levels=params.contour_levels, colors="white", alpha=0.5, linewidths=0.8, extent=extent)
        except Exception:
            pass

    if params.show_beam and params.type != "polar" and params.show_axes and "BMAJ" in img_entry.header:
        try:
            bmaj = img_entry.header["BMAJ"] * 3600
            bmin = img_entry.header["BMIN"] * 3600
            bpa = img_entry.header.get("BPA", 0.0)
            if extent:
                width_phys = abs(extent[1] - extent[0])
                height_phys = abs(extent[3] - extent[2])
                bx = extent[0] + width_phys * 0.1
                by = extent[2] + height_phys * 0.1
                ax.add_patch(Ellipse((bx, by), width=bmin, height=bmaj, angle=bpa, facecolor="white", edgecolor="black", zorder=20))
        except Exception:
            pass

    fmt = params.format if params.format in ("png", "pdf", "svg") else "png"
    buf = io.BytesIO()
    is_transparent = not params.show_axes
    plt.savefig(buf, format=fmt, bbox_inches="tight", pad_inches=0.1 if params.show_axes else 0, transparent=is_transparent, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    mime = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml"}[fmt]
    return {
        "image": f"data:{mime};base64,{base64.b64encode(buf.read()).decode('utf-8')}",
        "format": fmt,
        "stats": {
            "min": float(np.min(image_data)),
            "max": float(np.max(image_data)),
            "vmin_used": float(vmin),
            "vmax_used": float(vmax),
            "cmap_used": params.cmap,
        },
    }


def render_multi_panel(img_entry, panels, ncols=2, dpi=150, fmt="png", title=""):
    n = max(len(panels), 1)
    nrows = int(np.ceil(n / max(ncols, 1)))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 5 * nrows), dpi=dpi)
    axes = np.atleast_1d(axes).ravel()
    for i, ax in enumerate(axes):
        if i >= n:
            ax.axis("off")
            continue
        p = panels[i]
        if p.type == "profile":
            if not img_entry.profile_data:
                ax.set_title("No profile")
                continue
            x = np.array(img_entry.profile_data["radius"])
            y = np.array(img_entry.profile_data.get("tb") or img_entry.profile_data.get("intensity"))
            safe = np.where((y > 0) & np.isfinite(y), y, 1e-10)
            ax.plot(x, safe, "k", lw=1.2)
            ax.set_yscale("log")
            ax.set_xlabel("R [arcsec]")
            ax.set_ylabel("Tb [K]")
            ax.set_title(p.title or "Profile")
            continue
        if p.type in img_entry.results:
            data = img_entry.results[p.type]
        elif p.type == "data":
            data = img_entry.data
        else:
            ax.set_title(f"Missing {p.type}")
            continue
        vmin = 0.0 if p.vmin is None else p.vmin
        vmax = float(np.percentile(data, 99.5)) if p.vmax is None else p.vmax
        if p.type == "residuals":
            lim = float(np.percentile(np.abs(data), 99.5))
            vmin, vmax = -lim, lim
        norm = _stretch(p.stretch, vmin, vmax)
        extent = img_entry.extents.get(p.type) if img_entry.extents else None
        im = ax.imshow(data, origin="lower", cmap=p.cmap, norm=norm, extent=extent, aspect="equal" if p.type != "polar" else "auto")
        ax.set_title(p.title or p.type)
        if p.show_colorbar:
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        if not p.show_axes:
            ax.axis("off")
    if title:
        fig.suptitle(title, fontweight="bold")
    fig.tight_layout()
    buf = io.BytesIO()
    fmt = fmt if fmt in ("png", "pdf", "svg") else "png"
    plt.savefig(buf, format=fmt, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    mime = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml"}[fmt]
    return {"image": f"data:{mime};base64,{base64.b64encode(buf.read()).decode('utf-8')}", "format": fmt}
