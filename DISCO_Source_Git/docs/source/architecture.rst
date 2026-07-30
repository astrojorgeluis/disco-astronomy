.. _architecture:

Architecture
============

Repository Structure
--------------------

.. code-block:: text

   disco-astronomy/
   ├── disco/                     # Installable Python package
   │   ├── main.py                # Entry-point dispatcher (disco-start)
   │   ├── cli.py                 # Automated pipeline (CLI mode)
   │   ├── server/                # FastAPI backend (GUI mode)
   │   │   ├── app.py             # App factory, lifespan, launcher
   │   │   ├── session.py         # Multi-image SessionStore
   │   │   ├── schemas.py
   │   │   ├── render_utils.py    # Publication matplotlib renderers
   │   │   └── routers/           # images, analysis, render, catalogs, session
   │   ├── static/                # Pre-built React frontend
   │   ├── models/                # DiscoNet weights
   │   └── core/                  # Pure science (no FastAPI)
   │       ├── fits_io.py
   │       ├── fits_utils.py      # Compatibility re-exports
   │       ├── units.py
   │       ├── beams.py
   │       ├── geometry.py
   │       ├── profiles.py        # Shared analysis pipeline
   │       ├── regions.py
   │       ├── optimization.py
   │       └── cnn_inference.py
   ├── client/                    # React frontend (Vite)
   │   └── src/
   │       ├── app/shell/
   │       ├── theme/
   │       ├── state/store.js     # zustand
   │       ├── api/client.js
   │       ├── panels/
   │       ├── viewer/            # Colormaps + raster layer
   │       └── ui/
   ├── tests/                     # pytest + golden files
   ├── training/
   └── pyproject.toml

Module Relationships
--------------------

.. code-block:: text

   disco-start
       └── disco.main:run()
               ├── GUI → disco.server.app
               │         ├── SessionStore (multi-image)
               │         ├── disco.core.profiles.run_analysis_pipeline
               │         ├── disco.core.optimization
               │         ├── disco.core.regions
               │         └── astroquery.simbad (optional)
               └── CLI → disco.cli
                         ├── disco.core.cnn_inference
                         ├── disco.core.optimization
                         └── disco.core.fits_utils / profiles / fits_io

Design Principles
-----------------

* **One science core.** CLI and GUI call the same deprojection / profile
  routines so numerical results match.
* **Interactive vs publication rendering.** Interactive views use client-side
  rasters (float32 pixels); matplotlib is reserved for publication figures.
* **Local-only server.** The GUI binds to ``127.0.0.1``.
* **Session durability.** Uploads are not wiped on soft reset so JSON session
  restore can reload FITS files from ``.disco_uploads``.
