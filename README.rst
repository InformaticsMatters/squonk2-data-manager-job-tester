Informatics Matters Job Tester
==============================

.. image:: https://badge.fury.io/py/im-jote.svg
   :target: https://badge.fury.io/py/im-jote
   :alt: PyPI package (latest)

The Job Tester (``jote``) is used to run unit tests located in
Data Manager Job implementation repositories against the Job's
container image.

Job implementations are required to provide at least one manifest file
that lists Job Definition files (these reside in the ``data-manager``
of the repository being tested). The default manifest file is
``manifest.yaml`` but you can name your own and have more than one.

Each Manifest must name at least one file and the corresponding
Job Definition file should define at least one test for every Job.
``jote`` runs the tests but also ensures the repository structure is as
expected and applies strict formatting of the YAML files.

Here's a snippet from a Job definition file illustrating a
Job (``max-min-picker``) with a test called ``simple-execution``.

The test defines an input option (a file) and some other command options.
The ``checks`` section is used to define the exit criteria of the test.
In this case the container must exit with code ``0`` and the file
``diverse.smi`` must be found (in the mounted project directory), i.e
it must *exist* and contain ``100`` lines. ``jote`` will ensure that these
expectations are satisfied::

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

Running tests
-------------

Run ``jote`` from the root of a clone of the Data Manager Job implementation
repository that you want to test::

    jote

You can display the utility's help with::

    jote --help

Built-in variables
------------------

Job definition command-expansion relies on a number of *built in* variables.
Some are provided by the Data Manager when the Job runs under its control
(i.e. ``DM_INSTANCE_DIRECTORY``) others are built-in to ``jote``.

The set of variables injected into the command expansion by ``jote``
are: -

- ``DM_INSTANCE_DIRECTORY``. Set to the path of the simulated instance
  directory created by ``jote``
- ``CODE_DIRECTORY``. Set to the root of the repository clone under test

Ignoring tests
--------------

Individual tests can be prevented from being executed by adding an `ignore`
declaration::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            ignore:
            [...]

Test run levels
---------------
Tests can be assigned a ``run-level``. Run-levels are numerical value (1..100)
that can be used to classify your tests, often using it to represent
execution time. By default all tests that have no run-level and those with
run-level ``1`` are executed. You can set the run-level for longer-running
tests higher value, e.g. ``10``. To run these more time-consuming tests you
specify the new run-level when running jote: ``jote --run-level 10``.

You define the run-level in the root block of the job specification::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            run-level: 5
            [...]

Test timeouts
-------------

``jote`` lets each test run for 10 minutes before cancelling (and failing) them.
If you expect your test to run for more than 10 minutes you can use the
``timeout-minutes`` property to define your own test-specific value::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            timeout-minutes: 120
            [...]

Remember that job tests are *unit tests*, so long-running tests should be
discouraged.

Nextflow execution
------------------
Job image type can be ``simple`` or ``nextflow``. Simple jobs are executed in
the container image you've built and should behave much the same as they do
when run within the Data Manager. Nextflow jobs on the other hand are executed
using the shell, relying on Docker as the execution run-time for the processes
in your workflow.

be aware that nextflow tests run by ``jote`` run under different conditions
compared to those running under the Data Manager's control, where nextflow
will be executed within a Kubernetes environment rather than docker. This
introduces variability. Tests that run under ``jote`` *are not* running in the
same environment or under the same memory or CPU constraints. Remember this
when testing - i.e. a successful nextflow test under ``jote`` does not
necessarily mean that it will execute successfully within the Data Manager.
Successful nextflow tests run with ``jote`` are just and indication that
the same execution might work in the Data Manager.

It's your responsibility to provide a suitable nextflow for shell execution,
which ``jote`` simply uses when executing the test's ``command`` that's
defined in your Job definition.

When running nextflow jobs ``jote`` writes a ``nextflow.config`` to the
test's simulated project directory prior to executing the command.
``jote`` *will not* let you have a nextflow config in your home directory
as any settings found there would be merged with the file ``jote`` writes,
potentially disturbing the execution behanviour.

Installation
============

``jote```` is published on `PyPI`_ and can be installed from
there::

    pip install im-jote

This is a Python 3 utility, so try to run it from a recent (ideally 3.10)
Python environment.

To use the utility you will need to have installed `Docker`_.

.. _PyPI: https://pypi.org/project/im-jote/
.. _Docker: https://docs.docker.com/get-docker/

Get in touch
------------

- Report bugs, suggest features or view the source code `on GitHub`_.

.. _on GitHub: https://github.com/informaticsmatters/data-manager-job-tester
