.. _file-io:

File Input and Output
=====================

FITS Input
----------

DISCO accepts standard FITS files conforming to the ALMA imaging output
convention. The following header keywords are read and utilised:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Keyword
     - Usage
   * - ``CDELT2``
     - Pixel scale in degrees per pixel. The absolute value is multiplied
       by 3600 to yield arcseconds per pixel.
   * - ``BUNIT``
     - Flux density units. If ``"JY/BEAM"``, the data are multiplied by
       1 000 to convert to mJy/beam.
   * - ``BMAJ``, ``BMIN``
     - Synthesised beam major and minor axes in degrees. Used for beam
       area computation, SNR scoring, inner radius estimation, beam
       homogenisation, and brightness temperature conversion.
   * - ``BPA``
     - Beam position angle in degrees. Used for beam kernel construction.
   * - ``RESTFRQ``
     - Rest frequency in Hz. Used for brightness temperature conversion.
       Fallback: searches ``CRVAL3``/``CRVAL4`` for a frequency axis; if
       absent, assumes 230 GHz.
   * - ``DATE-OBS``
     - ISO-T observation date string. Used for Gaia proper-motion epoch.
   * - ``MJD-OBS``
     - Modified Julian Date of observation. Fallback for ``DATE-OBS``.
   * - ``NAXIS1``, ``NAXIS2``
     - Image dimensions in pixels.
   * - WCS keywords (``CTYPE1/2``, ``CRPIX1/2``, ``CRVAL1/2``, etc.)
     - Used for pixel ↔ ICRS coordinate transformations.

Multi-dimensional FITS cubes (e.g. with Stokes and frequency axes) are
handled by ``numpy.squeeze``, which collapses all degenerate axes to
produce a 2D image.

.. _file-io-cli:

CLI Output Files
----------------

The CLI pipeline writes the following files to ``<output_dir>/`` for each
processed group. All paths are relative to the group output directory.

Radial Profile Plot
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Filename
     - Description
   * - ``RP_<group_name>.PNG``
     - Matplotlib figure (dpi=150, white background) showing normalised
       radial profiles for all images in the group, with the optimised
       geometry annotated in the title (inclination ± uncertainty,
       PA ± uncertainty). One line per FITS file, labelled by band if a
       ``Band_N`` token is present in the filename.

CSV Exports (``--csv on``)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Filename
     - Contents
   * - ``RP_<group_name>_global.csv``
     - Global geometric parameters. Columns: ``parameter``, ``value``,
       ``uncertainty``. Parameters written: ``Rout_arcsec``,
       ``Rmin_arcsec``, ``Inclination_deg``, ``PA_deg``,
       ``Ellipse_smaj_arcsec``, ``Ellipse_smin_arcsec``,
       ``Center_RA_deg``, ``Center_Dec_deg`` (if WCS available),
       ``Gaia_pmRA_masyr``, ``Gaia_pmDec_masyr``, ``Gaia_match_arcsec``
       (if Gaia match found).
   * - ``RP_<group_name>_bands.csv``
     - Per-image metadata. Columns: ``filename``, ``snr``, ``cx_pix``,
       ``cy_pix``, ``bmaj_arcsec``, ``bmin_arcsec``,
       ``peak_flux_mJyBeam``.
   * - ``RP_<group_name>_profile.csv``
     - Tabulated radial profile data. For each image (column group labelled
       by band): ``R_<band>_arcsec``, ``Flux_<band>_mJy``,
       ``FluxNorm_<band>``, ``FluxNormErr_<band>``. Rows correspond to
       radial bins; missing values are empty strings.

Debug Output (``--debug on``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Filename
     - Contents
   * - ``debug_pipeline/<group_name>_debug_center_rout.png``
     - PNG (dpi=150) of the deprojected image of the reference file, with
       a white cross at the optimised centroid and a dashed cyan circle at
       the outer radius.

GUI Session Files
-----------------

The GUI supports saving and restoring sessions as JSON files. The session
file schema is:

.. code-block:: text

   {
     "filename": "<base FITS filename>",
     "params": {
       "cx": <float>,
       "cy": <float>,
       "incl": <float>,
       "pa": <float>,
       "rout": <float>,
       "fit_rmin": <float>,
       "fit_rmax": <float>
     },
     "timestamp": "<ISO-8601 string>",
     "pixelScale": <float>
   }

On restore, the stored parameters are applied immediately and the
referenced FITS file is reloaded from the upload directory via
``POST /load_local``.

GUI FITS Downloads
------------------

Any pipeline output image type (``"data"``, ``"deproj"``, ``"model"``,
``"residuals"``, ``"polar"``) can be downloaded as a FITS file via
``GET /download_fits?type=<type>``. The returned FITS file carries the
original header from the loaded FITS file.

GUI CSV Export
--------------

The ``handleDownloadCSV`` function in ``AnalysisDashboard.jsx`` produces
a three-column CSV file (``radial_profile.csv``) with the following columns:

.. list-table::
   :header-rows: 1

   * - Column
     - Units
     - Source
   * - ``Radius [arcsec]``
     - arcsec
     - ``profileData.radius``
   * - ``Intensity [Jy/beam]``
     - Jy/beam
     - ``profileData.raw_intensity``
   * - ``Brightness Temp [K]``
     - K
     - ``profileData.intensity``
