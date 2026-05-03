.. _api-fits-utils:

``disco.core.fits_utils``
=========================

.. module:: disco.core.fits_utils
   :synopsis: FITS I/O, beam utilities, WCS helpers, astrometric correction.

This module provides all FITS-level I/O functions and astrometric utilities
used by the CLI pipeline and, indirectly, by the GUI backend. It handles beam
convolution kernels, robust centroid detection, parameter auto-detection,
radial profile extraction, WCS conversions, and Gaia DR3 proper-motion
retrieval.

The availability of ``astroquery`` is detected at import time and stored in
the module-level flag ``_ASTROQUERY_AVAILABLE``. When ``astroquery`` is
absent, the Gaia-related functions are no-ops returning ``(None, None, None)``.

----

Beam Utilities
--------------

.. function:: get_alma_beam(sigma_maj, sigma_min, bpa_rad, size=15)

   Construct a 2D elliptical Gaussian beam kernel on a grid of half-width
   ``size``.

   :param float sigma_maj: Major-axis Gaussian sigma in pixels.
   :param float sigma_min: Minor-axis Gaussian sigma in pixels.
   :param float bpa_rad: Beam position angle in radians.
   :param int size: Half-width of the kernel (kernel shape is
                    ``(2*size+1, 2*size+1)``). Default: 15.
   :returns: Normalised 2D kernel array.
   :rtype: numpy.ndarray

.. function:: deconvolve_beams(bmaj_t, bmin_t, pa_t, bmaj_i, bmin_i, pa_i)

   Compute the convolution kernel required to convolve an image with beam
   :math:`(b_{\rm maj,i}, b_{\rm min,i}, \phi_i)` to the target beam
   :math:`(b_{\rm maj,t}, b_{\rm min,t}, \phi_t)`.

   The deconvolution is performed analytically via covariance matrix
   subtraction: :math:`\Sigma_c = \Sigma_t - \Sigma_i`, followed by
   eigendecomposition to recover the convolution kernel axes.

   :param float bmaj_t: Target beam major axis in arcseconds.
   :param float bmin_t: Target beam minor axis in arcseconds.
   :param float pa_t:   Target beam position angle in degrees.
   :param float bmaj_i: Input beam major axis in arcseconds.
   :param float bmin_i: Input beam minor axis in arcseconds.
   :param float pa_i:   Input beam position angle in degrees.
   :returns: ``(bmaj_c, bmin_c, pa_c)`` — the convolution kernel major
             axis (arcsec), minor axis (arcsec), and position angle (degrees).
             Returns ``(None, None, None)`` if the covariance difference has
             a negative eigenvalue (target beam smaller than input beam).
   :rtype: tuple[float, float, float] or tuple[None, None, None]

.. function:: make_gaussian_kernel_casa(bmaj_c, bmin_c, pa_c, pixel_scale)

   Build a 2D elliptical Gaussian convolution kernel in pixel space from
   beam parameters in arcseconds.

   The kernel size is :math:`\lceil 5\sigma_{\rm maj} \rceil` pixels
   (odd-sized). Normalised to unit sum.

   :param float bmaj_c: Kernel major axis FWHM in arcseconds.
   :param float bmin_c: Kernel minor axis FWHM in arcseconds.
   :param float pa_c:   Kernel position angle in degrees.
   :param float pixel_scale: Pixel scale in arcseconds per pixel.
   :returns: Normalised 2D kernel array.
   :rtype: numpy.ndarray

----

Centroid and Parameter Detection
---------------------------------

.. function:: find_center_robust(data, pixel_scale, header)

   Robustly estimate the disk centroid by Gaussian-smoothing a central
   crop of the image and computing the centre of mass of the thresholded
   (> 20% of peak) emission region. If the filled region is significantly
   larger than the detected region (indicating a cavity), the geometric
   bounding-box midpoint is used instead.

   The search radius is fixed at 3 arcsec from the array centre.

   :param numpy.ndarray data: 2D image array.
   :param float pixel_scale: Pixel scale in arcseconds per pixel.
   :param dict header: FITS header dictionary (used to read ``BMAJ``).
   :returns: ``(cx, cy)`` — pixel coordinates of the estimated centroid.
   :rtype: tuple[float, float]

.. function:: auto_detect_parameters(data, header, pixel_scale, cx, cy)

   Automatically estimate the inner radius, outer radius, and beam major
   axis from the image data and FITS header.

   The outer radius is determined by scanning the azimuthally-averaged
   (non-deprojected) radial profile for the last bin exceeding
   :math:`3\sigma_{\rm edge}`, with a gap tolerance of 0.3 arcsec.

   :param numpy.ndarray data: 2D image array.
   :param dict header: FITS header.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Centroid x-coordinate in pixels.
   :param float cy: Centroid y-coordinate in pixels.
   :returns: ``(rmin, rout, bmaj)`` in arcseconds.
   :rtype: tuple[float, float, float]

.. function:: refine_center_local(data, header, pixel_scale, cx_init, cy_init)

   Refine a centroid estimate by Gaussian-smoothing a small crop around
   the initial position and computing the centre of mass of the
   thresholded emission. The search radius is :math:`0.6\,b_{\rm maj}` or
   a minimum of 0.15 arcsec. If the refined position moves by more than the
   search radius, the initial estimate is returned unchanged.

   :param numpy.ndarray data: 2D image array.
   :param dict header: FITS header.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx_init: Initial centroid x in pixels.
   :param float cy_init: Initial centroid y in pixels.
   :returns: ``(cx, cy)`` refined centroid in pixels.
   :rtype: tuple[float, float]

----

Profile Extraction
------------------

.. function:: extract_profile(data, header, incl, pa, pixel_scale, cx, cy, limit_arcsec)

   Extract the azimuthally-averaged brightness temperature radial profile
   from a FITS image, given the disk geometry.

   The procedure is:

   1. A :math:`1000 \times 1000` deprojected image is generated by
      bilinear resampling (``map_coordinates``, order 3) applying the
      inclination and position angle transform.
   2. The deprojected image is resampled into polar coordinates
      (:math:`R \in [0, 500\,\text{pix}]`, :math:`\theta \in [-180°, 180°]`).
   3. The azimuthal mean and standard deviation are computed.
   4. The uncertainty profile accounts for the effective number of
      independent beams per annulus.
   5. If a valid rest frequency and beam geometry are available, the profile
      is converted to brightness temperature :math:`T_b` [K].

   :param numpy.ndarray data: 2D image array (in mJy/beam or equivalent).
   :param dict header: FITS header (used for ``BMAJ``, ``BMIN``, ``RESTFRQ``).
   :param float incl: Inclination in degrees.
   :param float pa: Position angle in degrees.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Centroid x in pixels.
   :param float cy: Centroid y in pixels.
   :param float limit_arcsec: Maximum radius for the returned profile.
   :returns: ``(r_arcsec, tb_prof, tb_err)`` — radius array, brightness
             temperature profile, and 1-sigma uncertainty, all clipped to
             ``limit_arcsec``.
   :rtype: tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]

.. function:: measure_rout_deproj(data, header, pixel_scale, cx, cy, incl, pa, rmin=0.0)

   Estimate the outer disk radius from the deprojected azimuthally-averaged
   profile. The profile is computed in pixel bins of width one pixel scale.
   The outer radius is defined as the last bin where the smoothed profile
   exceeds ``2 × RMS``, with a gap tolerance of 0.5 arcsec, plus a margin
   of :math:`\max(b_{\rm maj}, 3\,\delta_{\rm pix}, 0.03\,\text{arcsec})`.

   :param numpy.ndarray data: 2D image array.
   :param dict header: FITS header.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Centroid x in pixels.
   :param float cy: Centroid y in pixels.
   :param float incl: Inclination in degrees.
   :param float pa: Position angle in degrees.
   :param float rmin: Inner radius in arcseconds (bins below this are skipped).
   :returns: Estimated outer radius in arcseconds, clipped to [0.10, 8.0].
   :rtype: float

.. function:: save_debug_deproj_center(image, cx, cy, incl, pa, rout_arcsec, pixel_scale, out_png, title)

   Save a diagnostic PNG showing the deprojected image with the optimised
   centroid (cross marker) and outer radius (dashed cyan circle) overlaid.
   Generated when ``--debug on`` is specified.

   :param numpy.ndarray image: 2D image array.
   :param float cx: Centroid x in pixels.
   :param float cy: Centroid y in pixels.
   :param float incl: Inclination in degrees.
   :param float pa: Position angle in degrees.
   :param float rout_arcsec: Outer radius in arcseconds.
   :param float pixel_scale: Arcsec per pixel.
   :param str out_png: Output file path.
   :param str title: Plot title string.

----

WCS and Coordinate Utilities
-----------------------------

.. function:: deg_to_sex(deg)

   Convert a decimal degree value to a sexagesimal string of the form
   ``±DDD:MM:SS.sss``.

   :param float deg: Decimal degrees.
   :returns: Sexagesimal string.
   :rtype: str

.. function:: pixel_to_icrs(header, cx, cy)

   Convert pixel coordinates to ICRS (RA, Dec) using the FITS WCS.
   Uses ``astropy.wcs.WCS.celestial`` to handle cubes with degenerate axes.

   :param dict header: FITS header containing WCS keywords.
   :param float cx: Column (x) coordinate in pixels.
   :param float cy: Row (y) coordinate in pixels.
   :returns: ``(ra_deg, dec_deg)`` in decimal degrees (ICRS).
   :rtype: tuple[float, float]

.. function:: icrs_to_pixel(header, ra_deg, dec_deg)

   Convert ICRS sky coordinates to pixel coordinates using the FITS WCS.

   :param dict header: FITS header.
   :param float ra_deg: Right ascension in decimal degrees.
   :param float dec_deg: Declination in decimal degrees.
   :returns: ``(x, y)`` pixel coordinates.
   :rtype: tuple[float, float]

.. function:: get_obs_epoch(header)

   Extract the observation epoch from the FITS header. Reads ``DATE-OBS``
   (ISO-T format) or ``MJD-OBS`` (Modified Julian Date).

   :param dict header: FITS header.
   :returns: Observation epoch as an :class:`astropy.time.Time` object,
             or ``None`` if neither keyword is present or parseable.
   :rtype: astropy.time.Time or None

----

Gaia Proper Motion
------------------

.. function:: query_gaia_proper_motion(ra_deg, dec_deg, search_radius_arcsec=3.0)

   Query the Gaia DR3 catalogue (``gaiadr3.gaia_source``) for the nearest
   source within ``search_radius_arcsec`` arcseconds of the supplied position.
   Returns the proper motion of the nearest source with valid ``pmra`` and
   ``pmdec`` values.

   Requires ``astroquery`` to be installed. Returns ``(None, None, None)``
   if the library is unavailable or no match is found.

   :param float ra_deg: Right ascension in decimal degrees (ICRS).
   :param float dec_deg: Declination in decimal degrees (ICRS).
   :param float search_radius_arcsec: Cone search radius. Default: 3.0.
   :returns: ``(pmra_masyr, pmdec_masyr, separation_arcsec)`` for the
             nearest matched Gaia source, or ``(None, None, None)``.
   :rtype: tuple[float, float, float] or tuple[None, None, None]

.. function:: apply_proper_motion_correction(ra_deg, dec_deg, pmra_masyr, pmdec_masyr, dt_yr)

   Apply a proper-motion correction to a sky position, propagating it
   by ``dt_yr`` years.

   .. math::

      \Delta\alpha = \frac{\mu_\alpha^* \, \Delta t}{\cos\delta \times 3.6 \times 10^6}, \qquad
      \Delta\delta  = \frac{\mu_\delta \, \Delta t}{3.6 \times 10^6}

   :param float ra_deg: Original right ascension in decimal degrees.
   :param float dec_deg: Original declination in decimal degrees.
   :param float pmra_masyr: Proper motion in RA (mas/yr), including cos(δ) factor.
   :param float pmdec_masyr: Proper motion in Dec (mas/yr).
   :param float dt_yr: Time baseline in years.
   :returns: ``(ra_corrected_deg, dec_corrected_deg)``.
   :rtype: tuple[float, float]
