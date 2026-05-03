.. _cli:

Command-Line Interface
======================

DISCO provides a single console-script entry point, ``disco-start``,
declared in ``pyproject.toml`` as:

.. code-block:: toml

   [project.scripts]
   disco-start = "disco.main:run"

The entry point ``disco.main:run`` inspects ``sys.argv[1]`` and dispatches
either to the GUI server or to the CLI pipeline (see :ref:`architecture`).

Synopsis
--------

.. code-block:: text

   usage: disco-start [-h] [--rout ROUT] [--rmin RMIN] [--incl INCL] [--pa PA]
                      [--beam BEAM] [--homobeam {on,off}] [--csv {on,off}]
                      [--debug {on,off}] [identifier ...]

Positional Arguments
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Argument
     - Description
   * - ``identifier``
     - Zero or more object identifiers or file paths.
       Each identifier is matched against discovered FITS group names and file
       paths. May be an object name prefix (e.g., ``AS209``), a directory path
       (e.g., ``path/to/group/``), or a direct path to a ``.fits`` file.
       If omitted, all FITS files in the working directory tree are processed.

Optional Arguments
------------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Argument
     - Default
     - Description
   * - ``--rout ROUT``
     - ``None``
     - Force the outer disk radius in arcseconds.
       When specified, the automatic outer radius estimation is bypassed and
       this value is used for all groups.
   * - ``--rmin RMIN``
     - ``0.0``
     - Force the inner disk radius (cavity) in arcseconds.
       When set to 0.0 (default), the inner radius is detected automatically
       from the FITS header beam size.
   * - ``--incl INCL``
     - ``None``
     - Force the disk inclination in degrees.
       When both ``--incl`` and ``--pa`` are specified, the geometry
       optimisation phase (Phase 2) is skipped entirely.
   * - ``--pa PA``
     - ``None``
     - Force the disk position angle in degrees.
       Must be specified jointly with ``--incl`` to bypass optimisation.
   * - ``--beam BEAM``
     - ``None``
     - Force the target beam resolution in arcseconds for beam
       homogenisation. When omitted and ``--homobeam on``, the largest
       beam major axis in the group (multiplied by 1.01) is used as the
       target.
   * - ``--homobeam {on,off}``
     - ``on``
     - Enable or disable beam homogenisation. When ``on``, all images in a
       group are convolved to a common target beam before profile extraction.
   * - ``--csv {on,off}``
     - ``off``
     - Enable CSV export. When ``on``, three CSV files are written per group
       (global parameters, per-band metadata, and tabulated radial profiles).
       See :ref:`file-io-cli` for format details.
   * - ``--debug {on,off}``
     - ``off``
     - Save a diagnostic deprojected PNG image showing the optimised
       centre and outer radius overlay.

Usage Examples
--------------

.. code-block:: bash

   # Process all FITS files discovered in the working directory
   disco-start

   # Process a single object by name prefix
   disco-start AS209

   # Process multiple objects simultaneously
   disco-start AS209 Elias29 DoAr25

   # Process a specific directory group
   disco-start path/to/group/

   # Process a FITS file directly
   disco-start path/to/disk.fits

   # Force inclination and PA, export CSV, enable debug output
   disco-start AS209 --incl 35.0 --pa 120.0 --csv on --debug on

   # Set outer radius and disable beam homogenisation
   disco-start AS209 --rout 1.2 --homobeam off

   # Specify a custom homogenisation beam size
   disco-start AS209 Elias29 --homobeam on --beam 0.15

CNN Model Loading
-----------------

At startup, the CLI attempts to load the pre-trained DiscoNet weights from
``disco/models/disco_model_stable.pth``. The model is instantiated as
``DiscoNet(n_out=5)`` and its state dictionary is loaded with
``weights_only=True``. If the model file is absent or fails to load, a
warning is printed and the pipeline falls back to analytical geometry
optimisation without CNN priors.

.. code-block:: python

   # Effective loading logic in disco/cli.py
   model_path = os.path.join(BASE_DIR, "models", "disco_model_stable.pth")
   if os.path.exists(model_path):
       ckpt      = torch.load(model_path, map_location='cpu', weights_only=True)
       cnn_model = DiscoNet(n_out=5)
       state     = ckpt["model_state"] if isinstance(ckpt, dict) else ckpt
       cnn_model.load_state_dict(state)
       cnn_model.eval()
