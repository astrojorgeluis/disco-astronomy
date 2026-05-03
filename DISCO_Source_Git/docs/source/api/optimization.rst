.. _api-optimization:

``disco.core.optimization``
===========================

.. module:: disco.core.optimization
   :synopsis: Geometric loss function and hybrid geometry optimiser.

This module implements the core geometric loss function used to assess the
azimuthal symmetry of a deprojected disk image, and the functions that
orchestrate the hybrid CNN-seeded optimisation strategy.

----

Geometric Loss Function
-----------------------

.. function:: geometric_loss(params, image, base_cx, base_cy, crop_rad, rmin_pix, rmax_pix, dim=150, order=1)

   Evaluate the asymmetry of a disk image under a given deprojection
   geometry. This function serves as the objective for all optimisation
   routines in DISCO.

   **Algorithm:**

   1. The four-parameter vector ``[incl, pa, dcx, dcy]`` defines the
      trial geometry: inclination and position angle (both in degrees) and
      centre offsets (in pixels) relative to ``(base_cx, base_cy)``.

   2. A square grid of dimension ``dim × dim`` is constructed in the
      deprojected frame. The corresponding source-plane pixel coordinates are
      computed via the inclination and rotation transforms, then offset by the
      trial centre:

      .. math::

         X_c = X \cos i, \qquad
         X_{\rm rot} = \cos\phi \cdot X_c + \sin\phi \cdot Y, \qquad
         Y_{\rm rot} = -\sin\phi \cdot X_c + \cos\phi \cdot Y

   3. The deprojected image ``deproj`` is obtained by interpolating the
      cropped input ``image`` at the source-plane coordinates via
      ``scipy.ndimage.map_coordinates`` with the specified ``order``.

   4. The deprojected image is mapped into polar coordinates
      (:math:`r \in [0, \dim/2]`, :math:`\theta \in [-\pi, \pi]`,
      180 azimuthal samples).

   5. The azimuthal mean profile ``profile[r]`` is computed over the radial
      range ``[rmin_pix, rmax_pix]``.

   6. The loss is the weighted Huber loss of the residuals between the polar
      image and its azimuthal mean:

      .. math::

         L = \sum_{r,\theta} h_\delta\!\left(
               \frac{I_{\rm polar}(r,\theta) - \bar{I}(r)}
                    {\bar{I}(r) + 0.01 \max(\bar{I})}
             \right) w(r)

      where :math:`h_\delta` is the Huber function with :math:`\delta = 0.5`
      and :math:`w(r) = \sqrt{\bar{I}(r)/\max(\bar{I})} \cdot [r \ge 0.03]
      \cdot r` is a radially-weighted mask favouring the bright, outer disk.

   If more than 10% of the mapped pixel coordinates fall outside the image
   boundary, or if the profile maximum is below :math:`10^{-8}`, the
   function returns the sentinel value :math:`10^{12}`.

   :param list params: ``[incl, pa, dcx, dcy]`` — inclination (deg),
                       position angle (deg), x centre offset (pix),
                       y centre offset (pix).
   :param numpy.ndarray image: 2D cropped image array.
   :param float base_cx: Reference centre x in the cropped array.
   :param float base_cy: Reference centre y in the cropped array.
   :param float crop_rad: Half-width of the cropped array in pixels.
   :param float rmin_pix: Inner radius of the fitting annulus in pixels.
   :param float rmax_pix: Outer radius of the fitting annulus in pixels.
   :param int dim: Size of the evaluation grid. Default: 150.
   :param int order: Interpolation order for ``map_coordinates``. Default: 1.
   :returns: Scalar loss value.
   :rtype: float

----

Hybrid Geometry Optimiser
--------------------------

.. function:: auto_tune_geometry_hybrid(data, header, pixel_scale, cx, cy, model, search_rad, rmin)

   Determine the optimal disk inclination, position angle, and centre offset
   using a two-stage hybrid strategy: CNN-seeded global search followed by
   local refinement.

   **Stage 1 — CNN prior:**

   :func:`disco.core.cnn_inference.predict_with_cnn` provides an initial
   estimate :math:`(\hat{i}_{\rm CNN}, \hat{\phi}_{\rm CNN})` that constrains
   the parameter bounds for the subsequent optimisation.

   **Stage 2 — Differential evolution (coarse):**

   ``scipy.optimize.differential_evolution`` minimises
   :func:`geometric_loss` on a Gaussian-smoothed version of the cropped image
   (``dc_smooth``, smoothing width :math:`\approx 0.4\,b_{\rm maj}`).
   The search bounds are constrained around the CNN prior:

   * :math:`i \in [\hat{i}_{\rm CNN} - \Delta_i, \hat{i}_{\rm CNN} + \Delta_i]`,
     where :math:`\Delta_i = 15°` if :math:`\hat{i}_{\rm CNN} < 35°`,
     else :math:`20°`.
   * :math:`\phi \in [\hat{\phi}_{\rm CNN} - \Delta_\phi, \hat{\phi}_{\rm CNN} + \Delta_\phi]`,
     where :math:`\Delta_\phi = 25°` if :math:`\hat{i}_{\rm CNN} < 35°`,
     else :math:`30°`.
   * Centre offsets: :math:`|\Delta x|, |\Delta y| \le 1.5` pixels.

   Parameters: ``maxiter=50``, ``tol=0.02``, ``mutation=(0.5, 1.0)``,
   ``recombination=0.7``, ``seed=42``.

   **Stage 3 — Nelder-Mead refinement (fine):**

   Starting from the differential-evolution result, ``scipy.optimize.minimize``
   (Nelder-Mead) refines on the full-resolution image ``dc`` with a
   :math:`400 \times 400` grid (``order=3``).

   **Stage 4 — Secondary refinement (if near boundary):**

   If the optimised centre offset is within 80% of the bound (``near_edge``),
   a second differential-evolution + Nelder-Mead cycle is run with the
   accumulated offset applied to the reference centre, and tighter bounds
   (:math:`|\Delta x|, |\Delta y| \le 0.6` pixels). The final offset is the
   sum of both stages.

   **Consistency guard:**

   If the final inclination departs from :math:`\hat{i}_{\rm CNN}` by more
   than 20°, the CNN prior is restored for both inclination and position
   angle, and the centre offset is zeroed.

   :param numpy.ndarray data: 2D FITS image array.
   :param dict header: FITS header.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Initial centroid x in pixels.
   :param float cy: Initial centroid y in pixels.
   :param DiscoNet model: Pre-loaded DiscoNet model.
   :param float search_rad: Search radius in arcseconds.
   :param float rmin: Inner radius in arcseconds.
   :returns: ``(incl, pa, cnn_incl, cnn_pa, dcx, dcy)`` — optimised inclination
             (deg), optimised PA (deg), CNN prior inclination (deg), CNN prior PA
             (deg), x centre correction (pix), y centre correction (pix).
   :rtype: tuple[float, float, float, float, float, float]

----

Uncertainty Estimation
-----------------------

.. function:: estimate_geometry_errors(data, pixel_scale, cx, cy, incl, pa, rmin, rmax)

   Estimate 1-sigma uncertainties on the inclination and position angle via
   a parabolic approximation of the geometric loss landscape.

   The function first performs a local Nelder-Mead optimisation to confirm
   the minimum, evaluates the loss :math:`L_{\rm min}`, and then scans
   the loss along each angular axis independently at offsets
   :math:`\delta \in [-11.75°, +11.75°]` (step 0.25°). A degree-2 polynomial
   is fitted to the valid loss values (:math:`L < 2.5\,L_{\rm min}`). The
   estimated 1-sigma uncertainty is:

   .. math::

      \sigma = \text{clip}\!\left(\sqrt{\frac{L_{\rm min} \times 5 \times 10^{-3}}{a}},\ 0.3°,\ 10°\right)

   where :math:`a` is the parabola's leading coefficient. Returns ``(2.0, 2.0)``
   if the minimum loss is non-finite or exceeds :math:`10^{11}`, or if fewer
   than 5 valid loss samples are available.

   :param numpy.ndarray data: 2D image array.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Centroid x in pixels.
   :param float cy: Centroid y in pixels.
   :param float incl: Best-fit inclination in degrees.
   :param float pa: Best-fit position angle in degrees.
   :param float rmin: Inner fitting radius in arcseconds.
   :param float rmax: Outer fitting radius in arcseconds.
   :returns: ``(err_incl, err_pa)`` — 1-sigma uncertainties in degrees.
   :rtype: tuple[float, float]

----

Centre Refinement
-----------------

.. function:: refine_center_geometry(data, header, pixel_scale, cx, cy, incl, pa, rmin, rmax)

   Refine the disk centroid by optimising centre offsets while holding
   inclination and position angle fixed.

   A Nelder-Mead optimisation is performed with the centre offset constrained
   to :math:`\le 2\,b_{\rm maj}` pixels. If the optimised offset does not
   improve the loss, or if the offset exceeds the bound, the original centre
   is returned unchanged.

   :param numpy.ndarray data: 2D image array.
   :param dict header: FITS header.
   :param float pixel_scale: Arcsec per pixel.
   :param float cx: Initial centroid x in pixels.
   :param float cy: Initial centroid y in pixels.
   :param float incl: Fixed inclination in degrees.
   :param float pa: Fixed position angle in degrees.
   :param float rmin: Inner fitting radius in arcseconds.
   :param float rmax: Outer fitting radius in arcseconds.
   :returns: ``(cx_refined, cy_refined)`` in pixels.
   :rtype: tuple[float, float]
