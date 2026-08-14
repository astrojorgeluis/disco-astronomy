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

   usage: disco-start [-h] [--group {file,dir,name}] [--ref REF]
                      [--rout ROUT] [--rmin RMIN] [--incl INCL] [--pa PA]
                      [--beam BEAM] [--homobeam {on,off}] [--csv {on,off}]
                      [--debug {on,off}] [-y] [identifier ...]

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
   * - ``--group {file,dir,name}``
     - ``file``
     - How to group FITS files. ``file`` (default): each FITS is its own
       group — safest for a mixed folder. ``dir``: all FITS *directly* in
       the same folder are one group (nested directories stay separate).
       Use this for one object with several bands or methods.
       ``name``: legacy split on ``BandN`` / ``_Band6`` in the filename
       (``B6_`` / ``priism_b6`` are not split). Homogenisation applies
       **inside** a group only.
   * - ``--ref REF``
     - auto
     - Geometry reference inside each group (CNN + hybrid, Rout, centre).
       Accepts a filename, a unique substring, or a path; must match
       **exactly one** file in the group. Default without ``--ref`` is the
       highest :math:`\mathrm{SNR}/\Omega_{\mathrm{beam}}^{3/2}`. If both
       ``--incl`` and ``--pa`` are set, those angles override the fit;
       ``--ref`` still selects the map for centre / Rout.
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
   * - ``-y``, ``--yes``
     - off
     - Escape hatch to skip the confirmation prompt. Prefer answering
       ``y`` at the prompt in normal interactive use.

Confirmation Prompt
-------------------

Before discovering FITS files, the CLI prints a warning with the current
working directory and the grouping mode, then asks:

.. code-block:: text

   WARNING: DISCO will now scan for and process FITS files.
   Current directory: /path/to/your/fits
   Grouping mode (--group): file
   ------------------------------------------------------------
   Are you sure you want to continue? [y/N]:

Answer ``y`` or ``yes`` to proceed, or anything else to cancel. The prompt
is intentional so users confirm before FITS scanning begins. Prefer running
the CLI from the directory that contains your science FITS (or pass explicit
paths); a bare ``disco-start`` walks the current directory tree.

Grouping (``--group``)
----------------------

A *group* shares one geometry solution and, if ``--homobeam on``, one
homogenisation beam. DISCO does **not** infer your folder layout: you
choose the mode.

.. list-table::
   :header-rows: 1
   :widths: 18 42 40

   * - ``--group``
     - Meaning
     - When to use
   * - ``file`` (default)
     - Each ``.fits`` file is its own group.
     - Safest. A flat folder of unrelated sources, or you do not want
       mixed maps homogenised together.
   * - ``dir``
     - All FITS **directly** in the same folder are one group. Nested
       directories stay separate (``AS209/*.fits`` vs
       ``HD163296/*.fits``).
     - One object per folder, with several bands or methods
       (``robust0``, PRIISM, Band 6/7, …).
   * - ``name``
     - Legacy: inside each folder, split stems on ``BandN`` /
       ``_Band6`` / ``band7``. Tokens such as ``B6_`` or ``priism_b6``
       are **not** split.
     - Old ``Object_Band6.fits`` naming only.

v1.2.5 always used the ``name`` heuristic. From **v1.2.6** the default is
``file`` so unrelated cubes in one directory are not treated as one
source. Name filters still apply on top: ``disco-start AS209 --group dir``
keeps groups whose paths or filenames contain ``AS209``.

.. code-block:: bash

   # Each FITS separately (default)
   disco-start /data/batch/ --group file

   # One object folder with Band 6, Band 7, PRIISM, robust 0, …
   disco-start /data/AS209/ --group dir --ref robust0.fits

   # Parent directory: one subdirectory per source
   disco-start /data/sample/ --group dir

   # Legacy Object_Band6.fits naming (v1.2.5 behaviour)
   disco-start /data/fits/ --group name

Geometry reference (``--ref``)
------------------------------

In a **multi-file group**, DiscoNet + hybrid (and Rout / centre) run on
**one** map. Without ``--ref``, that map is the highest
:math:`\mathrm{SNR}/\Omega_{\mathrm{beam}}^{3/2}`. Cropped restorations
(PRIISM, super-resolution) can win that score even when they are a poor
CNN prior.

``--ref`` pins the geometry image inside **each** group:

* basename — ``--ref robust0.fits``
* unique substring — ``--ref Band6`` (error if 0 or 2+ files match)
* path — ``--ref /data/AS209/robust0.fits``

Other files in the group still get homogenisation (if enabled) and
profiles **using that geometry**. If both ``--incl`` and ``--pa`` are
set, those angles override the fit; ``--ref`` still selects the map for
centre / Rout. The CLI logs ``[INFO] Geometry reference: <filename>``.

Usage Examples
--------------

.. code-block:: bash

   # Prefer: cd into the folder with your FITS first
   cd /path/to/your/fits/

   # Each FITS separately (default since v1.2.6)
   disco-start --group file

   # Process a single object by name prefix
   disco-start AS209 --group file

   # One folder = one source (multi-band / multi-method)
   disco-start path/to/AS209/ --group dir --ref robust0.fits

   # Process a FITS file directly
   disco-start path/to/disk.fits

   # Force inclination and PA, export CSV, enable debug output
   disco-start AS209 --incl 35.0 --pa 120.0 --csv on --debug on --group dir

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
