Informatics Matters Job Tester ("jote")
=======================================

.. image:: https://badge.fury.io/py/im-jote.svg
   :target: https://badge.fury.io/py/im-jote
   :alt: PyPI package (latest)

The **Squonk2 Job Tester** (``jote``) is a Python utility used to run *unit tests*
that are defined in Data Manager *job implementation repositories* against
the job's container image, images that are typically built from the same
repository.

``jote`` is designed to run job implementations in a file-system
environment that replicates what they find when they're run by the Data Manager.
But jobs *are not* running in the same operating-system environment, e.g. they
are not bound by the same processor and memory constraints they'll encounter in
the Data Manager, which runs in `Kubernetes`_.

A successful test should give you confidence that it *should* work in the
Data Manger but without writing a lot of tests you'll never be completely
confident that it will always run successfully.

``jote`` is a tool we designed to provide *us* with confidence that we can
deploy jobs to a Data Manager instance and know that they're basically fit
for purpose. Jobs that have no tests will not normally be deployed to the
Data Manager.

To use a job in Squonk you need to create at least one **manifest file** and
one **job definition file**. These reside in the ``data-manager``
directory of the repository you're going to test. ``jote`` expects the
default manifest file to be called ``manifest.yaml`` but you can use a
different name and have more than one.

    If you want to provide your own Squonk jobs and corresponding
    job definitions our **Virtual Screening** repository
    (https://github.com/InformaticsMatters/virtual-screening) is a good
    place to start. The repository is host to a number of job-based
    container images and several *manifests* and *job definition files*.

Here's an example **manifest** from a recent **Virtual Screening** repository::

    ---
    kind: DataManagerManifest
    kind-version: '2021.1'

    job-definition-files:
    - im-virtual-screening.yaml
    - rdkit.yaml
    - xchem.yaml

Each Manifest must list at least one file. To be included in Squonk every
job must contain at least one test. ``jote`` runs the tests but also ensures
the repository structure is as expected and applies strict rules for the
formatting of the YAML files.

Both ``jote`` and the Data Manager rely on the schemas that can be found
in our **Job Decoder** repository
(https://github.com/InformaticsMatters/data-manager-job-decoder).

Here's a snippet from a job definition file illustrating a
job (``max-min-picker``) that has a test called ``simple-execution``.

The test defines an input option (a file) and some other command options.
The ``checks`` section is used to define the exit criteria of the test.
In this case the container must exit with code ``0`` and the file
``diverse.smi`` must be found in the generated test directory, i.e
it must *exist* and contain ``100`` lines. ``jote`` will fail the test unless
these checks are satisfied::

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

.. _kubernetes: https://kubernetes.io/

Running tests
-------------

Run ``jote`` from the root of a clone of the Data Manager Job implementation
repository that you want to test::

    jote

You can display the utility's help with::

    jote --help

Jote container network
----------------------

``jote`` tests are executed on the network ``data-manager_jote``. This is
defined in the docker-compose file that it generates to run your tests.

Built-in variables
------------------

Job definition command-expansion provided by the **job decoder**
relies on a number of *built in* variables. Some are provided by the
Data Manager when the job runs under its control
(i.e. ``DM_INSTANCE_DIRECTORY``) others are provided by ``jote`` to simplify
testing.

The set of variables injected into the command expansion by ``jote``
are: -

- ``DM_INSTANCE_DIRECTORY``. Set to the path of the simulated instance
  directory created by ``jote``, normally created by the Data Manager
- ``CODE_DIRECTORY``. Set to the root of the repository that you're running
  the tests in. This is a convenient variable to locate your out-of-container
  nextflow workflow file, which is likely to be in the root of your repository

Ignoring tests
--------------

Occasionally you may want to disable some tests because they need some work
before they're complete. To allow you to continue testing other jobs under
these circumstances you can mark individual tests and have them excluded
by adding an ``ignore`` declaration::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            ignore:
            [...]

You don't have to remove the ``ignore`` declaration to run the test in ``jote``.
If you want to see whether an ignored test now works you can run ``jote``
for specific tests by using ``--test`` and naming the ignored test you want
to run. When a test is named explicitly it is run, regardless of whether
``ignore`` has been set or not.

Test run levels
---------------

Tests can be assigned a ``run-level``. Run-levels are numerical value (1..100)
that can be used to group your tests. You can use the ``run-level``
as an indication of execution time, with short tests having low values and
time-consuming tests with higher values.

By default all tests that have no run-level defined and those with
a run-level of ``1`` are executed.  If you set the run-level for longer-running
tests to a higher value, e.g. ``5``, these will be skipped. To run these more
time-consuming tests you specify the run-level when running ``jote``
using ``--run-level 5``.

    When you give ``jote`` a run-level only tests up to and including the
    level, and those without any run-level, will be run.

You define the run-level in the root block of the job's test specification::

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
If you expect that your test needs to run for more than 10 minutes you must
use the ``timeout-minutes`` property in the job definition to define your own
test-specific value::

    jobs:
      [...]
      max-min-picker:
        [...]
        tests:
          simple-execution:
            timeout-minutes: 120
            [...]

You should try and avoid creating too many long-running tests. If you cannot,
consider whether it's a appropriate to use ``run-level`` to avoid ``jote``
running them by default.

Test groups
-----------

Tests are normally executed and the environment torn-down between them.
If you have tests that depend on the results from a prior test you can run
tests as a **group**, which preserves the project directory between the tests.

To run a sequence of test (as a **group**) you need to define a ``test-group``
in your Job Definition file and then refer to that group in your test. Here,
we define a test group called ``experiment-a``, at the top of the
definition file::

    test-groups:
    - name: experiment-a


We then place a test in that group with a ``run-group`` declaration
in the corresponding test block::

    jobs:
      max-min-picker:
        [...]
        tests:
          test-a:
            run-groups:
            - name: experiment-a
              ordinal: 1

We need to provide an ``ordinal`` value. This numeric value (from 1 ..N)
puts the test in a specific position in the test sequence. When tests are
placed in a ``run-group`` you have to order your tests, i.e. declare that
``test-a`` follows ``test-b``. This is done with unique ordinals for each
test in the ``run-group``. A test with ordinal ``1`` will run before a test
with ordinal ``2``. Ordinals have to be unique within a ``run-group``.

You can run the tests for a specific group by using  the ``--run-group``
option::

    jote --run-group experiment-a

Running additional containers (group testing)
---------------------------------------------

Test groups provide an ability to launch additional support containers during
testing. You might want to start a background database for example, that can
be used by tests in your ``test-group``. To take advantage of this feature
you just need to provide a ``docker-compose`` file (in the Job definition
``data-manager`` directory) and name that file in you r``test-groups``
declaration.

Here we declare a docker-compose file called
``docker-compose-experiment-a.yaml``::

    test-groups:
    - name: experiment-a
      compose:
        file: docker-compose-experiment-a.yaml

The compose filename must begin ``docker-compose`` and end ``.yaml``.

The compose file is run before any tests in the corresponding test group
have been run and will be stopped after the last test in the group.

The compose file you provide is run in a *detached* state so ``jote`` does
not wait for the containers to start (or initialise). As the first test
in the test group can begin very soon after the compose file is started
you can minimise the risk that your containers are not ready for the tests
by adding a fixed delay between ``jote`` starting the compose file and
running the first test::

    test-groups:
    - name: experiment-a
      compose:
        file: docker-compose-experiment-a.yaml
        delay-seconds: 10

Nextflow test execution
-----------------------

Job image types can be ``simple`` or ``nextflow``. Simple jobs are executed in
the container image you've built and should behave much the same as they do
when run within the Data Manager. Nextflow jobs on the other hand are executed
using the shell, relying on Docker as the execution run-time for the processes
in your workflow.

Be aware that nextflow tests run by ``jote`` run under different conditions
compared to when it runs under the Data Manager's control. In the Data Manager
nextflow jobs will be executed within a Kubernetes environment. When run by ``jote``
nextflow is expected using the operating system shell. This introduces a
variability that you need to take into account - i.e. under ``jote`` the
nextflow controller runs in the shell, and *are not* executed in the same
environment or under the same memory or processor constraints.

You might need to provide a custom nextflow configuration file
for your tests to run successfully. You do this by adding a ``nextflow-config-file``
declaration in the test. Here, we name the file ``nextflow-test.config``::

    jobs:
      max-min-picker:
        [...]
        tests:
          simple-load:
            nextflow-config-file: nextflow-test.config
            [...]

The config file must be located in the Job repository's ``data-manager``
directory.

Prior to running the corresponding test ``jote`` copies it to the
Job's project directory as the file ``nextflow.config`` (a standard file
expected by nextflow).

``jote`` *will not* let you have a nextflow config in your home directory
as any settings found there would be merged with the file ``jote`` writes,
potentially disturbing the execution behaviour.

.. note::
   It's your responsibility to install a suitable nextflow that's available
   for shell execution. ``jote`` expects to be able to run nextflow when
   executing the corresponding ``command`` that's defined in the job
   definition.

Installation
============

``jote`` is published on `PyPI`_ and can be installed from there::

    pip install im-jote

This is a Python 3 utility, so try to run it from a recent (ideally 3.10)
Python environment.

To use the utility you will need to have installed `Docker`_ and,
if you want to test nextflow jobs, `nextflow`_.

.. _PyPI: https://pypi.org/project/im-jote/
.. _Docker: https://docs.docker.com/get-docker/
.. _nextflow: https://www.nextflow.io/

Get in touch
------------

- Report bugs, suggest features or view the source code `on GitHub`_.

.. _on GitHub: https://github.com/informaticsmatters/squonk2-data-manager-job-tester
