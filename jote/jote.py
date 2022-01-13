"""Informatics Matters Job Tester (JOTE).

Run with 'jote --help'
"""
import argparse
import glob
import os
import shutil
from typing import Any, Dict, List, Tuple

from munch import DefaultMunch
import yaml

from decoder import decoder
import compose

# Where can we expect to find Job definitions?
_DEFINITION_DIRECTORY: str = 'data-manager'


def _print_test_banner(collection: str,
                       job_name: str,
                       job_test_name: str) -> None:

    print('  ---')
    print(f'+ collection={collection} job={job_name} test={job_test_name}')
    test_path: str = compose.get_test_path(job_name)
    print(f'# path={test_path}')


def _load() -> Tuple[List[DefaultMunch], int]:
    """Loads definition files (all the YAML files in a given directory)
    and extracts the definitions that contain at least one test.
    """
    job_definitions: List[DefaultMunch] = []
    num_tests: int = 0

    jd_filenames: List[str] = glob.glob(f'{_DEFINITION_DIRECTORY}/*.yaml')
    for jd_filename in jd_filenames:
        with open(jd_filename, 'r') as jd_file:
            jd: Dict[str, Any] = yaml.load(jd_file, Loader=yaml.FullLoader)
        if jd:
            jd_munch: DefaultMunch = DefaultMunch.fromDict(jd)
            for jd_name in jd_munch.jobs:
                if jd_munch.jobs[jd_name].tests:
                    num_tests += len(jd_munch.jobs[jd_name].tests)
            if num_tests:
                job_definitions.append(jd_munch)

    return job_definitions, num_tests


def _copy_inputs(test_inputs: DefaultMunch,
                 project_path: str) -> bool:
    """Copies all the test files into the test project directory.
    Files are expected to reside in the repo's 'data' directory.
    """

    # The files are assumed to reside in the repo's 'data' directory.
    print('# Copying inputs...')

    for test_input in test_inputs:
        test_file: str = os.path.join('data', test_inputs[test_input])
        print(f'# + {test_file} ({test_input})')
        if not os.path.isfile(test_file):
            print('! FAILURE')
            print(f'! missing input file {test_file} ({test_input})')
            return False
        shutil.copy(test_file, project_path)

    print('# Copied')

    return True


def _test(args: argparse.Namespace,
          collection: str,
          job: str,
          job_definition: DefaultMunch) -> bool:
    """Runs test for a specific Job definition returning True on success.
    """
    assert job_definition
    assert isinstance(job_definition, DefaultMunch)

    # The test status, assume success
    test_status: bool = True

    job_image: str = f'{job_definition.image.name}:{job_definition.image.tag}'
    job_project_directory: str = job_definition.image['project-directory']

    for job_test_name in job_definition.tests:
        _print_test_banner(collection, job, job_test_name)

        # Render the command for this test.
        # First extract the variables and values form options and inputs...
        job_variables: Dict[str, Any] = {}
        for variable in job_definition.tests[job_test_name].options:
            job_variables[variable] =\
                job_definition.tests[job_test_name].options[variable]
        for variable in job_definition.tests[job_test_name].inputs:
            job_variables[variable] =\
                job_definition.tests[job_test_name].inputs[variable]
        # Get the raw (encoded) command
        raw_command: str = job_definition.command
        # Apply the rendering...
        job_command, test_status =\
            decoder.decode(raw_command,
                           job_variables,
                           'command',
                           decoder.TextEncoding.JINJA2_3_0)
        if not test_status:
            print('! FAILURE')
            print('! Failed to render command')
            print('! error={job_command}')

        if test_status:

            print(f'> image={job_image}')
            print(f'> command="{job_command}"')

            # Create the project
            project_path: str = compose.create(job_test_name,
                                               job_image,
                                               job_project_directory,
                                               job_command)

            # Copy the data into the test's project directory.
            # Data's expected to be found in the Job's 'inputs'.
            if job_definition.tests[job_test_name].inputs:
                test_status =\
                    _copy_inputs(job_definition.tests[job_test_name].inputs,
                                 project_path)

        if test_status:
            # Run the container
            exit_code, out, err = compose.run(job_test_name)

            # Delete the test directory?
            # Not if there's an error
            # and not if told not to.
            expected_exit_code: int =\
                job_definition.tests[job_test_name].checks.exitCode

            if exit_code == expected_exit_code and not args.keep_results:
                compose.delete(job_test_name)
            elif exit_code != expected_exit_code:
                print(f'! FAILURE')
                print(f'! exit_code={exit_code}'
                      f' expected_exit_code={expected_exit_code}')
                print(f'! Container output follows...')
                print(out)
                test_status = False

        # Inspect the results
        # (only if successful so far)
        if test_status and job_definition.tests[job_test_name].outputs:
            print('Checking outputs')

    return test_status


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------
def main() -> None:
    """The console script entry-point. Called when jote is executed
    or from __main__.py, which is used by the installed console script.
    """

    # Build a command-line parser
    # and process the command-line...
    arg_parser: argparse.ArgumentParser =\
        argparse.ArgumentParser(description='Data Manager Job Tester')

    arg_parser.add_argument('-c', '--collection',
                            help='The Job collection to test. If not'
                                 ' specified the Jobs in all collections'
                                 ' will be candidates for testing.')
    arg_parser.add_argument('-j', '--job',
                            help='The Job to test. If specified the collection'
                                 ' is required. If not specified all the Jobs'
                                 ' that match the collection will be'
                                 ' candidates for testing.')
    arg_parser.add_argument('-t', '--test',
                            help='A specific test to run. If specified the job'
                                 ' is required. If not specified all the Tests'
                                 ' that match the collection will be'
                                 ' candidates for testing.')

    arg_parser.add_argument('-i', '--image',
                            help='An alternative container image to test,'
                                 ' with a tag like "my-image:latest". If not'
                                 ' specified the image and tag declared in the'
                                 ' Job definition will be used.')

    arg_parser.add_argument('-d', '--dry-run',
                            help='Setting this flag will result in jote'
                                 ' simply parsing the Job definitions'
                                 ' but not running any of the tests.'
                                 ' It is can be used to check validate your'
                                 ' definition file and its test commands and'
                                 'data.')

    arg_parser.add_argument('-k', '--keep-results',
                            help='Normally all material created to run each'
                                 ' test is removed when the test is'
                                 ' successful')

    arg_parser.add_argument('-x', '--exit-on-failure',
                            help='Normally jote reports test failures but'
                                 ' continues with the next test.'
                                 ' Setting this flag will force jote to '
                                 ' stop when it encounters the first failure')

    args: argparse.Namespace = arg_parser.parse_args()

    if args.test and args.job is None:
        arg_parser.error('--test requires --job')
    if args.job and args.collection is None:
        arg_parser.error('--job requires --collection')

    # Args are OK if we get here.
    test_fail_count: int = 0

    # Load all the files we can and then run the tests.
    job_definitions, num_tests = _load()

    msg: str = 'test' if num_tests == 1 else 'tests'
    print(f'# Found {num_tests} {msg}')

    if job_definitions:
        # There is at least one job-definition with a test
        # Now process all the Jobs that have tests...
        next_number: int = 0
        for job_definition in job_definitions:
            for job_name in job_definition.jobs:
                if job_definition.jobs[job_name].tests:
                    if not _test(args,
                                 job_definition.collection,
                                 job_name,
                                 job_definition.jobs[job_name]):
                        test_fail_count += 1

    num_tests_passed: int = num_tests - test_fail_count
    # Success or failure?
    if test_fail_count:
        print()
        arg_parser.error('Done (FAILURE)'
                         f' passed={num_tests_passed}'
                         f' failed={test_fail_count}')
    else:
        print("Done (Success) passed={num_tests_passed}")


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()
