.. _api-server:

``disco.server`` — HTTP API Reference
======================================

.. module:: disco.server
   :synopsis: FastAPI backend for the DISCO GUI.

The GUI backend is implemented as a FastAPI application (``app``) served by
Uvicorn on ``http://0.0.0.0:8000``. The application maintains a single
in-memory session via the module-level singleton ``state`` (an instance of
``GlobalState``). All state is cleared on startup and on server shutdown.

CORS is enabled for all origins (``allow_origins=["*"]``) to permit
access from the bundled React application.

----

Global State
------------

The ``GlobalState`` class holds the current session data:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Attribute
     - Description
   * - ``data``
     - ``numpy.ndarray | None`` — the currently-loaded 2D FITS image.
   * - ``header``
     - FITS header object, or ``None``.
   * - ``filename``
     - Resolved file path of the loaded FITS file, or ``None``.
   * - ``results``
     - ``dict`` — pipeline output images keyed by type
       (``"deproj"``, ``"model"``, ``"residuals"``, ``"polar"``).
   * - ``extents``
     - ``dict`` — Matplotlib ``extent`` (physical axis limits) for each
       image type, used for correct axis labelling.
   * - ``profile_data``
     - ``dict | None`` — radial profile data with keys ``"radius"`` and
       ``"tb"`` (brightness temperature profile).

----

Pydantic Request Models
-----------------------

.. class:: PlotParams

   Request body for ``POST /render_plot``.

   :param str type: Image type to render. One of:
                    ``"data"``, ``"deproj"``, ``"model"``, ``"residuals"``,
                    ``"polar"``, ``"profile"``.
   :param str cmap: Matplotlib colormap name. Default: ``"magma"``.
   :param str stretch: Intensity stretch. One of: ``"asinh"`` (default),
                       ``"log"``, ``"linear"``, ``"sqrt"``.
   :param float | None vmax_percentile: If set, the vmax is computed as
                                         this percentile of the image data.
   :param float | None vmin: Manual lower intensity limit.
   :param float | None vmax: Manual upper intensity limit.
   :param bool contours: Overlay contours. Default: ``False``.
   :param int contour_levels: Number of contour levels. Default: 5.
   :param bool show_beam: Overlay beam ellipse. Default: ``False``.
   :param bool show_grid: Overlay grid lines. Default: ``False``.
   :param bool show_axes: Show axes and labels. Default: ``True``.
   :param bool show_colorbar: Show colorbar. Default: ``True``.
   :param str | None title: Optional plot title.
   :param int dpi: Figure DPI. Default: 150.

.. class:: PipelineParams

   Request body for ``POST /run_pipeline``.

   :param float cx: Disk centre x-coordinate in pixels.
   :param float cy: Disk centre y-coordinate in pixels (GUI convention:
                    measured from the top of the image).
   :param float pa: Position angle in degrees.
   :param float incl: Inclination in degrees.
   :param float rout: Outer disk radius in arcseconds.
   :param float fit_rmin: Inner radius for Gaussian ring fitting. Default: 0.0.
   :param float fit_rmax: Outer radius for Gaussian ring fitting. Default: 0.0.

.. class:: OptimizeParams

   Request body for ``POST /optimize_geometry``.

   :param float cx: Centre x in pixels.
   :param float cy: Centre y in pixels.
   :param float pa: Current position angle in degrees.
   :param float incl: Current inclination in degrees.
   :param float rout: Outer radius in arcseconds.
   :param float fit_rmin: Inner fitting radius in arcseconds. Default: 0.0.
   :param float fit_rmax: Outer fitting radius in arcseconds. Default: 0.0.

.. class:: LoadLocalParams

   Request body for ``POST /load_local``.

   :param str filename: Base filename (not a full path) to load from
                         the upload directory ``.disco_uploads/``.

----

Endpoints
---------

Session Management
~~~~~~~~~~~~~~~~~~

.. http:post:: /reset_session

   Clears all session state (``GlobalState`` fields reset to ``None`` /
   empty) and deletes all files in the ``.disco_uploads/`` directory.

   :status 200: ``{"status": "Session cleared"}``

File Loading
~~~~~~~~~~~~

.. http:post:: /upload

   Accept a multipart FITS file upload, save it to ``.disco_uploads/``,
   load the primary HDU into ``state.data`` and ``state.header``, and
   return basic image metadata.

   If the data maximum is below 0.1, the array is multiplied by 1 000
   (Jy/beam → mJy/beam normalisation).

   **Form field:** ``file`` — the FITS file.

   :status 200: JSON object with keys:
                ``filename`` (str), ``status`` (``"loaded"``),
                ``shape`` (list[int, int]),
                ``pixel_scale`` (float, arcsec/pixel).
   :status 500: On any read or FITS parse error.

.. http:post:: /load_local

   Load a previously-uploaded FITS file from ``.disco_uploads/`` by
   base filename. Applies the same unit normalisation as ``/upload``.

   **Request body:** :class:`LoadLocalParams`

   :status 200: JSON object with keys:
                ``status`` (``"loaded"``), ``filename`` (str),
                ``shape`` (list[int, int]),
                ``pixel_scale`` (float).
   :status 404: If the file does not exist in the upload directory.
   :status 500: On parse error.

.. http:get:: /preview

   Return a base64-encoded PNG preview of the currently-loaded image,
   rendered with the ``inferno`` colormap and an ``AsinhStretch``
   normalisation (``stretch_val=0.02``).

   :status 200: ``{"image": "data:image/png;base64,<...>"}``
   :status 404: If no data is loaded.

.. http:get:: /get_header

   Return the FITS header as a list of keyword–value–comment triples,
   excluding ``COMMENT`` and ``HISTORY`` records.

   :status 200: ``{"header": [{"key": str, "value": str, "comment": str}, ...]}``
                Returns an empty list if no header is loaded.

Pipeline and Optimisation
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. http:post:: /run_pipeline

   Execute the deprojection pipeline on the currently-loaded image with the
   supplied geometry, and store the results in ``state.results``.

   **Procedure:**

   1. Convert GUI pixel-y to image-y convention.
   2. Generate the deprojected image by applying the inclination and PA
      transform on a :math:`1000 \times 1000` grid using
      ``scipy.ndimage.map_coordinates`` (order 3).
   3. Compute the polar map (radius vs azimuth, 361 × 500 pixels).
   4. Build the azimuthal model (mean profile tiled over the polar grid,
      then reprojected to Cartesian).
   5. Compute the residual map (deprojected − model).
   6. Extract the azimuthally-averaged profile via
      :func:`disco.core.fits_utils.extract_profile`.
   7. If ``fit_rmin < fit_rmax``, fit a Gaussian to the profile segment
      using ``scipy.optimize.curve_fit`` with the model
      :math:`G(r) = a\exp(-(r-r_0)^2/(2\sigma^2)) + c`.
   8. Read beam geometry from the header and construct a beam info dict.
   9. Store all results in ``state``.

   **Request body:** :class:`PipelineParams`

   :status 200: JSON object with the following structure:

   .. code-block:: text

      {
        "images": {
          "deproj":    "data:image/png;base64,...",
          "polar":     "data:image/png;base64,...",
          "model":     "data:image/png;base64,...",
          "residuals": "data:image/png;base64,..."
        },
        "profile": {
          "radius":        [...],
          "intensity":     [...],
          "raw_intensity": [...]
        },
        "geometry": {
          "fov_cartesian": <float>,
          "fov_polar":     <float>,
          "beam":          {"major": <float>, "minor": <float>, "pa": <float>},
          "pixel_scale":   <float>
        },
        "fit": {
          "peak_radius": <float>,
          "fwhm":        <float>
        }
      }

   The ``fit`` key is ``null`` if no fit range is specified or fitting fails.

   :status 400: If no data is loaded.
   :status 500: On internal error.

.. http:post:: /optimize_geometry

   Run a grid-seeded Nelder-Mead optimisation of
   :func:`disco.core.optimization.geometric_loss` to refine inclination and
   position angle.

   **Procedure:**

   1. Convert GUI coordinates to image-space.
   2. Apply zero-padding (1000 pixels) and crop around the centre.
   3. Evaluate the loss at a grid of :math:`(i, \phi)` candidates:
      ``test_incls = [10, 30, 50, 70]`` degrees,
      ``test_pas   = range(0, 180, 30)`` degrees.
   4. Run Nelder-Mead (bounds ``[0,85] × [0,180] × [-10,10]²``, ``dim=400``,
      ``order=3``) starting from the best grid point.

   **Request body:** :class:`OptimizeParams`

   :status 200:

   .. code-block:: text

      {
        "optimized_incl": <float>,
        "optimized_pa":   <float>
      }

   :status 400: If no data is loaded.

Rendering
~~~~~~~~~

.. http:post:: /render_plot

   Render a Matplotlib figure of the requested image type and return it as a
   base64-encoded PNG.

   For 2D image types (``"data"``, ``"deproj"``, ``"model"``,
   ``"residuals"``, ``"polar"``):

   * Intensity normalisation uses the selected stretch function
     (``AsinhStretch``, ``LogStretch``, ``LinearStretch``, or
     ``SqrtStretch``).
   * If ``show_axes`` is ``True``, axis labels, title, and optionally a
     colorbar and grid are rendered.
   * If ``show_beam`` is ``True`` and ``BMAJ``/``BMIN`` are present in the
     header, a beam ellipse is overlaid in the lower-left region.
   * If ``contours`` is ``True``, ``ax.contour`` is called with
     ``contour_levels`` levels.

   For ``"profile"`` type:

   * A log-scale 1D plot of the brightness temperature profile is generated.

   **Request body:** :class:`PlotParams`

   :status 200:

   .. code-block:: text

      {
        "image": "data:image/png;base64,...",
        "stats": {
          "min": <float>,
          "max": <float>,
          "vmin_used": <float>,
          "vmax_used": <float>,
          "cmap_used": <str>
        }
      }

   :status 400: If data for the requested type is not available.

Download and Metadata
~~~~~~~~~~~~~~~~~~~~~

.. http:get:: /download_fits

   Return a pipeline output array as a binary FITS file, preserving the
   original FITS header.

   **Query parameter:** ``type`` — one of ``"data"``, ``"deproj"``,
   ``"model"``, ``"residuals"``, ``"polar"``.

   :status 200: Binary FITS file with
                ``Content-Disposition: attachment; filename=result_<type>.fits``
   :status 400: If the requested data type is not available.

.. http:get:: /query_simbad

   Query CDS SIMBAD for objects within 2 arcmin of the loaded FITS image
   centre. Reads the WCS from the header to compute the sky position.

   Requests the following VOTable fields: ``otype``, ``flux(V)``,
   ``distance``.

   Requires ``astroquery`` to be installed.

   :status 200: ``{"found": true, "data": [...]}`` — list of row objects
                with all returned SIMBAD columns, or
                ``{"found": false, "data": []}`` if no sources are found.
   :status 400: If no header is loaded.
   :status 501: If ``astroquery`` is not installed.
   :status 500: On SIMBAD query error.

Static File Serving
~~~~~~~~~~~~~~~~~~~

.. http:get:: /assets/<path>

   Serves static assets from ``disco/static/assets/`` (Vite build output).

.. http:get:: /{full_path}

   Catch-all route. If the path resolves to an existing file in
   ``disco/static/``, serves it directly; otherwise serves
   ``disco/static/index.html`` (enabling React client-side routing).

   All responses include ``Cache-Control: no-cache`` headers to prevent
   stale asset delivery.

----

Server Lifecycle
----------------

.. function:: start_server()

   Called by :func:`disco.main.run` when ``gui`` is the first argument.
   Prints the server address to stdout, starts a background thread that
   opens the default browser at ``http://localhost:8000`` after a 1.5-second
   delay, and starts Uvicorn:

   .. code-block:: python

      uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

   On shutdown, the ``@app.on_event("shutdown")`` handler calls
   ``wipe_session_logic()`` to clean up the upload directory and reset
   session state.
