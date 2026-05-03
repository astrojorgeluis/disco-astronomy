.. _api-main:

``disco.main``
==============

.. module:: disco.main
   :synopsis: Entry-point dispatcher for the disco-start console script.

This module contains the single function registered as the ``disco-start``
console-script entry point in ``pyproject.toml``.

----

.. function:: run()

   Dispatch execution to either the GUI server or the CLI pipeline based on
   the first command-line argument.

   If ``sys.argv[1].lower() == "gui"``, imports and calls
   :func:`disco.server.start_server`. Otherwise, imports and calls
   :func:`disco.cli.main`.

   Imports are deferred to avoid loading heavy GUI dependencies (FastAPI,
   Uvicorn, Matplotlib) when only the CLI is required, and vice versa.

   This function is the sole entry point for all DISCO functionality and is
   mapped in ``pyproject.toml`` as:

   .. code-block:: toml

      [project.scripts]
      disco-start = "disco.main:run"
