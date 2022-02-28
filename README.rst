Informatics Matters Job Tester
==============================

.. image:: https://badge.fury.io/py/im-jote.svg
   :target: https://badge.fury.io/py/im-jote
   :alt: PyPI package (latest)

The Job Tester (``jote``) is used to run unit tests located in
Data Manager Job implementation repositories against the Job's
container image.

Job implementations are required to provide a Manifest file (``manifest.yaml``)
that lists Job Definition files (in the Job repository's ``data-manager``
directory). The Manifest names at least ine file and the Job Definition
should define at least one test for every Job. ``jote`` runs the tests
but also ensures the repository structure meets the Data Manager requirements.

Tests are defined in the Job definition file. Here's a snippet illustrating a
Job (``max-min-picker``) with a test called ``simple-execution``.

The test defines an input option (a file) and some other command options.
The ``checks`` section defines the exit criteria of a successful test.
In this case the container must exit with code ``0`` and the file
``diverse.smi`` must be found (in the mounted project directory), i.e
it must *exist* and contain ``100`` lines::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            inputs:
              inputFile: data/100000.smi
            options:
              outputFile: diverse.smi
              count: 100
            checks:
              exitCode: 0
              outputs:
              - name: diverse.smi
                checks:
                - exists: true
                - lineCount: 100
Individual tests can be prevented from being processed by adding an `ignore`
declaration::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            ignore:
            [...]


Installation
------------

Pyconf is published on `PyPI`_ and can be installed from
there::

    pip install im-jote

This is a Python 3 utility, so try to run it from a recent (ideally 3.10)
Python environment.

To use the utility you will need to have installed `Docker`_.

.. _PyPI: https://pypi.org/project/im-jote/
.. _Docker: https://docs.docker.com/get-docker/

Running tests
-------------

Run ``jote`` from the root of a clone of the Data Manager Job implementation
repository that you want to test::

    jote

You can display the utility's help with::

    jote --help

Get in touch
------------

- Report bugs, suggest features or view the source code `on GitHub`_.

.. _on GitHub: https://github.com/informaticsmatters/data-manager-job-tester
