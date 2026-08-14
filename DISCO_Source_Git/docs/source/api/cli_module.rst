.. _api-cli-module:

``disco.cli``
=============

.. module:: disco.cli
   :synopsis: Automated CLI pipeline for batch FITS processing.

This module contains the full implementation of the DISCO automated pipeline,
including FITS file discovery, group management, and the five-phase processing
function. It is invoked when ``disco-start`` is called without the ``gui``
argument.

----

.. function:: discover_groups(base_dir, mode="file")

   Traverse the directory tree rooted at ``base_dir`` and group FITS files.

   ``mode`` is ``file`` (one group per FITS, default), ``dir`` (all FITS
   directly in the same folder), or ``name`` (legacy ``BandN`` prefix split).

   :param str base_dir: Root directory to search.
   :param str mode: Grouping mode (``file``, ``dir``, or ``name``).
   :returns: List of group dictionaries, each with keys:
             ``"name"`` (str), ``"files"`` (list of str),
             ``"output_dir"`` (str).
   :rtype: list[dict]

.. function:: resolve_geometry_ref(temp_data, ref)

   Return the unique index in ``temp_data`` matching ``--ref`` (path,
   basename, or unique substring). Raises ``ValueError`` if the match
   count is not exactly one.

.. function:: run_pipeline(files_to_process, group_name, output_dir, args, cnn_model)

   Execute the five-phase DISCO pipeline for a single group of FITS files.

   :param list files_to_process: Ordered list of FITS file paths.
   :param str group_name: Human-readable group identifier (used in output
                           filenames).
   :param str output_dir: Directory where output files are written.
   :param argparse.Namespace args: Parsed command-line arguments. Relevant
                                    attributes: ``rout``, ``rmin``, ``incl``,
                                    ``pa``, ``beam``, ``homobeam``, ``csv``,
                                    ``debug``, ``yes``, ``group``, ``ref``.
   :param DiscoNet | None cnn_model: Pre-loaded DiscoNet model, or ``None``
                                      to use analytical-only geometry.

   Writes the following files to ``output_dir``:

   * ``RP_<group_name>.PNG`` — normalised radial profile plot
   * ``RP_<group_name>_global.csv`` (if ``--csv on``)
   * ``RP_<group_name>_bands.csv`` (if ``--csv on``)
   * ``RP_<group_name>_profile.csv`` (if ``--csv on``)
   * ``debug_pipeline/<group_name>_debug_center_rout.png`` (if ``--debug on``)

.. function:: main()

   Parse command-line arguments and orchestrate the full pipeline execution
   across all matched groups. Before scanning, prints a confirmation prompt
   (``Are you sure you want to continue? [y/N]``); answer ``y`` / ``yes`` to
   proceed. The prompt is intentional for interactive use. Identifiers may be object name prefixes, directory paths, or direct
   ``.fits`` paths. Loads the DiscoNet model once before iterating over
   groups. Groups are processed sequentially with a ``tqdm`` outer progress
   bar. Processing failures for individual groups are logged but do not
   abort the remaining groups.
