.. _pipeline:

Pipeline Description
====================

The CLI pipeline (implemented in :func:`disco.cli.run_pipeline`) processes
each group of FITS files through five sequential phases. A ``tqdm`` progress
bar tracks advancement through these phases.

Group Discovery
---------------

Before any processing begins, :func:`disco.cli.discover_groups` traverses
the working directory tree via ``os.walk``, collecting all ``.fits`` files.
Files within a common directory are grouped by a common stem prefix: the
function splits each filename on the regular expression ``_?[Bb]and_?\d+`` to
isolate the source identifier, then aggregates files sharing the same prefix
into a group dictionary containing the group name, sorted list of file paths,
and designated output directory.

Target selection from command-line identifiers is performed by matching each
supplied string against the resolved directory path components and filenames of
each discovered group. Groups that partially match (via substring containment)
are included.

Phase 1 — FITS Ingestion
-------------------------

Each FITS file in the group is opened with ``astropy.io.fits``. The primary
HDU data array is squeezed (removing degenerate Stokes and frequency axes),
converted to ``float32``, and passed through ``numpy.nan_to_num``.

Unit normalisation is applied if the ``BUNIT`` header keyword is ``'JY/BEAM'``
(data multiplied by 1 000, header updated to ``'mJy/beam'``), or if the
inferred units are unlabelled and the data maximum is below 5.0 (same
multiplicative correction applied heuristically).

The pixel scale is derived as:

.. math::

   \delta_{\rm pix} = |\texttt{CDELT2}| \times 3600 \quad [\text{arcsec pixel}^{-1}]

For each file, the following quantities are computed:

* **Centroid** via :func:`disco.core.fits_utils.find_center_robust`
* **Radial extent and inner radius** via
  :func:`disco.core.fits_utils.auto_detect_parameters`
* **Beam parameters** (``BMAJ``, ``BMIN``) from the FITS header
* **Observation epoch** via :func:`disco.core.fits_utils.get_obs_epoch`,
  reading ``DATE-OBS`` (ISO-T) or ``MJD-OBS``

The image with the highest per-beam signal-to-noise ratio is selected as the
**reference image** for geometry determination. The SNR scoring function is:

.. math::

   \mathrm{SNR} = \frac{\max(d)}{\sigma_{\rm edge}}, \qquad
   \text{score} = \frac{\mathrm{SNR}}{\Omega_{\rm beam}^{3/2}}

where :math:`\sigma_{\rm edge}` is estimated from the 10-pixel border of the
image and :math:`\Omega_{\rm beam} = b_{\rm maj} \times b_{\rm min}`.

If ``astroquery`` is available and the reference centroid can be converted to
ICRS coordinates (via :func:`disco.core.fits_utils.pixel_to_icrs`), a
Gaia DR3 proper-motion query is issued via
:func:`disco.core.fits_utils.query_gaia_proper_motion` within a 3 arcsec
cone. Detected proper motions are used to register centroids of secondary
images relative to the reference epoch through
:func:`disco.core.fits_utils.apply_proper_motion_correction`.

Phase 2 — Geometry Optimisation
---------------------------------

If both ``--incl`` and ``--pa`` are supplied by the user, these values are
used directly. Otherwise, geometry is determined as follows.

**With CNN model available:**

:func:`disco.core.optimization.auto_tune_geometry_hybrid` is called on the
reference image. This function:

1. Invokes :func:`disco.core.cnn_inference.predict_with_cnn` to obtain an
   initial prior estimate :math:`(\hat{i}_{\rm CNN}, \hat{\phi}_{\rm CNN})`.
2. Constructs a cropped, zero-padded subimage centred on the reference
   centroid, at radius :math:`1.5 \times r_{\rm search}`.
3. Applies a Gaussian pre-smoothing kernel (width :math:`\sim 0.4\,b_{\rm maj}`)
   to produce a coarse image ``dc_smooth``.
4. Runs ``scipy.optimize.differential_evolution`` within CNN-constrained
   parameter bounds to find a global minimum of
   :func:`disco.core.optimization.geometric_loss` on the smoothed image.
5. Refines this solution with ``scipy.optimize.minimize`` (Nelder-Mead) on
   the full-resolution image.
6. If the optimised centre offset is near the search boundary, a second
   optimisation stage is initiated with the accumulated offset as a new
   origin.
7. Applies a consistency guard: if the optimised inclination departs from
   the CNN prior by more than 20°, the CNN prior is restored.

.. _cli-geometry-fallback:

**Without CNN model (fallback):**

A direct ``scipy.optimize.minimize`` call (Nelder-Mead) minimises
:func:`disco.core.optimization.geometric_loss` starting from the fixed
initial point :math:`(i_0, \phi_0, \Delta x_0, \Delta y_0) = (30°, 45°, 0, 0)`.

Phase 3 — Uncertainty Estimation
----------------------------------

Geometric uncertainties are computed by
:func:`disco.core.optimization.estimate_geometry_errors` using a parabolic
approximation of the loss landscape:

1. The optimised geometry is refined locally with Nelder-Mead.
2. The loss at the minimum, :math:`L_{\rm min}`, is evaluated.
3. A one-dimensional scan in each angular parameter is performed over a
   grid of offsets :math:`\delta \in [-12°, +12°]` at 0.25° intervals.
4. A degree-2 polynomial is fitted to the valid loss values. The estimated
   1-sigma uncertainty is:

   .. math::

      \sigma_\theta = \sqrt{\frac{L_{\rm min} \times 5 \times 10^{-3}}{a}}

   where :math:`a` is the leading coefficient of the parabola, clipped to
   :math:`[0.3°, 10°]`.

The outer radius is then estimated by a weighted fusion of two independent
estimates:

* A deprojection-based estimate from
  :func:`disco.core.fits_utils.measure_rout_deproj`, which thresholds the
  azimuthally-averaged deprojected profile at 2σ above the local RMS.
* The heuristic auto-detected estimate from Phase 1.

The weights depend on inclination and the ratio between the two estimates.

Phase 4 — Profile Extraction and Beam Homogenisation
------------------------------------------------------

If ``--homobeam on`` is set (default), all secondary images are convolved
to the largest beam in the group. The convolution kernel is derived by
:func:`disco.core.fits_utils.deconvolve_beams` (covariance-matrix beam
deconvolution) and constructed by
:func:`disco.core.fits_utils.make_gaussian_kernel_casa`. Convolution is
performed via ``scipy.signal.fftconvolve``. The flux scale is corrected by
the ratio of beam solid angles.

A custom target beam size can be specified via ``--beam <arcsec>``.

For each image (sorted by SNR in descending order),
:func:`disco.core.fits_utils.extract_profile` produces the azimuthally-
averaged radial profile:

1. A :math:`1000 \times 1000` deprojected image is computed by bilinear
   resampling (order 3) using the WCS-consistent rotation and inclination
   transform.
2. A polar-coordinate map is extracted from this deprojected image.
3. The mean and standard deviation along the azimuthal axis are computed
   to yield the profile :math:`\bar{I}(r)` and its uncertainty
   :math:`\sigma_I(r)`.
4. If a valid rest frequency and beam geometry are available, the profile
   is converted to brightness temperature :math:`T_b` via the
   Rayleigh–Jeans approximation:

   .. math::

      T_b = \frac{c^2}{2 \nu^2 k_B \Omega_{\rm beam}} \, S_\nu

Phase 5 — Output Serialisation
--------------------------------

Output files are written to the group's ``output_dir``:

* ``RP_<group_name>.PNG`` — Normalised radial profile plot
  (Matplotlib, dpi=150, white background)

If ``--csv on`` is specified, three additional files are written:

* ``RP_<group_name>_global.csv`` — Fitted geometric parameters
  (inclination, position angle, outer/inner radius, ellipse axes,
  sky coordinates in degrees, Gaia proper motions if available)
* ``RP_<group_name>_bands.csv`` — Per-file metadata
  (filename, SNR, pixel centroid, beam dimensions, peak flux)
* ``RP_<group_name>_profile.csv`` — Radial profile tabulation
  (radius in arcsec, raw flux, normalised flux, normalised uncertainty)

If ``--debug on`` is set, a diagnostic deprojected image is saved to
``<output_dir>/debug_pipeline/<group_name>_debug_center_rout.png`` by
:func:`disco.core.fits_utils.save_debug_deproj_center`.
