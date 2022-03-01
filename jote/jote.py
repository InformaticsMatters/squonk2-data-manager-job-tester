"""Informatics Matters Job Tester (JOTE).

Run with 'jote --help'
"""
import argparse
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from munch import DefaultMunch
import yaml
from yamllint import linter
from yamllint.config import YamlLintConfig

from decoder import decoder

from .compose import get_test_root, INSTANCE_DIRECTORY
from .compose import Compose

# Where can we expect to find Job definitions?
_DEFINITION_DIRECTORY: str = 'data-manager'
# What's the default manifest file?
_DEFAULT_MANIFEST: str = 'manifest.yaml'
# Where can we expect to find test data?
_DATA_DIRECTORY: str = 'data'

# The yamllint configuration file of the repository under test.
# It must exist in the root of the repo we're running in.
_YAMLLINT_FILE: str = '.yamllint'


def _print_test_banner(collection: str,
                       job_name: str,
                       job_test_name: str) -> None:

    print('  ---')
    print(f'+ collection={collection} job={job_name} test={job_test_name}')


def _lint(definition_filename: str) -> bool:
    """Lints the provided job definition file.
    """

    if not os.path.isfile(_YAMLLINT_FILE):
        print(f'! The yamllint file ({_YAMLLINT_FILE}) is missing')
        return False

    with open(definition_filename, 'rt', encoding='UTF-8') as definition_file:
        errors = linter.run(definition_file,
                            YamlLintConfig(file=_YAMLLINT_FILE))

    if errors:
        # We're given a 'generator' and we don't know if there are errors
        # until we iterator over it. So here we print an initial error message
        # on the first error.
        found_errors: bool = False
        for error in errors:
            if not found_errors:
                print(f'! Job definition "{definition_file}" fails yamllint:')
                found_errors = True
            print(error)
        if found_errors:
            return False

    return True


def _validate_schema(definition_filename: str) -> bool:
    """Checks the Job Definition against the decoder's schema.
    """

    with open(definition_filename, 'rt', encoding='UTF-8') as definition_file:
        job_def: Optional[Dict[str, Any]] =\
            yaml.load(definition_file, Loader=yaml.FullLoader)
    assert job_def

    # If the decoder returns something there's been an error.
    error: Optional[str] = decoder.validate_job_schema(job_def)
    if error:
        print(f'! Job definition "{definition_filename}"'
              ' does not comply with schema')
        print('! Full response follows:')
        print(error)
        return False

    return True


def _validate_manifest_schema(manifest_filename: str) -> bool:
    """Checks the Manifest against the decoder's schema.
    """

    with open(manifest_filename, 'rt', encoding='UTF-8') as definition_file:
        job_def: Optional[Dict[str, Any]] =\
            yaml.load(definition_file, Loader=yaml.FullLoader)
    assert job_def

    # If the decoder returns something there's been an error.
    error: Optional[str] = decoder.validate_manifest_schema(job_def)
    if error:
        print(f'! Manifest "{manifest_filename}"'
              ' does not comply with schema')
        print('! Full response follows:')
        print(error)
        return False

    return True


def _check_cwd() -> bool:
    """Checks the execution directory for sanity (cwd). Here we must find
    a .yamllint file and a data-manager directory?
    """
    expected_files: List[str] = [_YAMLLINT_FILE]
    for expected_file in expected_files:
        if not os.path.isfile(expected_file):
            print(f'! Expected file "{expected_file}"'
                  ' but it is not here')
            return False

    expected_directories: List[str] = [_DEFINITION_DIRECTORY,
                                       _DATA_DIRECTORY]
    for expected_directory in expected_directories:
        if not os.path.isdir(expected_directory):
            print(f'! Expected directory "{expected_directory}"'
                  ' but it is not here')
            return False

    return True


def _load(manifest_filename: str, skip_lint: bool)\
        -> Tuple[List[DefaultMunch], int]:
    """Loads definition files listed in the manifest
    and extracts the definitions that contain at least one test. The
    definition blocks for those that have tests (ignored or otherwise)
    are returned along with a count of the number of tests found
    (ignored or otherwise).

    If there was a problem loading the files an empty list and
    -ve count is returned.
    """
    manifest_path: str = os.path.join(_DEFINITION_DIRECTORY, manifest_filename)
    if not os.path.isfile(manifest_path):
        print(f'! The manifest file is missing ("{manifest_path}")')
        return [], -1

    if not _validate_manifest_schema(manifest_path):
        return [], -1

    with open(manifest_path, 'r', encoding='UTF-8') as manifest_file:
        manifest: Dict[str, Any] = yaml.load(manifest_file, Loader=yaml.FullLoader)
    if manifest:
        manifest_munch: DefaultMunch = DefaultMunch.fromDict(manifest)

    # Iterate through the named files...
    job_definitions: List[DefaultMunch] = []
    num_tests: int = 0

    for jd_filename in manifest_munch['job-definition-files']:

        # Does the definition comply with the dschema?
        # No options here - it must.
        jd_path: str = os.path.join(_DEFINITION_DIRECTORY, jd_filename)
        if not _validate_schema(jd_path):
            return [], -1

        # YAML-lint the definition?
        if not skip_lint:
            if not _lint(jd_path):
                return [], -2

        with open(jd_path, 'r', encoding='UTF-8') as jd_file:
            job_def: Dict[str, Any] = yaml.load(jd_file, Loader=yaml.FullLoader)
        if job_def:
            jd_munch: DefaultMunch = DefaultMunch.fromDict(job_def)
            for jd_name in jd_munch.jobs:
                if jd_munch.jobs[jd_name].tests:
                    num_tests += len(jd_munch.jobs[jd_name].tests)
            if num_tests:
                job_definitions.append(jd_munch)

    return job_definitions, num_tests


def _copy_inputs(test_inputs: List[str], project_path: str) -> bool:
    """Copies all the test files into the test project directory.
    """

    # The files are assumed to reside in the repo's 'data' directory.
    print(f'# Copying inputs (from "${{PWD}}/{_DATA_DIRECTORY}")...')

    expected_prefix: str = f'{_DATA_DIRECTORY}/'
    for test_input in test_inputs:

        print(f'# + {test_input}')

        if not test_input.startswith(expected_prefix):
            print('! FAILURE')
            print(f'! Input file {test_input} must start with "{expected_prefix}"')
            return False
        if not os.path.isfile(test_input):
            print('! FAILURE')
            print(f'! Missing input file {test_input} ({test_input})')
            return False

        # Looks OK, copy it
        shutil.copy(test_input, project_path)

    print('# Copied')

    return True


def _check_exists(name: str, path: str, expected: bool) -> bool:

    exists: bool = os.path.exists(path)
    if expected and not exists:
        print(f'#   exists ({expected}) [FAILED]')
        print('! FAILURE')
        print(f'! Check exists "{name}" (does not exist)')
        return False
    if not expected and exists:
        print(f'#   exists ({expected}) [FAILED]')
        print('! FAILURE')
        print(f'! Check does not exist "{name}" (exists)')
        return False

    print(f'#   exists ({expected}) [OK]')
    return True


def _check_line_count(name: str, path: str, expected: int) -> bool:

    line_count: int = 0
    with open(path, 'rt', encoding='UTF-8') as check_file:
        for _ in check_file:
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
          job_definition: DefaultMunch) -> Tuple[int, int, int, int]:
    """Runs the tests for a specific Job definition returning the number
    of tests passed, skipped (due to run-level), ignored and failed.
    """
    assert job_definition
    assert isinstance(job_definition, DefaultMunch)

    # The test status, assume success
    tests_passed: int = 0
    tests_skipped: int = 0
    tests_ignored: int = 0
    tests_failed: int = 0

    job_image: str = f'{job_definition.image.name}:{job_definition.image.tag}'
    job_image_memory: str = job_definition.image['memory']
    if job_image_memory is None:
        job_image_memory = '1Gi'
    job_image_cores: int = job_definition.image['cores']
    if job_image_cores is None:
        job_image_cores = 1
    job_project_directory: str = job_definition.image['project-directory']
    job_working_directory: str = job_definition.image['working-directory']

    for job_test_name in job_definition.tests:

        # If a job test has been named,
        # skip this test if it doesn't match.
        # We do not include this test in the count.
        if args.test and not args.test == job_test_name:
            continue

        _print_test_banner(collection, job, job_test_name)

        # The status changes to False if any
        # part of this block fails.
        test_status: bool = True

        # Does the test have an 'ignore' declaration?
        if 'ignore' in job_definition.tests[job_test_name]:
            print('W Ignoring test (found "ignore")')
            tests_ignored += 1
            continue

        # Does the test have a 'run-level' declaration?
        # If so, is it higher than the run-level specified?
        if 'run-level' in job_definition.tests[job_test_name]:
            run_level: int = job_definition.tests[job_test_name]['run-level']
            if run_level > args.run_level:
                print(f'W Skipping test (test is "run-level: {run_level}")')
                tests_skipped += 1
                continue

        # Render the command for this test.

        # First extract the variables and values from 'options'
        # and then 'inputs'.
        job_variables: Dict[str, Any] = {}
        for variable in job_definition.tests[job_test_name].options:
            job_variables[variable] =\
                job_definition.tests[job_test_name].options[variable]

        # If the option variable's declaration is 'multiple'
        # it must be handled as a list, e.g. it might be declared like this: -
        #
        # The double-comment is used
        # to avoid mypy getting upset by the 'type' line...
        #
        # #  properties:
        # #    fragments:
        # #      title: Fragment molecules
        # #      multiple: true
        # #      mime-types:
        # #      - chemical/x-mdl-molfile
        # #      type: file
        #
        # We only pass the basename of the input to the command decoding
        # i.e. strip the source directory.

        # A list of input files (relative to this directory)
        # We populate this with everything we find declared as an input
        input_files: List[str] = []

        # Process every 'input'
        for variable in job_definition.tests[job_test_name].inputs:
            # Test variable must be known as an input or option.
            # Is the variable an option (otherwise it's an input)
            variable_is_option: bool = False
            variable_is_input: bool = False
            if variable in job_definition.variables.options.properties:
                variable_is_option = True
            elif variable in job_definition.variables.inputs.properties:
                variable_is_input = True
            if not variable_is_option and not variable_is_input:
                print('! FAILURE')
                print(f'! Test variable ({variable})' +
                      ' not declared as input or option')
                # Record but do no further processing
                tests_failed += 1
                test_status = False
            # Is it declared as a list?
            value_is_list: bool = False
            if variable_is_option:
                if job_definition.variables.options.properties[variable].multiple:
                    value_is_list = True
            else:
                if job_definition.variables.inputs.properties[variable].multiple:
                    value_is_list = True

            # Add each value or just one value
            # (depending on whether it's a list)
            if value_is_list:
                job_variables[variable] = []
                for value in job_definition.tests[job_test_name].inputs[variable]:
                    job_variables[variable].append(os.path.basename(value))
                    input_files.append(value)
            else:
                value = job_definition.tests[job_test_name].inputs[variable]
                job_variables[variable] = os.path.basename(value)
                input_files.append(value)

        if test_status:

            # Job variables must contain 'built-in' variables: -
            # - DM_INSTANCE_DIRECTORY
            job_variables['DM_INSTANCE_DIRECTORY'] = INSTANCE_DIRECTORY

            # Get the raw (encoded) command from the job definition...
            raw_command: str = job_definition.command
            # Decode it using our variables...
            decoded_command, test_status =\
                decoder.decode(raw_command,
                               job_variables,
                               'command',
                               decoder.TextEncoding.JINJA2_3_0)
            if not test_status:
                print('! FAILURE')
                print('! Failed to render command')
                print(f'! error={decoded_command}')
                # Record but do no further processing
                tests_failed += 1
                test_status = False

        # Create the test directories, docker-compose file
        # and copy inputs...
        t_compose: Optional[Compose] = None
        if test_status:

            # The command must not contain new-lines.
            # So split then join the command.
            job_command: str = ''.join(decoded_command.splitlines())

            print(f'> image={job_image}')
            print(f'> command="{job_command}"')

            # Create the project
            t_compose = Compose(collection,
                                job,
                                job_test_name,
                                job_image,
                                job_image_memory,
                                job_image_cores,
                                job_project_directory,
                                job_working_directory,
                                job_command)
            project_path: str = t_compose.create()

            test_path: str = t_compose.get_test_path()
            print(f'# path={test_path}')

            # Copy the data into the test's project directory.
            # Data's expected to be found in the Job's 'inputs'.
            print(f'input_files={input_files}')
            test_status = _copy_inputs(input_files, project_path)

        # Run the container
        if test_status and not args.dry_run:
            # Run the container
            assert t_compose
            exit_code, out, err = t_compose.run()

            # Delete the test directory?
            # Not if there's an error
            # and not if told not to.
            expected_exit_code: int =\
                job_definition.tests[job_test_name].checks.exitCode

            if exit_code != expected_exit_code:
                print('! FAILURE')
                print(f'! exit_code={exit_code}'
                      f' expected_exit_code={expected_exit_code}')
                print('! Container stdout follows...')
                print(out)
                print('! Container stderr follows...')
                print(err)
                test_status = False

            if args.verbose:
                print(out)

        # Inspect the results
        # (only if successful so far)
        if test_status \
                and not args.dry_run \
                and job_definition.tests[job_test_name].checks.outputs:

            assert t_compose
            test_status = \
                _check(t_compose,
                       job_definition.tests[job_test_name].checks.outputs)

        # Clean-up
        if test_status and not args.keep_results:
            assert t_compose
            t_compose.delete()

        # Count?
        if test_status:
            tests_passed += 1
        else:
            tests_failed += 1

        # Told to stop on first failure?
        if not test_status and args.exit_on_failure:
            break

    return tests_passed, tests_skipped, tests_ignored, tests_failed


def _wipe() -> None:
    """Wipes the results of all tests.
    """
    test_root: str = get_test_root()
    if os.path.isdir(test_root):
        shutil.rmtree(test_root)


def arg_check_run_level(value: str) -> int:
    """A type checker for the argparse run-level.
    """
    i_value = int(value)
    if i_value < 1:
        raise argparse.ArgumentTypeError('Minimum value is 1')
    if i_value > 100:
        raise argparse.ArgumentTypeError('Maximum value is 100')
    return i_value


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------
def main() -> int:
    """The console script entry-point. Called when jote is executed
    or from __main__.py, which is used by the installed console script.
    """

    # Build a command-line parser
    # and process the command-line...
    arg_parser: argparse.ArgumentParser = argparse\
        .ArgumentParser(description='Data Manager Job Tester',
                        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    arg_parser.add_argument('-m', '--manifest',
                            help='The manifest file.',
                            default=_DEFAULT_MANIFEST,
                            type=str)
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
    arg_parser.add_argument('-r', '--run-level',
                            help='The run-level of the tests you want to'
                                 ' execute. All tests at or below this level'
                                 ' will be executed, a value from 1 to 100',
                            default=1,
                            type=arg_check_run_level)

    arg_parser.add_argument('-d', '--dry-run', action='store_true',
                            help='Setting this flag will result in jote'
                                 ' simply parsing the Job definitions'
                                 ' but not running any of the tests.'
                                 ' It is can be used to check the syntax of'
                                 ' your definition file and its test commands'
                                 ' and data.')

    arg_parser.add_argument('-k', '--keep-results', action='store_true',
                            help='Normally all material created to run each'
                                 ' test is removed when the test is'
                                 ' successful')

    arg_parser.add_argument('-v', '--verbose', action='store_true',
                            help='Displays test stdout')

    arg_parser.add_argument('-x', '--exit-on-failure', action='store_true',
                            help='Normally jote reports test failures but'
                                 ' continues with the next test.'
                                 ' Setting this flag will force jote to'
                                 ' stop when it encounters the first failure')

    arg_parser.add_argument('-s', '--skip-lint', action='store_true',
                            help='Normally jote runs the job definition'
                                 ' files against the prevailing lint'
                                 ' configuration of the repository under test.'
                                 ' Using this flag skips that step')

    arg_parser.add_argument('-w', '--wipe', action='store_true',
                            help='Wipe does nto run any tests, it simply'
                                 ' wipes the repository clean of jote'
                                 ' test material. It would be wise'
                                 ' to run this once you have finished testing.'
                                 ' Using this negates the effect of any other'
                                 ' option.')

    arg_parser.add_argument('-a', '--allow-no-tests', action='store_true',
                            help='Normally jote expects to run tests'
                                 ' and if you have no tests jote will fail.'
                                 ' To prevent jote complaining about the lack'
                                 ' of tests you can use this option.')

    args: argparse.Namespace = arg_parser.parse_args()

    if args.test and args.job is None:
        arg_parser.error('--test requires --job')
    if args.job and args.collection is None:
        arg_parser.error('--job requires --collection')
    if args.wipe and args.keep_results:
        arg_parser.error('Cannot use --wipe and --keep-results')

    # Args are OK if we get here.
    total_skipped_count: int = 0
    total_ignore_count: int = 0
    total_fail_count: int = 0

    # Check CWD
    if not _check_cwd():
        print('! FAILURE')
        print('! The directory does not look correct')
        arg_parser.error('Done (FAILURE)')

    # Told to wipe?
    # If so wipe, and leave.
    if args.wipe:
        _wipe()
        print('Done [Wiped]')
        return 0

    print(f'# Using manifest "{args.manifest}"')

    # Load all the files we can and then run the tests.
    job_definitions, num_tests = _load(args.manifest, args.skip_lint)
    if num_tests < 0:
        print('! FAILURE')
        print('! Definition file has failed yamllint')
        arg_parser.error('Done (FAILURE)')

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
                    _, num_skipped, num_ignored, num_failed =\
                        _test(args,
                              collection,
                              job_name,
                              job_definition.jobs[job_name])
                    total_skipped_count += num_skipped
                    total_ignore_count += num_ignored
                    total_fail_count += num_failed

                    # Break out of this loop if told to stop on failures
                    if num_failed > 0 and args.exit_on_failure:
                        break

            # Break out of this loop if told to stop on failures
            if num_failed > 0 and args.exit_on_failure:
                break

    # Success or failure?
    # It's an error to find no tests.
    print('  ---')
    total_pass_count: int = num_tests - total_fail_count - total_ignore_count
    dry_run: str = '[DRY RUN]' if args.dry_run else ''
    summary: str = f'passed={total_pass_count}' \
        f' skipped={total_skipped_count}' \
        f' ignored={total_ignore_count}'
    if total_fail_count:
        arg_parser.error(f'Done (FAILURE) {summary} failed={total_fail_count}'
                         f' {dry_run}')
    elif total_pass_count == 0 and not args.allow_no_tests:
        arg_parser.error(f'Done (FAILURE) {summary}'
                         f' failed=0 (at least one test must pass)'
                         f' {dry_run}')
    else:
        print(f'Done (OK) {summary} {dry_run}')

    # Automatically wipe.
    # If there have been no failures
    # and not told to keep directories.
    if total_fail_count == 0 and not args.keep_results:
        _wipe()

    return 0


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()
