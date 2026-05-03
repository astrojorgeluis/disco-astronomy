.. _api-cnn-inference:

``disco.core.cnn_inference``
============================

.. module:: disco.core.cnn_inference
   :synopsis: DiscoNet CNN architecture and inference helper.

This module defines the **DiscoNet** convolutional neural network and the
:func:`predict_with_cnn` inference function used to generate prior estimates
of disk inclination and position angle from a FITS image patch.

----

Architecture
------------

DiscoNet is a residual convolutional encoder with a multi-layer perceptron
head. It accepts a 3-channel :math:`128 \times 128` tensor and returns 5
scalar outputs (``n_out=5``), although only the first three are used for
geometric parameter decoding in the current inference path.

.. class:: ResBlock(ch)

   A residual block consisting of two :math:`3 \times 3` convolutional layers
   with batch normalisation and ReLU activations, plus a skip connection.

   .. math::

      \text{out} = \text{ReLU}\!\left(x + \text{BN}(\text{Conv}(\text{ReLU}(\text{BN}(\text{Conv}(x)))))\right)

   :param int ch: Number of input and output channels.

   .. method:: forward(x)

      :param torch.Tensor x: Input feature map.
      :returns: Output feature map of the same shape as input.
      :rtype: torch.Tensor

.. class:: DiscoNet(n_out=6)

   Residual convolutional encoder with five downsampling stages and an MLP
   regression head. At inference time the model is loaded with ``n_out=5``.

   **Architecture summary:**

   .. list-table::
      :header-rows: 1
      :widths: 20 30 50

      * - Stage
        - Layer(s)
        - Output channels
      * - ``stem``
        - Conv 3×3, BN, ReLU
        - 32
      * - ``enc1``
        - ResBlock(32) + Conv 3×3 stride 2
        - 64
      * - ``enc2``
        - ResBlock(64) + Conv 3×3 stride 2
        - 128
      * - ``enc3``
        - ResBlock(128) + Conv 3×3 stride 2
        - 256
      * - ``enc4``
        - ResBlock(256) + Conv 3×3 stride 2
        - 512
      * - ``enc5``
        - ResBlock(512) + Conv 3×3 stride 2
        - 512
      * - ``pool``
        - AdaptiveAvgPool2d(4×4)
        - 512 × 4 × 4 = 8192
      * - ``head``
        - Linear(8192→1024), ReLU, Dropout(0.45), Linear(1024→512),
          ReLU, Dropout(0.30), Linear(512→n_out)
        - n_out

   :param int n_out: Number of output scalars. Default: 6. The CLI pipeline
                     loads the model with ``n_out=5``.

   .. method:: forward(x)

      :param torch.Tensor x: Input tensor of shape ``(N, 3, H, W)``.
      :returns: Output tensor of shape ``(N, n_out)``.
      :rtype: torch.Tensor

----

Output Encoding
---------------

The network outputs are encoded as follows (as documented in the training
checkpoint ``outputs`` field):

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Index
     - Symbol
     - Encoding
   * - 0
     - ``incl/90``
     - Inclination normalised to [0, 1] (multiply by 90° to recover degrees)
   * - 1
     - ``sin2PA``
     - :math:`\sin(2\phi)` — PA encoded as double-angle sine
   * - 2
     - ``cos2PA``
     - :math:`\cos(2\phi)` — PA encoded as double-angle cosine
   * - 3
     - ``dx/0.14``
     - Centre x-offset normalised by 0.14 arcsec (not used in inference)
   * - 4
     - ``dy/0.14``
     - Centre y-offset normalised by 0.14 arcsec (not used in inference)

The position angle is decoded as:

.. math::

   \hat{\phi} = \left(\frac{1}{2}\arctan_2\!\left(\hat{y}_1,\, \hat{y}_2\right) \times \frac{180}{\pi}\right) \bmod 180°

This double-angle encoding is used to ensure continuity across the
:math:`0° / 180°` boundary of position angle.

----

Inference Function
------------------

.. function:: predict_with_cnn(data, header, pixel_scale, cx, cy, search_rad, model)

   Generate a prior estimate of disk inclination and position angle from a
   FITS image patch using a pre-loaded DiscoNet model.

   **Preprocessing:**

   1. A rectangular crop of half-width :math:`1.5 \times r_{\rm search} /
      \delta_{\rm pix}` pixels is extracted around ``(cx, cy)``. The crop
      is zero-padded if it extends beyond the image boundary.
   2. The crop is resampled to :math:`128 \times 128` pixels using
      ``scipy.ndimage.zoom`` (order 1).
   3. Intensity normalisation: clipped to :math:`[p_1, p_{99.9}]` then
      rescaled to [0, 1].
   4. A beam map (2D elliptical Gaussian at the image centre, normalised to
      peak 1) is constructed for the second channel.
   5. A scalar map filled with
      :math:`\text{clip}(b_{\rm maj} / \text{FOV}, 0, 1)` is used as the
      third channel.

   The resulting 3-channel tensor of shape ``(1, 3, 128, 128)`` is forwarded
   through the model in ``eval`` mode with gradient computation disabled.

   **Output decoding:**

   .. math::

      \hat{i}  = \text{clip}(y_0 \times 90°,\ 0°, 85°)

      \hat{\phi} = \left(\frac{\arctan_2(y_1, y_2)}{2} \times \frac{180}{\pi}\right) \bmod 180°

   :param numpy.ndarray data: 2D FITS image array (float32).
   :param dict header: FITS header (used for ``BMAJ``, ``BMIN``, ``BPA``).
   :param float pixel_scale: Pixel scale in arcseconds per pixel.
   :param float cx: Centroid column coordinate in pixels.
   :param float cy: Centroid row coordinate in pixels.
   :param float search_rad: Search radius in arcseconds defining the crop region.
   :param DiscoNet model: Pre-loaded DiscoNet model in evaluation mode.
   :returns: ``(cnn_incl, cnn_pa)`` — estimated inclination (degrees) and
             position angle (degrees).
   :rtype: tuple[float, float]
