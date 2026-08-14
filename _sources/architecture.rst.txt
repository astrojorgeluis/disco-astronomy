.. _architecture:

Architecture
============

Repository Structure
--------------------

The DISCO repository is organised into three top-level namespaces:

.. code-block:: text

   disco-astronomy/
   ├── disco/                     # Installable Python package
   │   ├── __init__.py
   │   ├── main.py                # Entry-point dispatcher (disco-start)
   │   ├── cli.py                 # Automated pipeline (CLI mode)
   │   ├── server.py              # FastAPI backend (GUI mode)
   │   ├── static/                # Pre-built React frontend (bundled asset)
   │   ├── models/                # Serialised DiscoNet weights (bundled asset)
   │   └── core/
   │       ├── __init__.py
   │       ├── cnn_inference.py   # DiscoNet architecture & inference helper
   │       ├── cnn_preprocess.py  # Shared CNN crop / beam / label encode-decode
   │       ├── fits_utils.py      # FITS I/O, beam utilities, WCS helpers
   │       └── optimization.py    # Geometric loss & hybrid optimiser
   ├── client/                    # React frontend source (Vite project)
   │   └── src/
   │       ├── App.jsx            # Root component, mosaic layout, global state
   │       ├── main.jsx           # React DOM mount point
   │       ├── InteractiveViewer.jsx
   │       ├── SimpleImageViewer.jsx
   │       ├── MatplotlibWidget.jsx
   │       └── components/
   │           └── AnalysisDashboard.jsx
   ├── training/                  # Training utilities (not installed)
   │   └── train_model.py         # DiscoNet synthetic training loop
   ├── pyproject.toml
   ├── MANIFEST.in
   └── README.md

Module Relationships
--------------------

The following diagram summarises the runtime dependency graph between
the primary Python modules.

.. code-block:: text

   disco-start (console_scripts entry point)
       └── disco.main:run()
               ├── GUI branch ──────────────────────────────────────────────┐
               │       disco.server (FastAPI app)                           │
               │           ├── disco.core.optimization.geometric_loss       │
               │           └── astroquery.simbad (optional)                 │
               └── CLI branch                                               │
                       disco.cli:main()                                     │
                           ├── disco.core.cnn_inference                     │
                           │       DiscoNet, predict_with_cnn               │
                           ├── disco.core.cnn_preprocess                    │
                           ├── disco.core.optimization                      │
                           │       geometric_loss                           │
                           │       auto_tune_geometry_hybrid                │
                           │       estimate_geometry_errors                 │
                           │       refine_center_geometry                   │
                           └── disco.core.fits_utils                        │
                                   get_alma_beam                            │
                                   deconvolve_beams                         │
                                   make_gaussian_kernel_casa                │
                                   find_center_robust                       │
                                   auto_detect_parameters                   │
                                   extract_profile                          │
                                   save_debug_deproj_center                 │
                                   measure_rout_deproj                      │
                                   refine_center_local                      │
                                   deg_to_sex                               │
                                   pixel_to_icrs / icrs_to_pixel            │
                                   get_obs_epoch                            │
                                   query_gaia_proper_motion                 │
                                   apply_proper_motion_correction           │
                                                                            │
   React SPA (served from disco/static/) ←────────────────────────────────┘
       communicates via HTTP with disco.server on localhost (first free port from 8000)

Operational Modes
-----------------

CLI Pipeline (``disco-start <identifier ...>``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The CLI pipeline (implemented in :mod:`disco.cli`) operates entirely
server-side without any browser interaction. It discovers FITS files
under the working directory (or paths you pass), groups them according to
``--group`` (default: one file per group), and processes each group through
a five-phase sequence. The CNN model is loaded once at startup and reused
across all groups. Results are written to disk as PNG figures and, optionally, CSV files.

GUI Server (``disco-start gui``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In GUI mode, :func:`disco.server.start_server` initialises a FastAPI
application backed by Uvicorn. A global singleton ``state`` object
(an instance of ``GlobalState``) holds the currently-loaded FITS array,
header, and pipeline results in memory for the duration of the session.
The React single-page application communicates with the backend exclusively
through REST endpoints documented in :ref:`api-server`.

The React build artefact is served as static content from ``disco/static/``
via FastAPI's ``StaticFiles`` mount and a catch-all route that returns
``index.html`` for any unmatched path, enabling client-side routing.

Frontend Build Pipeline
-----------------------

The React application (located in ``client/``) is built with
`Vite <https://vitejs.dev/>`_. The ``vite.config.js`` configures the
output directory as ``../disco/static``, replacing the installed static
assets in place:

.. code-block:: bash

   # From client/
   npm ci && npm run build

The Vite ``outDir`` is ``../disco/static``. ``npm run build:disco`` is an alias
for the same command.

The resulting bundle is shipped as part of the ``disco-astronomy`` PyPI
distribution via ``MANIFEST.in`` / package-data
``recursive-include disco/static *`` (build the frontend before ``python -m build``).
