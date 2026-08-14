.. _training:

DiscoNet Training Pipeline
==========================

.. note::

   The training scripts in ``training/`` are **not** installed with the
   ``disco-astronomy`` package. End users only need the bundled weights
   ``disco/models/disco_model_stable.pth``. CASA is required only if you
   regenerate FITS simulations with ``simulate_catalogue.py``.

Shipped model (v1.2.5)
----------------------

The packaged DiscoNet checkpoint was trained in **synthetic-only** mode
(``train_model.py --synthetic-only``):

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Item
     - Value
   * - Dataset
     - ``SyntheticDataset``: 20 000 on-the-fly 128×128 crops (no CASA FITS)
   * - Morphology mix
     - 25% smooth, 40% simple (1–2 gaps), 35% complex (3–5 gaps)
   * - Inclination / PA
     - Uniform :math:`i \in [0°, 83°]`, :math:`\mathrm{PA} \in [0°, 180°]`
   * - Size / SNR / beam
     - Rout from ~0.05″ upward; SNR 5–200; elliptical beams with random BPA
   * - Channels
     - Normalised intensity, elliptical beam map, beam-scale map
         (same preprocess as inference: ``disco.core.cnn_preprocess``)
   * - Epochs / early stop
     - Up to 80 epochs, patience 15; best checkpoint ≈ epoch 64
   * - Val MAE (synthetic hold-out)
     - Inclination ≈ 4.6°; PA ≈ 9.6° (180° wrap)
   * - Seed / batch / AMP
     - ``--seed 42``, batch 32, CUDA AMP enabled

Reproduce the shipped recipe:

.. code-block:: bash

   cd DISCO_Source_Git/training
   python train_model.py --synthetic-only --synthetic-samples 20000 \
     --epochs 80 --batch-size 32 --amp --patience 15 --seed 42 \
     --save disco_model_stable.pth

Optional CASA path (not used for the v1.2.5 release weights)
------------------------------------------------------------

A hybrid train (CASA FITS + synthetic) is supported but did **not** beat
synthetic-only on the literature test set used for v1.2.5. The three
scripts remain for reproducibility:

Step 1 — ``generate_catalogue.py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Writes a CSV of randomised disk + ALMA observing parameters
(``incl_deg``, ``pa_deg``, ``rout_arcsec``, ``rmin_arcsec``, band, array,
PWV, time, flux, center offsets ``dx_arcsec`` / ``dy_arcsec``, …).

Step 2 — ``simulate_catalogue.py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For each catalogue row: build a Jy/pixel sky model, run CASA
``simobserve`` + ``tclean``, export FITS, stamp training keywords
(``INCL``, ``PA``, ``DX_AS``, …), optional post-export domain noise.

Step 3 — ``train_model.py`` (mixed)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Without ``--synthetic-only``, combines ``FITSDataset`` (simulated FITS +
augment) with ``SyntheticDataset``. Split is by object ID (no crop leak
into validation). Mixup does not blend PA sin/cos targets.

Network and loss
----------------

* Architecture: :class:`disco.core.cnn_inference.DiscoNet` (``n_out=5``).
* Labels: ``[incl/90, sin(2·PA), cos(2·PA), dx/CENTER_SCALE, dy/CENTER_SCALE]``
  with ``CENTER_SCALE = 0.14`` (FOV-normalised center).
* Loss: weighted L1 on inclination, PA (via sin/cos), and center.
* Optimiser: AdamW + linear warmup (5 epochs) + cosine decay; grad clip 2.0.

Checkpoint schema
-----------------

.. code-block:: python

   {
       "epoch":       int,
       "model_state": OrderedDict,
       "val_loss":    float,
       "img_size":    int,   # 128
       "n_out":       int,   # 5
       "outputs":     ["incl/90", "sin2PA", "cos2PA", "dx/0.14", "dy/0.14"],
   }

Validation note
---------------

Geometric accuracy on real ALMA disks is assessed with the CLI hybrid
pipeline against literature values (e.g. DSHARP). Typical hybrid MAE on
inclination is ~1.7° (DSHARP) / ~3° (DSHARP+ODISEA). Face-on disks
(:math:`i \lesssim 25°`) have poorly constrained continuum PA; the
plot :math:`\pm` from ``estimate_geometry_errors`` is a **loss-curvature**
indicator, not a literature :math:`1\sigma`.
