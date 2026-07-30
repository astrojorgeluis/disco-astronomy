.. _changelog:

Changelog
=========

Version 1.3.0 (current)
-----------------------

Major architecture and GUI rework while preserving CLI and GUI modes.

* Unified science core shared by CLI and GUI (``disco.core.profiles``,
  ``geometry``, ``fits_io``, ``units``, ``beams``, ``regions``).
* Modular FastAPI package (``disco.server``) with multi-image sessions,
  ``/api`` prefix, pixel streaming, region statistics, and session restore.
* CARTA-like Blueprint v6 design system with a single blue accent.
* Client-side raster rendering, WCS cursor probe, region tools,
  multi-image list, figure builder, and reproducibility panel.
* Pytest regression suite with golden files, Ruff linting, and GitHub Actions CI.
* Binding address fixed to ``127.0.0.1``; upload path traversal hardened.
* Derived FITS exports use product-specific headers (no longer copy invalid WCS).
* Single geometry convention: ``cx``/``cy`` are FITS array coordinates
  (origin lower-left) across core, API and client, and the position angle drawn
  by the client matches the deprojection and the optimizer.
* Analysis products share one square FOV derived from ``Rout``; the source crop
  covers the whole deprojected grid, so inclined disks no longer show a rotated
  square of valid data, and uncovered pixels are NaN (transparent) instead of 0.

Version 1.2.3
-------------

Previous documented release prior to the 1.3 architecture rework.

.. note::

   DISCO is currently in active development. Features and interfaces may
   change between releases. Consult the
   `GitHub repository <https://github.com/astrojorgeluis/disco-astronomy>`_
   for the latest changes.
