#!/usr/bin/env python3

# Setup module for the Job Tester utility
#
# January 2022

import os
from setuptools import setup, find_packages

# Pull in the essential run-time requirements
with open('requirements.txt') as file:
    requirements = file.read().splitlines()


# Use the README.rst as the long description.
def get_long_description():
    return open('README.rst').read()


name = 'im-jote'
author = 'Alan Christie'
version = os.environ.get('GITHUB_REF_SLUG', '1.0.0')
copyright = 'MIT'
setup(

    name=name,
    version=version,
    author=author,
    author_email='achristie@informaticsmatters.com',
    url='https://github.com/informaticsmatters/data-manager-job-tester',
    license=copyright,
    description='The IM Data Manager Job Tester (jote)',
    long_description=get_long_description(),
    keywords='configuration',
    platforms=['any'],
    # Our modules to package
    packages=find_packages(exclude=["*.test", "*.test.*", "test.*", "test"]),
    include_package_data=True,

    # Project classification:
    # https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.10',
        'Topic :: System :: Installation/Setup',
        'Operating System :: POSIX :: Linux',
    ],

    install_requires=requirements,

    entry_points={
        "console_scripts": [
            "jote = jote.jote:main",
        ],
    },

    zip_safe=False,

)
