.. _quickstart:

Quick Start
===========

DISCO is invoked through its single entry point, ``disco-start``, which is
registered as a console script by the package. Its behaviour is determined
by the first argument: if the literal string ``gui`` is supplied, the GUI
server is launched; any other argument (or no argument) delegates to the
CLI automated pipeline.

This routing logic is implemented in :mod:`disco.main`:

.. code-block:: python

   # disco/main.py
   def run():
       if len(sys.argv) > 1 and sys.argv[1].lower() == "gui":
           from disco.server import start_server
           start_server()
       else:
           from disco.cli import main
           main()

.. note::

   **Which mode should I use?**

   The **GUI** is recommended for exploratory analysis and first-time users.
   It provides interactive sliders, real-time visualisation, and point-and-click
   geometry tuning with no scripting required.

   The **CLI** is designed for reproducible, automated pipelines. It supports
   batch processing of multiple targets, beam homogenisation, CNN-seeded geometry
   optimisation, and structured CSV output — all without any browser interaction.

   See :ref:`architecture` for a feature-by-feature comparison of the two modes.

----

Interactive GUI Mode
--------------------

Launch the web interface for interactive, parameter-driven analysis:

.. code-block:: bash

   disco-start gui

This command starts a local `Uvicorn <https://www.uvicorn.org/>`_ server on
the first free TCP port starting at 8000 (check the terminal for the URL),
opens a browser window automatically after a short delay, and serves the
pre-built React application bundled in ``disco/static/``.

Once running, load a FITS file using the folder icon in the toolbar.
The interface provides four view modes — **Deprojection**, **Model**,
**Residuals**, and **Polar** — as well as interactive geometry controls and
1D radial profile charts. See :ref:`gui` for a complete description of the
interface and a step-by-step workflow guide.

Stop the server with ``Ctrl+C``.

----

Automated CLI Mode
------------------

For batch processing, **change into the directory that contains your FITS
files** (or pass explicit paths). With no identifier, the CLI scans the
current working directory tree — avoid running it from your home folder or
another broad path.

.. code-block:: bash

   cd /path/to/your/fits/

   # Process a named object (each matching FITS separately by default)
   disco-start AS209

   # One folder = one source; choose the geometry image with --ref
   disco-start path/to/AS209/ --group dir --ref continuum.fits

   # Provide a direct path to a FITS file
   disco-start path/to/disk.fits

   # Force geometric parameters and enable CSV export
   disco-start AS209 --incl 35.0 --pa 120.0 --csv on

   # Set outer radius and disable beam homogenisation
   disco-start AS209 --rout 1.2 --homobeam off

   # Specify a custom homogenisation beam size and enable debug output
   disco-start AS209 Elias29 --homobeam on --beam 0.15 --debug on

The pipeline discovers FITS files and groups them according to ``--group``
(default ``file``: one FITS per group). Use ``--group dir`` when several
maps of the **same** object live in one folder. See :ref:`cli` for
``--group`` / ``--ref``. Each group runs a five-phase sequence: FITS
ingestion, geometry optimisation, uncertainty estimation, radial profile
extraction, and result serialisation. See :ref:`pipeline` for each phase.

Before scanning, the CLI prints a warning with the current working directory
and asks for confirmation (``Are you sure you want to continue? [y/N]``).
Answer ``y`` / ``yes`` to proceed. This prompt is intentional — do not skip
it in normal interactive use, and check that the printed directory is the
data folder you intend to scan.
