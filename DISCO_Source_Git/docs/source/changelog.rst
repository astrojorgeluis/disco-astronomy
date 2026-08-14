.. _changelog:

Changelog
=========

Version 1.2.6 (current)
-----------------------

CLI grouping is explicit: ``--group file|dir|name`` and ``--ref`` for the
geometry map. Default ``--group file`` no longer mixes unrelated FITS via
the old ``BandN`` filename heuristic.

* ``--group file`` (default): one group per FITS file.
* ``--group dir``: all FITS directly in the same folder are one group
  (nested directories remain separate).
* ``--group name``: legacy split on ``BandN`` / ``_Band6`` in the stem.
* ``--ref`` selects the CNN + hybrid (and Rout / centre) image inside a
  group by filename, unique substring, or path; must match exactly one
  file. ``--incl`` + ``--pa`` still override fitted angles.
* Docs / README explain grouping and ``--ref``; confirmation prompt still
  prints the grouping mode.


Version 1.2.5
-------------

DiscoNet synthetic training release, hybrid geometry polish, GUI refresh,
and docs sync.

CNN / training
~~~~~~~~~~~~~~

* Shared preprocess module ``disco.core.cnn_preprocess`` (percentiles,
  elliptical beam map, scale map, label encode/decode) used by train and
  inference.
* Packaged weights retrained **synthetic-only** (20k crops, elliptical
  beams, early-stop best ≈ epoch 64). Mixed CASA+synth did not improve
  literature metrics; synth weights are shipped.
* ``train_model.py``: object-ID split, mixup without blending PA sin/cos,
  AMP, early stopping, FOV-normalised center labels.

CLI / geometry
~~~~~~~~~~~~~~

* Hybrid refinement uses **L-BFGS-B** (bounds respected).
* ``estimate_geometry_errors``: parabolic loss-curvature :math:`\pm`
  documented as fit-quality indicator (not literature :math:`1\sigma`).
* Beam / FITS robustness: elliptical beam channel, RESTFRQ helpers,
  spacing tests.
* CLI debug deprojection PNG uses the same sky-aligned sampling as the GUI
  (North up; no empty-corner post-rotation).

GUI
~~~

* FOV slider (arcsec) wired into ``/run_pipeline``; Radius Out capped by
  FOV/2 with a stable slider track (FOV changes no longer nudge Rout).
* Default stretch **linear**; default FOV ≈ half map side with nice rounding.
* Sky-aligned deprojected / model / residual maps (North up) without
  corner cropping.
* Layout: File Header | Image Viewer + Render Configuration | Scientific
  Analysis; JetBrains Mono; slate/violet palette; brand accent ``#a44aff``.
* Ellipse-handle tip no longer flips during PA drag; Image Viewer zoom
  preserved across mosaic resize after user adjustment.
* Faster Image Viewer preview: block-downsample large FITS before PNG
  (exports / Matplotlib / FITS download remain full quality).
* Status pill shows **Loading…** while opening heavy FITS; Auto-Tune still
  re-runs the pipeline with the refined geometry.
* Matplotlib widget: FOV crop control; beam PA corrected for RA-left plots.
* Analysis Settings: contour percentiles or N levels (same options as
  Matplotlib). GUI Auto-Tune documented as approximate (not the CLI hybrid).

Docs / packaging
~~~~~~~~~~~~~~~~

* Training docs describe the v1.2.5 synthetic recipe and optional CASA path.
* Pipeline / API docs aligned with L-BFGS-B hybrid path.
* Citation uses the Zenodo all-versions DOI ``10.5281/zenodo.19999239``
  (resolves to the latest release; no Software Heritage id yet).
* GUI: ``npm run build`` writes to ``disco/static`` (Vite ``outDir``).
* Version bump to 1.2.5.


Version 1.2.4
-------------

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
