Informatics Matters Job Tester ("jote")
=======================================

.. image:: https://badge.fury.io/py/im-jote.svg
   :target: https://badge.fury.io/py/im-jote
   :alt: PyPI package (latest)

.. image:: https://github.com/InformaticsMatters/squonk2-data-manager-job-tester/actions/workflows/build.yaml/badge.svg
   :target: https://github.com/InformaticsMatters/squonk2-data-manager-job-tester/actions/workflows/build.yaml
   :alt: Build

.. image:: https://github.com/InformaticsMatters/squonk2-data-manager-job-tester/actions/workflows/publish.yaml/badge.svg
   :target: https://github.com/InformaticsMatters/squonk2-data-manager-job-tester/actions/workflows/publish.yaml
   :alt: Publish

The **Squonk2 Job Tester** (``jote``) is a Python utility used to run *unit tests*
that are defined in Data Manager *job implementation repositories* against
the job's container image, images that are typically built from the same
repository.

Documentation
-------------

The authoritative user documentation for ``jote`` — and for Data Manager
Jobs in general — lives in the `squonk2-jobs`_ repository. To learn how to
write and run Job tests start with the `Testing Jobs`_ guide there.

.. _squonk2-jobs: https://github.com/InformaticsMatters/squonk2-jobs
.. _testing jobs: https://github.com/InformaticsMatters/squonk2-jobs/blob/main/docs/testing-jobs.md

Installation
============

``jote`` is published on `PyPI`_ and can be installed from there::

    pip install im-jote

This is a Python 3 utility, so try to run it from a recent (ideally 3.10)
Python environment.

To use the utility you will need to have installed `Docker`_, ``docker-compose``
(v1 or v2) and, if you want to test nextflow jobs, `nextflow`_.

.. _PyPI: https://pypi.org/project/im-jote/
.. _Docker: https://docs.docker.com/get-docker/
.. _nextflow: https://www.nextflow.io/

Get in touch
------------

- Report bugs, suggest features or view the source code `on GitHub`_.

.. _on GitHub: https://github.com/informaticsmatters/squonk2-data-manager-job-tester
