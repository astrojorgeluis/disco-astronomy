.. _gui:

Graphical User Interface
========================

The DISCO GUI is a single-page web application delivered by the FastAPI
backend (``disco.server``) and rendered in any modern browser. It is
launched with:

.. code-block:: bash

   disco-start gui

The server starts on ``http://localhost:8000`` and opens a browser tab
automatically after a 1.5-second delay via a background thread.

.. tip::

   The GUI is recommended for exploratory analysis and first-time users.
   For reproducible, automated batch processing, use the CLI instead
   (see :ref:`cli`).

----

Step-by-Step Guide
------------------

A typical GUI session follows these steps:

**1. Load a FITS file**

Click the **folder icon** in the toolbar and select your ``.fits`` file.
The image will appear in the viewer and the FITS header will populate
automatically in the CATALOG panel.

**2. Adjust the disk geometry**

In the **CONTROLS** panel on the left, use the sliders to set the initial
geometric parameters:

- **Inclination** — disk inclination in degrees (0° = face-on, 90° = edge-on).
- **Position Angle** — orientation of the disk major axis in degrees.
- **Radius Out** — estimated outer disk radius in arcseconds.
- **Center X / Y** — pixel coordinates of the disk centre (auto-initialised
  to the image midpoint on load).

Activate the **Ellipse Tool** in the toolbar to display the geometry overlay
on the image. As you move the sliders, the ellipse updates live so you can
visually align it with the disk before running the pipeline.

**3. Run the pipeline**

Click **RUN PIPELINE**. DISCO computes the deprojected image,
azimuthally-averaged radial profile, cumulative flux curve, and Gaussian ring
fit for the current parameters.

**4. Auto-tune the geometry (optional)**

Click **Auto-Tune Geometry** in the ANALYSIS panel to run the optimiser
automatically. It performs a grid-search seeded Nelder-Mead minimisation of
the geometric loss and applies the best-fit inclination, position angle, and
centre — no manual tuning required. See :ref:`api-optimization` for the
full algorithm description.

**5. Explore the results**

Switch between **Deproj**, **Model**, **Residuals**, and **Polar** view tabs
to inspect different representations of the disk. Activate the **Inspector**
tool and hover over the image to probe the radial profile in real time. Drag
on the profile chart to define a fitting range for Gaussian ring analysis.

**6. Export**

Download the radial profile as CSV, save the currently displayed view as a
FITS file, or open the **Matplotlib Widget** for a publication-ready figure.
Use **Save Session** to preserve all parameters for later restoration.

----

Application Layout
------------------

The interface is implemented as a mosaic tiling system
(``react-mosaic-component``) with four resizable, re-arrangeable panels,
identified by internal window identifiers:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Panel ID
     - Content
   * - ``CONTROLS``
     - Geometry parameter controls (inclination, position angle, outer
       radius, centre pixel coordinates), active filename display, and the
       **RUN PIPELINE** button.
   * - ``VIEWER``
     - Interactive canvas viewer (``InteractiveViewer.jsx`` wrapping
       ``SimpleImageViewer.jsx``) showing the currently-loaded FITS image
       with pan, zoom, and inspector interactions.
   * - ``CATALOG``
     - FITS header keyword table (key, value, comment) and **SIMBAD** query
       button.
   * - ``ANALYSIS``
     - The ``AnalysisDashboard`` component with image view selector,
       1D radial profile chart, cumulative flux chart, statistics probe,
       and ring-fit statistics.

----

File Loading
------------

Files are loaded via two mechanisms:

1. **Direct FITS upload** — clicking the folder icon triggers a hidden
   ``<input type="file">`` element. The selected file is posted to
   ``POST /upload``. On success, ``GET /preview`` is called to retrieve
   a base64-encoded preview image, and ``GET /get_header`` retrieves the
   FITS header keywords.

2. **Session restore** — if a ``.json`` session file is selected, the stored
   parameters are restored and the referenced FITS filename is reloaded via
   ``POST /load_local``.

----

Toolbar Reference
-----------------

The toolbar provides file management and viewer interaction controls. The
active mode is highlighted with a purple background.

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Icon
     - Name
     - Description
   * - 📁
     - **Open File**
     - Opens a file picker to load a ``.fits`` image or a previously saved
       ``.json`` session file.
   * - 💾
     - **Save Session**
     - Saves current parameters (inclination, PA, radius, centre) and the
       active filename to a downloadable ``.json`` file for later
       restoration.
   * - ⛶
     - **Fullscreen**
     - Expands the viewer panel to fill the browser window.
   * - ✕
     - **Close**
     - Clears the currently loaded file and resets the interface.
   * - ◎
     - **Ellipse Tool**
     - It allows you to manipulate the shape of the ellipse. The ellipse reflects the current inclination, position angle, and outer radius in real time as you adjust the sliders and/or move the ellipse control. Use it as a visual guide before running the pipeline.
   * - 🖐
     - **Pan**
     - Switches to pan/drag mode for navigating across large images.
   * - ⊕
     - **Inspector**
     - Enables the Cursor Probe. Hovering over the image synchronises the
       crosshair position with the 1D radial profile chart and displays
       Radius, Intensity (K), and X/Y sky offsets in real time.

----

Geometry Controls (CONTROLS panel)
------------------------------------

The following parameters are exposed in the CONTROLS panel and are
transmitted to ``POST /run_pipeline`` on each pipeline execution:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Parameter
     - Description
   * - ``incl``
     - Disk inclination in degrees (slider + numeric input, range 0–90°).
   * - ``pa``
     - Position angle in degrees (slider + numeric input, range 0–180°).
   * - ``rout``
     - Outer disk radius in arcseconds (slider + numeric input, range
       0.1–10 arcsec).
   * - ``cx``, ``cy``
     - Pixel coordinates of the disk centre (numeric inputs; initialised
       to the image midpoint on load).
   * - ``fit_rmin``, ``fit_rmax``
     - Radial range boundaries for Gaussian ring fitting (set by
       drag-selection on the profile chart or image canvas).

----

Auto-Tune Geometry
------------------

The **Auto-Tune** button (implemented as ``handleAutoTune`` in ``App.jsx``)
posts the current geometry to ``POST /optimize_geometry`` and applies the
returned optimised inclination and position angle:

.. code-block:: javascript

   // App.jsx — handleAutoTune
   const response = await fetch('http://localhost:8000/optimize_geometry', {
       method: 'POST',
       body: JSON.stringify({
           cx, cy, pa, incl, rout, fit_rmin, fit_rmax
       }
   });
   const data = await response.json();
   setParams(prev => ({
       ...prev,
       incl: data.optimized_incl,
       pa:   data.optimized_pa
   }));

The optimisation is a grid-search seeded Nelder-Mead minimisation of
:func:`disco.core.optimization.geometric_loss` (see :ref:`api-optimization`).
Note that the GUI's Auto-Tune uses only the analytical grid-search path;
the CNN-seeded hybrid optimiser (``auto_tune_geometry_hybrid``) is used
exclusively by the CLI pipeline.

----

Analysis Dashboard (ANALYSIS panel)
-------------------------------------

View Modes
~~~~~~~~~~

The dashboard toolbar provides four view selectors:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Mode
     - Description
   * - ``deproj``
     - Deprojected (face-on) image computed by the pipeline.
   * - ``model``
     - Azimuthally-averaged synthetic model image.
   * - ``residuals``
     - Difference between the deprojected image and the model. Highlights
       non-axisymmetric structures such as spirals, arcs, or clumps.
   * - ``polar``
     - Image resampled into polar coordinates (radius vs azimuth).

Display Settings
~~~~~~~~~~~~~~~~

A popover panel provides the following visualisation controls, which
trigger a ``POST /render_plot`` call on change:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Control
     - Description
   * - Intensity Limits (Min/Max)
     - Manual ``vmin`` / ``vmax`` values passed to the Matplotlib normalisation.
   * - Auto button
     - Sets ``vmax_percentile: 100`` to trigger automatic percentile scaling.
   * - Colormap
     - Selected from: ``magma``, ``inferno``, ``viridis``, ``seismic``,
       ``gray``, ``jet``. Inversion toggles the ``_r`` suffix convention.
   * - Stretch
     - Selected from: ``asinh``, ``linear``, ``log``, ``sqrt``.
   * - Contours
     - Boolean toggle; number of contour levels is configurable (1–50).

1D Profile Chart
~~~~~~~~~~~~~~~~

The radial profile chart is rendered with the ``recharts`` library
(``LineChart``). The Y axis supports linear and logarithmic scaling (toggle
switch). Data points are derived from the ``profileData`` object returned
by ``POST /run_pipeline``.

**Range selection for Gaussian ring fitting** is implemented as a
click-and-drag interaction on the chart: the ``dragStart`` and ``dragEnd``
state variables track the selected radial interval, which is communicated
to the server via ``POST /run_pipeline`` through the ``fit_rmin`` /
``fit_rmax`` fields.

Cursor Probe
~~~~~~~~~~~~~

When the **Inspector** tool is active, hovering over the 2D image canvas
(``SimpleImageViewer``) synchronises the current radius to the 1D chart
via the ``syncedRadius`` state variable. The probe widget displays:

* **RADIUS** — current radial position in arcseconds
* **INTENSITY** — brightness temperature at the closest profile sample, in K
* **OFFSET X**, **OFFSET Y** — :math:`r / \sqrt{2}` in arcseconds

Ring Fit Statistics
~~~~~~~~~~~~~~~~~~~

If a fit range is active (``fit_rmin < fit_rmax``), the pipeline fits a
Gaussian to the radial profile within the selected interval using
``scipy.optimize.curve_fit`` with the model:

.. math::

   G(r) = a \exp\!\left(-\frac{(r - r_0)^2}{2\sigma^2}\right) + c

The returned ``fit`` object exposes:

* **PEAK RADIUS** :math:`r_0` — centroid of the fitted Gaussian, in arcsec
* **WIDTH (FWHM)** — :math:`2\sqrt{2 \ln 2}\,\sigma`, in arcsec

Cumulative Flux Chart
~~~~~~~~~~~~~~~~~~~~~

The cumulative enclosed flux is computed client-side as:

.. math::

   F_{\rm enc}(R) = \frac{\sum_{r \le R} I(r) \cdot r}{\sum_{\rm all} I(r) \cdot r} \times 100\%

and displayed as an ``AreaChart``.

Custom Markers
~~~~~~~~~~~~~~

The **Add Marker** function enters marker-placement mode on the image canvas.
On click, a dialog prompts for a label, shape (``circle``, ``square``,
``star``, ``cross``), and colour. Markers are rendered as Konva.js overlay
shapes and are persistent within the session. Markers can be cleared per
view mode.

----

Export Functions
----------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Function
     - Behaviour
   * - **Download FITS**
     - Calls ``GET /download_fits?type=<view_type>`` which returns the
       corresponding data array as a binary FITS file carrying the original
       header from the loaded FITS file.
   * - **CSV Export**
     - Client-side function (``handleDownloadCSV``) serialises
       ``profileData.radius``, ``profileData.raw_intensity``, and
       ``profileData.intensity`` (brightness temperature) into a CSV blob
       and triggers a browser download of ``radial_profile.csv``.
   * - **Session Save**
     - Serialises ``{filename, params, timestamp, pixelScale}`` as a JSON
       file downloadable as ``session_<stem>.json``.
   * - **Matplotlib Widget**
     - Opens a secondary browser panel (``MatplotlibWidget.jsx``) that
       calls ``POST /render_plot`` with higher DPI (default 150) and
       configurable axes, colourbar, and beam overlay options.

----

SIMBAD Query
------------

The **SIMBAD** button (in the CATALOG panel) triggers ``GET /query_simbad``.
The server reads the WCS from the loaded FITS header, converts the image
centre pixel to sky coordinates, and queries CDS SIMBAD within a 2 arcmin
radius, requesting the ``otype``, ``flux(V)``, and ``distance`` VOTable
fields. The result is returned as a list of JSON objects and displayed in a
popup table.

This functionality requires ``astroquery`` to be installed. If the library
is absent, the endpoint returns HTTP 501.
