"""Informatics Matters Job Tester (JOTE).

Run with 'jote --help'
"""
import argparse
import glob
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from munch import DefaultMunch
import yaml

from decoder import decoder

from .compose import Compose

# Where can we expect to find Job definitions?
_DEFINITION_DIRECTORY: str = 'data-manager'


def _print_test_banner(collection: str,
                       job_name: str,
                       job_test_name: str) -> None:

    print('  ---')
    print(f'+ collection={collection} job={job_name} test={job_test_name}')


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


def _check_exists(name: str, path: str, expected: bool) -> bool:

    exists: bool = os.path.exists(path)
    if expected and not exists:
        print(f'#   exists ({expected}) [FAILED]')
        print('! FAILURE')
        print(f'! Check exists "{name}" (does not exist)')
        return False
    elif not expected and exists:
        print(f'#   exists ({expected}) [FAILED]')
        print('! FAILURE')
        print(f'! Check does not exist "{name}" (exists)')
        return False

    print(f'#   exists ({expected}) [OK]')
    return True


def _check_line_count(name: str, path: str, expected: int) -> bool:

    line_count: int = 0
    for _ in open(path):
        line_count += 1

    if line_count != expected:
        print(f'#   lineCount ({line_count}) [FAILED]')
        print('! FAILURE')
        print(f'! Check lineCount {name}'
              f' (found {line_count}, expected {expected})')
        return False

    print(f'#   lineCount ({line_count}) [OK]')
    return True


def _check(t_compose: Compose,
           output_checks: DefaultMunch) -> bool:
    """Runs the checks on the Job outputs.
    We currently support 'exists' and 'lineCount'.
    """
    assert t_compose
    assert isinstance(t_compose, Compose)
    assert output_checks
    assert isinstance(output_checks, List)

    print('# Checking...')

    for output_check in output_checks:
        output_name: str = output_check.name
        print(f'# - {output_name}')
        expected_file: str = os.path.join(t_compose.get_test_project_path(),
                                          output_name)

        for check in output_check.checks:
            check_type: str = list(check.keys())[0]
            if check_type == 'exists':
                if not _check_exists(output_name,
                                     expected_file,
                                     check.exists):
                    return False
            elif check_type == 'lineCount':
                if not _check_line_count(output_name,
                                         expected_file,
                                         check.lineCount):
                    return False
            else:
                print('! FAILURE')
                print(f'! Unknown output check type ({check_type})')
                return False

    print('# Checked')

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
    job_working_directory: str = job_definition.image['working-directory']

    for job_test_name in job_definition.tests:

        test_status = True

        # If a job test has been named,
        # skip this test if it doesn't match
        if args.test and not args.test == job_test_name:
            continue

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

        # Create the test directories, docker-compose file
        # and copy inputs...
        t_compose: Optional[Compose] = None
        if test_status:

            print(f'> image={job_image}')
            print(f'> command="{job_command}"')

            # Create the project
            t_compose = Compose(collection,
                                job,
                                job_test_name,
                                job_image,
                                job_project_directory,
                                job_working_directory,
                                job_command)
            project_path: str = t_compose.create()

            test_path: str = t_compose.get_test_path()
            print(f'# path={test_path}')

            # Copy the data into the test's project directory.
            # Data's expected to be found in the Job's 'inputs'.
            if job_definition.tests[job_test_name].inputs:
                test_status =\
                    _copy_inputs(job_definition.tests[job_test_name].inputs,
                                 project_path)

        # Run the container
        if test_status and not args.dry_run:
            # Run the container
            exit_code, out, err = t_compose.run()

            # Delete the test directory?
            # Not if there's an error
            # and not if told not to.
            expected_exit_code: int =\
                job_definition.tests[job_test_name].checks.exitCode

            if exit_code != expected_exit_code:
                print(f'! FAILURE')
                print(f'! exit_code={exit_code}'
                      f' expected_exit_code={expected_exit_code}')
                print(f'! Container output follows...')
                print(out)
                test_status = False

            if args.verbose:
                print(out)

        # Inspect the results
        # (only if successful so far)
        if test_status and job_definition.tests[job_test_name].checks.outputs:
            test_status = \
                _check(t_compose,
                       job_definition.tests[job_test_name].checks.outputs)

        # Clean-up
        if test_status:
            t_compose.delete()

        # Told to stop on first failure?
        if not test_status and args.exit_on_failure:
            break

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

    arg_parser.add_argument('-d', '--dry-run', action='store_true',
                            help='Setting this flag will result in jote'
                                 ' simply parsing the Job definitions'
                                 ' but not running any of the tests.'
                                 ' It is can be used to check validate your'
                                 ' definition file and its test commands and'
                                 'data.')

    arg_parser.add_argument('-k', '--keep-results', action='store_true',
                            help='Normally all material created to run each'
                                 ' test is removed when the test is'
                                 ' successful')

    arg_parser.add_argument('-v', '--verbose', action='store_true',
                            help='Displays test stdout')

    arg_parser.add_argument('-x', '--exit-on-failure', action='store_true',
                            help='Normally jote reports test failures but'
                                 ' continues with the next test.'
                                 ' Setting this flag will force jote to '
                                 ' stop when it encounters the first failure')

    args: argparse.Namespace = arg_parser.parse_args()

    if args.test and args.job is None:
        arg_parser.error('--test requires --job')
    if args.job and args.collection is None:
        arg_parser.error('--job requires --collection')
    if args.keep_results and args.dry_run:
        arg_parser.error('Cannot use --dry-run and --keep-results')
    # Args are OK if we get here.
    test_fail_count: int = 0

    # Load all the files we can and then run the tests.
    job_definitions, num_tests = _load()

    msg: str = 'test' if num_tests == 1 else 'tests'
    print(f'# Found {num_tests} {msg}')
    if args.collection:
        print(f'# Limiting to Collection {args.collection}')
    if args.job:
        print(f'# Limiting to Job {args.job}')
    if args.test:
        print(f'# Limiting to Test {args.test}')

    if job_definitions:
        # There is at least one job-definition with a test
        # Now process all the Jobs that have tests...
        for job_definition in job_definitions:
            # If a collection's been named,
            # skip this file if it's not the named collection
            collection: str = job_definition.collection
            if args.collection and not args.collection == collection:
                continue

            for job_name in job_definition.jobs:
                # If a Job's been named,
                # skip this test if the job does not match
                if args.job and not args.job == job_name:
                    continue

                if job_definition.jobs[job_name].tests:
                    if not _test(args,
                                 collection,
                                 job_name,
                                 job_definition.jobs[job_name]):
                        test_fail_count += 1
                        if args.exit_on_failure:
                            break
            if test_fail_count and args.exit_on_failure:
                break

    # Success or failure?
    print('  ---')
    num_tests_passed: int = num_tests - test_fail_count
    dry_run: str = '[DRY RUN]' if args.dry_run else ''
    if test_fail_count:
        print()
        arg_parser.error('Done (FAILURE)'
                         f' passed={num_tests_passed}'
                         f' failed={test_fail_count}'
                         f' {dry_run}')
    else:
        print(f'Done (OK) passed={num_tests_passed} {dry_run}')


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()
