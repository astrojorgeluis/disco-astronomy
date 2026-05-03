.. _training:

DiscoNet Training Pipeline
==========================

.. note::

   The training scripts (located in ``training/``) are not installed as part
   of the ``disco-astronomy`` package and are not required for end-user
   operation. They are provided for reproducibility and documentation purposes.
   CASA (Common Astronomy Software Applications) is required for
   ``simulate_catalogue.py``.

The DiscoNet model is trained on a hybrid dataset combining simulated ALMA
observations (generated via CASA) and on-the-fly synthetic disk images. The
training pipeline consists of three independent scripts.

----

Step 1: Catalogue Generation (``training/generate_catalogue.py``)
-----------------------------------------------------------------

Generates a CSV catalogue of 100 synthetic disk parameters with randomised
physical properties drawn from the following distributions:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Sampling distribution
   * - ``incl_deg``
     - 40% in [0°, 30°] (low inclination), 60% in [30°, 80°] (high).
   * - ``pa_deg``
     - Uniform in [0°, 180°].
   * - ``rout_arcsec``
     - 35% "compact" in [0.10″, 0.50″]; 35% "large" in [0.60″, 1.80″];
       30% "intermediate" in [0.35″, 0.90″].
   * - ``rmin_arcsec``
     - Set to a non-zero value (drawn uniformly from [0.05″, 0.55 rout])
       with probability 30%; otherwise 0.
   * - ``band``
     - ALMA Band 6 (70% probability) or Band 8 (30%).
   * - ``flux_jy``
     - Log-uniform: Band 6 in [5, 80] mJy; Band 8 in [5, 40] mJy.
   * - ``array_cfg``
     - Band 6: ``cycle9.6/7/8.cfg`` with probabilities [0.20, 0.35, 0.45];
       Band 8: ``cycle9.5/6/7.cfg`` with [0.20, 0.35, 0.45].
   * - ``pwv``
     - Band 6: uniform in [0.8, 2.5] mm; Band 8: uniform in [0.4, 1.2] mm.
   * - ``time_s``
     - One of: 1200, 1800, 2400, 3600 seconds (uniform random choice).
   * - ``niter``
     - Uniform integer in [300, 1500].

Output: ``catalogo_piloto.csv`` with columns ``ID``, ``incl_deg``,
``pa_deg``, ``rout_arcsec``, ``rmin_arcsec``, ``flux_jy``, ``time_s``,
``array_cfg``, ``pwv``, ``niter``, ``band``, ``array_lo``.

----

Step 2: FITS Simulation (``training/simulate_catalogue.py``)
------------------------------------------------------------

For each row in the catalogue, this script:

1. Generates a synthetic sky model FITS file (``create_fits_model``) on a
   1024 × 1024 pixel grid using a physically-motivated brightness
   temperature model including:

   * A power-law + exponential radial profile
   * Optional inner cavity with wall brightening
   * Randomised gap-ring substructure (0–5 gaps per disk)
   * Optional crescent asymmetry (20% probability)
   * Optional central unresolved component (80% probability)
   * Multiplicative texture noise (Gaussian-filtered)
   * Outer exponential taper

2. Calls CASA ``simobserve`` with the sky model to produce a simulated
   measurement set.

3. Calls CASA ``tclean`` with multi-scale CLEAN to produce a FITS image.

Array configurations and Band parameters used:

.. list-table::
   :header-rows: 1
   :widths: 25 20 15 15

   * - Configuration
     - Beam (mas)
     - Cell (mas)
     - Comment
   * - ``alma.cycle9.5.cfg``
     - 130
     - 22
     -
   * - ``alma.cycle9.6.cfg``
     - 80
     - 13
     -
   * - ``alma.cycle9.7.cfg``
     - 50
     - 8
     -
   * - ``alma.cycle9.8.cfg``
     - 28
     - 5
     -

----

Step 3: Model Training (``training/train_model.py``)
-----------------------------------------------------

The training script combines two datasets:

* **FITSDataset** — real FITS simulations from ``training/simulations/``,
  with online augmentation.
* **SyntheticDataset** — purely synthetic disk images generated on-the-fly
  by randomly sampling disk parameters without CASA simulation.

The combined dataset is split 90/10 into training and validation subsets.
The model trained is ``DiskNet`` (equivalent in architecture to
:class:`disco.core.cnn_inference.DiscoNet`).

**Training configuration:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Hyperparameter
     - Value / Description
   * - Input size
     - 3 × IMG_SIZE × IMG_SIZE (3-channel: normalised intensity, beam map,
       beam scale map)
   * - Outputs
     - 5: ``[incl/90, sin2PA, cos2PA, dx/0.14, dy/0.14]``
   * - Optimiser
     - AdamW, ``lr=LEARNING_RATE``, ``weight_decay=1e-3``
   * - LR schedule
     - Linear warmup (5 epochs) + cosine decay to 10% of initial LR
   * - Gradient clipping
     - ``max_norm=2.0``
   * - Mixup augmentation
     - Applied with probability 0.5 per batch
   * - Batch dropout
     - 0.45 (first head layer), 0.30 (second head layer)

The best checkpoint (lowest validation loss) is saved to
``MODEL_SAVE_PATH`` (configured in the script) with the following
checkpoint schema:

.. code-block:: python

   {
       "epoch":       int,
       "model_state": OrderedDict,
       "val_loss":    float,
       "img_size":    int,
       "n_out":       int,
       "outputs":     ["incl/90", "sin2PA", "cos2PA", "dx/0.14", "dy/0.14"],
   }

This checkpoint is the file distributed as ``disco/models/disco_model_stable.pth``.
