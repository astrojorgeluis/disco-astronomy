> **WORK IN PROGRESS (WIP)**
> This software is currently in early active development. Features and documentation are being updated frequently.

# DISCO
### Deprojection Image Software for Circumstellar Objects

> A hybrid pipeline for the analysis and physical characterization of protoplanetary disks from ALMA FITS data.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-CNN-EE4C2C?style=flat&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-Frontend-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/badge/PyPI-disco--astronomy-blue?style=flat&logo=pypi&logoColor=white)](https://pypi.org/project/disco-astronomy/)

---

## Overview

DISCO is an open-source tool for the interactive and automated analysis of protoplanetary disk observations. It combines a convolutional neural network (**DiscoNet**) for rapid geometric parameter prediction with a hybrid optimization strategy, enabling robust deprojection and radial profile extraction from FITS images.

It bridges scientific Python libraries with a modern web interface, offering two complementary modes of operation: a **CLI pipeline** for batch processing and a **GUI** for interactive exploration.

> **Citation:** If you use DISCO in published work, please cite this repository and acknowledge **Jorge Luis Guzmán-Lazo**, who developed the software within the [YEMS Millennium Nucleus](https://www.milenioyems.cl/) under the supervision of **Sebastián Pérez Marquez** and **Camilo Gonzalez-Ruilova**.

---

## Key Features

- **DiscoNet (CNN)** — Convolutional neural network that predicts disk geometric parameters (inclination, position angle, outer/inner radius) directly from FITS images.
- **Hybrid Optimization (CLI)** — Combines CNN predictions with fine-grained numerical refinement for physically consistent results.
- **Dual Visualization** — Real-time rendering of deprojected images in both Cartesian and polar projections.
- **Batch Processing (CLI)** — Automated pipeline supporting multiple targets and FITS files in a single run.
- **Beam Homogenization (CLI)** — Convolves images to a target resolution for multi-epoch or multi-band consistency.
- **SIMBAD Metadata** — A- **Gaia Integration (CLI)** — Corrects for proper motion of the target system using Gaia DR3 astrometry.
utomatically queries object metadata (distance, spectral type) via the CDS SIMBAD service.
- **CSV Export** — Outputs radial profiles and fitted parameters in tabular format.

---

## Two Modes of Operation

| Feature | CLI Pipeline (`disco-start`) | GUI (`disco-start gui`) |
|---|---|---|
| DiscoNet (CNN) | ✅ | ❌ |
| Interactive visualization | ❌ | ✅ |
| Batch processing | ✅ | ❌ |
| Multi-band support | ✅ | ❌ |
| Beam degradation | ✅ | ❌ |
| Ease of use | Moderate | High |

The **GUI mode** is recommended for exploratory analysis and users new to disk deprojection. The **CLI mode** is designed for reproducible, automated pipelines.

---

## Installation

> **Recommended:** Use a dedicated virtual environment to avoid dependency conflicts.

```bash
# Create and activate a virtual environment
python -m venv disco-env
source disco-env/bin/activate      # Linux / macOS
disco-env\Scripts\activate         # Windows

# Install DISCO
pip install disco-astronomy

# Hint: Remember to update the package using
pip install --upgrade disco-astronomy
```

📦 Package on PyPI: [pypi.org/project/disco-astronomy](https://pypi.org/project/disco-astronomy/)

---

## Quick Start

### Interactive GUI

Launch the web interface for interactive, user-friendly analysis:

```bash
disco-start gui
```

This opens a local server with a React-based UI for loading FITS files, adjusting parameters visually, and inspecting radial profiles in real time.

![GUI Screenshot](https://raw.githubusercontent.com/astrojorgeluis/disco-astronomy/main/DISCO_Source_Git/assets/gui_screenshot.png)

**View Modes**
Toggle between different visualization states of the disk:
* **Deproj:** The deprojected (face-on) image based on current geometric parameters.
* **Model:** The synthetic symmetrical model.
* **Residuals:** The remaining flux after subtracting the model from the deprojected image, useful for spotting spirals or localized asymmetries.
* **Polar:** The image mapped into polar coordinates (Radius vs. Azimuth).

![GUI Screenshot Tools](https://raw.githubusercontent.com/astrojorgeluis/disco-astronomy/main/DISCO_Source_Git/assets/gui_screenshot_tools.png)

**Interactive Analysis Tools**
* **Auto-Tune Geometry:** A one-click execution that runs the mathematical optimization in the background to automatically predict and apply the optimal center offset, inclination, and position angle.
* **Cursor Probe (Inspector):** Hovering over the 2D image perfectly syncs with the 1D charts, showing you the exact Radius, Intensity (in Kelvin), and X/Y offsets.
* **Fit Range Selection:** Click and drag directly on the chart to select a specific radial range for Gaussian ring fitting. The stats widget will automatically update with the **Peak Radius** and **FWHM**.
* **Custom Markers:** Pinpoint specific morphological features. Click "Add Marker" to place customized annotations (shapes, colors, and labels) directly onto the FITS image.

**Real-Time Charts (1D Plots)**
* **Radial Profile:** Displays Intensity vs. Radius. Supports toggling between Linear and Logarithmic scales. 
* **Cumulative Flux:** An area chart showing the enclosed flux percentage as a function of radius.

**Display Configuration**
* **Colormaps & Stretch:** Change colormaps (`magma`, `inferno`, `viridis`, etc.) and stretch functions (`asinh`, `linear`, `log`, `sqrt`) on the fly.
* **Intensity Limits:** Manually set `Vmin`/`Vmax` values or use the Auto-percentile button to enhance faint disk structures.
* **Overlays:** Toggle axes, colorbars, and adjustable intensity contours.

**Export & Integration**
* **Download FITS:** Save the currently viewed state (e.g., the residual map) as a standard `.fits` file.
* **CSV Export:** Download the precise 1D radial profile data points (Radius, Intensity, Brightness Temperature) directly to your machine.
* **Matplotlib Widget:** Pop out the current view into an interactive, native Matplotlib window for publication-ready plotting.
---


### Automated CLI Pipeline

For batch processing of one or more targets:

```bash
# Process a single object by identifier
disco-start AS209

# Process a group of object by identifier
disco-start path/to/group/

# Process multiple objects in separate
disco-start AS209 Elias29 DoAr25

# Process a FITS file directly
disco-start path/to/disk.fits

# Force geometric parameters and export CSV
disco-start AS209 --incl 35.0 --pa 120.0 --csv on
```

---

## CLI Reference

```
usage: disco-start [-h] [--rout ROUT] [--rmin RMIN] [--incl INCL] [--pa PA]
                   [--beam BEAM] [--homobeam {on,off}] [--csv {on,off}]
                   [--debug {on,off}] [identifier ...]
```

| Argument | Description |
|---|---|
| `identifier` | Object prefix(es) or path(s) to FITS file(s) |
| `--rout ROUT` | Force outer radius (arcsec) |
| `--rmin RMIN` | Force inner radius (arcsec) |
| `--incl INCL` | Force disk inclination (degrees) |
| `--pa PA` | Force position angle (degrees) |
| `--beam BEAM` | Force target beam resolution (arcsec) |
| `--homobeam {on,off}` | Enable/disable beam homogenization |
| `--csv {on,off}` | Export radial profile as CSV |
| `--debug {on,off}` | Save debug deprojected image |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Astropy, SciPy, NumPy |
| Deep Learning | PyTorch (DiscoNet CNN) |
| Frontend | React, Vite, BlueprintJS |
| Distribution | PyPI (`disco-astronomy`) |

---

## License

This project is licensed under the [MIT License](https://opensource.org/licenses/MIT).

---

## Support & Contact

If you encounter issues or have questions, feel free to reach out:

📬 **jorge.guzman.l@usach.cl**

Bug reports and contributions via [GitHub Issues](https://github.com/astrojorgeluis/disco-astronomy) are also welcome.
