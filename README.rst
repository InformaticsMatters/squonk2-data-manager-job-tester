Informatics Matters Job Tester
==============================

The Job Tester (``jote``) is used to run unit tests located in
Data Manager Job implementation repositories against the Job's
container image.

Job implementations are required to provide a Job Definition (in the
Job repository's ``data-manager`` directory) and at least one test, located in
the repository's ``data-manager/tests`` directory. ``jote`` runs the tests
but also ensures the repository structure meets the Data Manager requirements.

Tests are dined in the Job definition file in the block where the the test
is defined. Here's a snippet illustrating a test called ``simple-execution``
that defines an input option defining a file and some other command
options along with a ``checks`` section that defines the exit criteria
of a successful test::

    jobs:
      [...]
      shard:
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
                exists: true
                lineCount: 100

Installation
------------

Pyconf is published on `PyPI`_ and can be installed from
there::

    pip install im-jote

This is a Python 3 utility, so try to run it from a recent (ideally 3.10)
Python environment.

To use the utility you will need to have installed `Docker`_
and `docker-compose`_.

.. _PyPI: https://pypi.org/project/im-jote/
.. _Docker: https://docs.docker.com/get-docker/
.. _docker-compose: https://pypi.org/project/docker-compose/

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
