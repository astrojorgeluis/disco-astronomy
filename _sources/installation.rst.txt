.. _installation:

Installation
============

Requirements
------------

DISCO requires **Python ≥ 3.9** and the following dependencies, which are
declared in ``pyproject.toml`` and resolved automatically by pip:

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Package
     - Minimum version
     - Role
   * - ``fastapi``
     - ≥ 0.110.0
     - HTTP backend for the GUI server
   * - ``uvicorn[standard]``
     - ≥ 0.29.0
     - ASGI server used to run FastAPI
   * - ``python-multipart``
     - —
     - Multipart form-data parsing (file upload)
   * - ``astropy``
     - ≥ 6.0.0
     - FITS I/O, WCS, coordinate transforms, unit handling
   * - ``scipy``
     - ≥ 1.11.0
     - Numerical optimisation, image interpolation, signal processing
   * - ``matplotlib``
     - ≥ 3.8.0
     - Scientific figure rendering (server-side, Agg backend)
   * - ``astroquery``
     - ≥ 0.4.7
     - Gaia DR3 proper-motion queries and SIMBAD object metadata
   * - ``numpy``
     - < 2.0.0
     - Numerical array operations (pinned below 2.0 for compatibility)
   * - ``torch``
     - ≥ 2.0.0
     - PyTorch — DiscoNet CNN inference
   * - ``tqdm``
     - ≥ 4.66.0
     - Progress reporting in the CLI pipeline

Installation from PyPI
----------------------

The recommended installation method uses pip inside a dedicated virtual
environment to avoid dependency conflicts.

.. code-block:: bash

   # 1. Create and activate a virtual environment
   python -m venv disco-env
   source disco-env/bin/activate        # Linux / macOS
   disco-env\Scripts\activate           # Windows

   # 2. Install DISCO from PyPI
   pip install disco-astronomy

   # 3. Verify the installation
   disco-start --help

The package is distributed under the name ``disco-astronomy`` on PyPI:
https://pypi.org/project/disco-astronomy/

Keeping DISCO up to date
------------------------

.. code-block:: bash

   pip install --upgrade disco-astronomy

Included Static Assets
----------------------

The ``MANIFEST.in`` specifies that the following directories are bundled
with the source distribution:

* ``disco/static/`` — pre-built React frontend (``index.html`` and assets)
* ``disco/models/`` — pre-trained DiscoNet weight file
  (``disco_model_stable.pth``)

These assets are required at runtime and are installed automatically via pip.
If the model file is absent from ``disco/models/``, the CLI pipeline falls
back to analytical geometry optimisation without CNN priors (see :ref:`analytical fallback <cli-geometry-fallback>`).
