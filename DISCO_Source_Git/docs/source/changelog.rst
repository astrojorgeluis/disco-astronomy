.. _changelog:

Changelog
=========

Version 1.2.4 (current)
-----------------------

GUI, CLI, backend robustness, and documentation sync.

GUI
~~~

* Replace the bare ``Run pipeline...`` placeholder with a Blueprint
  ``NonIdealState`` and clearer empty-state messaging.
* Persist colormap / stretch / intensity limits across pipeline re-runs,
  Auto-Tune, ring-range updates, and view-tab changes.
* Align default colormap with the pipeline render (``inferno``).
* Help opens the online documentation; toolbar labels match the docs
  (Ellipse Tool, Pan, Inspector, Close).
* Refresh / tab close clears the server session (also via Close / Exit).
* Status pill in the header (Idle / Ready / Running).
* Matplotlib plotter: beam overlay, fixed layout when toggling contours,
  and contour percentiles or N evenly spaced levels.
* Remove fabricated Inspector sky-offset cards.

Backend
~~~~~~~

* Safer FITS load: first image HDU, squeeze cubes to a 2D plane, clear
  analysis state on new upload.
* Guard missing/zero ``CDELT2`` with a warning and sane fallback.
* Actionable errors for pipeline/optimization failures; SIMBAD timeout
  and offline-friendly messaging.
* Path-safe uploads and static file serving; refuse to start GUI if
  ``disco/static`` was not built.

CLI
~~~

* CSV column labels report brightness temperature (K) when that is what
  is written.
* ``--yes`` / ``-y`` skips the scan confirmation; non-TTY requires ``--yes``.
* Direct ``.fits`` paths and directory paths are supported; identifier
  matching is case-insensitive.
* Warn when ``--incl`` / ``--pa`` are unpaired; degrade CNN path when
  ``BMAJ`` is missing; fix empty-crop return arity.

Docs / packaging
~~~~~~~~~~~~~~~~

* Correct Auto-Tune (incl/PA/center), dynamic port, CORS, SIMBAD, overlays,
  and ``npm run build`` (not ``build:disco`` on v1).
* Sphinx assets restored; BibTeX cite-key fixed; versions aligned to 1.2.4.
* Minimal pytest suite and GitHub Actions CI (tests + frontend build).


Version 1.2.3
-------------

Previous published PyPI version. See repository history for details.


Version 1.2.2
-------------

Zenodo DOI / citation integration release (GitHub Release ``v1.2.2``).


.. note::

   DISCO is currently in active development. Features and interfaces may
   change between releases. Consult the
   `GitHub repository <https://github.com/astrojorgeluis/disco-astronomy>`_
   for the latest changes.
