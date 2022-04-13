#!/usr/bin/env python3

# Setup module for the Job Tester utility
#
# January 2022

import os
import setuptools

# Pull in the essential run-time requirements
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read().splitlines()

# Use the README.rst as the long description.
with open("README.rst", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="im-jote",
    version=os.environ.get("GITHUB_REF_SLUG", "1.0.0"),
    author="Alan Christie",
    author_email="achristie@informaticsmatters.com",
    url="https://github.com/informaticsmatters/data-manager-job-tester",
    license="MIT",
    description="The IM Data Manager Job Tester (jote)",
    long_description=long_description,
    keywords="configuration",
    platforms=["any"],
    # Our modules to package
    package_dir={"": "src"},
    packages=setuptools.find_packages(
        where="src", exclude=["*.test", "*.test.*", "test.*", "test"]
    ),
    include_package_data=True,
    # Project classification:
    # https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Topic :: System :: Installation/Setup",
        "Operating System :: POSIX :: Linux",
    ],
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "jote = jote.jote:main",
        ],
    },
    zip_safe=False,
)
