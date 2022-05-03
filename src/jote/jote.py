#!/usr/bin/env python

"""Informatics Matters Job Tester (JOTE).

Get help running this utility with 'jote --help'
"""
import argparse
import os
import shutil
import stat
from stat import S_IRGRP, S_IRUSR, S_IWGRP, S_IWUSR
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from munch import DefaultMunch
import yaml
from yamllint import linter
from yamllint.config import YamlLintConfig

from decoder import decoder

from .compose import get_test_root, INSTANCE_DIRECTORY, DEFAULT_TEST_TIMEOUT_M
from .compose import Compose

# Where can we expect to find Job definitions?
_DEFINITION_DIRECTORY: str = "data-manager"
# What's the default manifest file?
_DEFAULT_MANIFEST: str = os.path.join(_DEFINITION_DIRECTORY, "manifest.yaml")
# Where can we expect to find test data?
_DATA_DIRECTORY: str = "data"

# Our yamllint configuration file
# from the same directory as us.
_YAMLLINT_FILE: str = os.path.join(os.path.dirname(__file__), "jote.yamllint")

# Read the version file
_VERSION_FILE: str = os.path.join(os.path.dirname(__file__), "VERSION")
with open(_VERSION_FILE, "r", encoding="utf-8") as file_handle:
    _VERSION = file_handle.read().strip()

# Job image types (lower-case)
_IMAGE_TYPE_SIMPLE: str = "simple"
_IMAGE_TYPE_NEXTFLOW: str = "nextflow"
_DEFAULT_IMAGE_TYPE: str = _IMAGE_TYPE_SIMPLE

# User HOME directory.
# Used to check for netflow files if nextflow is executed.
# The user CANNOT have any pf their own nextflow config.
_USR_HOME: str = os.environ.get("HOME", "")


def _print_test_banner(collection: str, job_name: str, job_test_name: str) -> None:

    print("  ---")
    print(f"+ collection={collection} job={job_name} test={job_test_name}")


def _lint(definition_filename: str) -> bool:
    """Lints the provided job definition file."""

    if not os.path.isfile(_YAMLLINT_FILE):
        print(f"! The yamllint file ({_YAMLLINT_FILE}) is missing")
        return False

    with open(definition_filename, "rt", encoding="UTF-8") as definition_file:
        errors = linter.run(definition_file, YamlLintConfig(file=_YAMLLINT_FILE))

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
    """Checks the Job Definition against the decoder's schema."""

    with open(definition_filename, "rt", encoding="UTF-8") as definition_file:
        job_def: Optional[Dict[str, Any]] = yaml.load(
            definition_file, Loader=yaml.FullLoader
        )
    assert job_def

    # If the decoder returns something there's been an error.
    error: Optional[str] = decoder.validate_job_schema(job_def)
    if error:
        print(
            f'! Job definition "{definition_filename}"' " does not comply with schema"
        )
        print("! Full response follows:")
        print(error)
        return False

    return True


def _validate_manifest_schema(manifest_filename: str) -> bool:
    """Checks the Manifest against the decoder's schema."""

    with open(manifest_filename, "rt", encoding="UTF-8") as definition_file:
        job_def: Optional[Dict[str, Any]] = yaml.load(
            definition_file, Loader=yaml.FullLoader
        )
    assert job_def

    # If the decoder returns something there's been an error.
    error: Optional[str] = decoder.validate_manifest_schema(job_def)
    if error:
        print(f'! Manifest "{manifest_filename}"' " does not comply with schema")
        print("! Full response follows:")
        print(error)
        return False

    return True


def _check_cwd() -> bool:
    """Checks the execution directory for sanity (cwd). Here we must find
    a data-manager directory
    """
    expected_directories: List[str] = [_DEFINITION_DIRECTORY, _DATA_DIRECTORY]
    for expected_directory in expected_directories:
        if not os.path.isdir(expected_directory):
            print(f'! Expected directory "{expected_directory}"' " but it is not here")
            return False

    return True


def _load(manifest_filename: str, skip_lint: bool) -> Tuple[List[DefaultMunch], int]:
    """Loads definition files listed in the manifest
    and extracts the definitions that contain at least one test. The
    definition blocks for those that have tests (ignored or otherwise)
    are returned along with a count of the number of tests found
    (ignored or otherwise).

    If there was a problem loading the files an empty list and
    -ve count is returned.
    """
    # Prefix manifest filename with definition directory if required...
    manifest_path: str = (
        manifest_filename
        if manifest_filename.startswith(f"{_DEFINITION_DIRECTORY}/")
        else os.path.join(_DEFINITION_DIRECTORY, manifest_filename)
    )
    if not os.path.isfile(manifest_path):
        print(f'! The manifest file is missing ("{manifest_path}")')
        return [], -1

    if not _validate_manifest_schema(manifest_path):
        return [], -1

    with open(manifest_path, "r", encoding="UTF-8") as manifest_file:
        manifest: Dict[str, Any] = yaml.load(manifest_file, Loader=yaml.FullLoader)
    if manifest:
        manifest_munch: DefaultMunch = DefaultMunch.fromDict(manifest)

    # Iterate through the named files...
    job_definitions: List[DefaultMunch] = []
    num_tests: int = 0

    for jd_filename in manifest_munch["job-definition-files"]:

        # Does the definition comply with the dschema?
        # No options here - it must.
        jd_path: str = os.path.join(_DEFINITION_DIRECTORY, jd_filename)
        if not _validate_schema(jd_path):
            return [], -1

        # YAML-lint the definition?
        if not skip_lint:
            if not _lint(jd_path):
                return [], -2

        with open(jd_path, "r", encoding="UTF-8") as jd_file:
            job_def: Dict[str, Any] = yaml.load(jd_file, Loader=yaml.FullLoader)
        if job_def:
            jd_munch: DefaultMunch = DefaultMunch.fromDict(job_def)
            for jd_name in jd_munch.jobs:
                if jd_munch.jobs[jd_name].tests:
                    num_tests += len(jd_munch.jobs[jd_name].tests)
            if num_tests:
                jd_munch.definition_filename = jd_filename
                job_definitions.append(jd_munch)

    return job_definitions, num_tests


def _copy_inputs(test_inputs: List[str], project_path: str) -> bool:
    """Copies all the test files into the test project directory."""

    # The files are assumed to reside in the repo's 'data' directory.
    print(f'# Copying inputs (from "${{PWD}}/{_DATA_DIRECTORY}")...')

    expected_prefix: str = f"{_DATA_DIRECTORY}/"
    for test_input in test_inputs:

        print(f"# + {test_input}")

        if not test_input.startswith(expected_prefix):
            print("! FAILURE")
            print(f'! Input file {test_input} must start with "{expected_prefix}"')
            return False
        if not os.path.isfile(test_input):
            print("! FAILURE")
            print(f"! Missing input file {test_input} ({test_input})")
            return False

        # Looks OK, copy it
        shutil.copy(test_input, project_path)

    print("# Copied")

    return True


def _check_exists(name: str, path: str, expected: bool, fix_permissions: bool) -> bool:

    exists: bool = os.path.exists(path)
    if expected and not exists:
        print(f"#   exists ({expected}) [FAILED]")
        print("! FAILURE")
        print(f'! Check exists "{name}" (does not exist)')
        return False
    if not expected and exists:
        print(f"#   exists ({expected}) [FAILED]")
        print("! FAILURE")
        print(f'! Check does not exist "{name}" (exists)')
        return False

    # File exists or does not exist, as expected.
    # If it exists we check its 'user' and 'group' read and write permission.
    #
    # If 'fix_permissions' is True (i.e. the DM is expected to fix (group) permissions)
    # the group permissions are expected to be incorrect. If False
    # then the group permissions are expected to be correct/
    if exists:
        stat_info: os.stat_result = os.stat(path)
        # Check user permissions
        file_mode: int = stat_info.st_mode
        if file_mode & S_IRUSR == 0 or file_mode & S_IWUSR == 0:
            print("! FAILURE")
            print(
                f'! "{name}" exists but has incorrect user permissions'
                f" ({stat.filemode(file_mode)})"
            )
            return False
        # Check group permissions
        if file_mode & S_IRGRP == 0 or file_mode & S_IWGRP == 0:
            # Incorrect permissions.
            if not fix_permissions:
                # And not told to fix them!
                print("! FAILURE")
                print(
                    f'! "{name}" exists but has incorrect group permissions (fix-permissions=False)'
                    f" ({stat.filemode(file_mode)})"
                )
                return False
        else:
            # Correct group permissions.
            if fix_permissions:
                # But told to fix them!
                print("! FAILURE")
                print(
                    f'! "{name}" exists but has correct group permissions (fix-permissions=True)'
                    f" ({stat.filemode(file_mode)})"
                )
                return False

    print(f"#   exists ({expected}) [OK]")
    return True


def _check_line_count(name: str, path: str, expected: int) -> bool:

    line_count: int = 0
    with open(path, "rt", encoding="UTF-8") as check_file:
        for _ in check_file:
            line_count += 1

    if line_count != expected:
        print(f"#   lineCount ({line_count}) [FAILED]")
        print("! FAILURE")
        print(f"! Check lineCount {name}" f" (found {line_count}, expected {expected})")
        return False

    print(f"#   lineCount ({line_count}) [OK]")
    return True


def _check(
    t_compose: Compose, output_checks: DefaultMunch, fix_permissions: bool
) -> bool:
    """Runs the checks on the Job outputs.
    We currently support 'exists' and 'lineCount'.
    If 'fix_permissions' is True we error if the permissions are correct,
    if False we error if the permissions are not correct.
    """
    assert t_compose
    assert isinstance(t_compose, Compose)
    assert output_checks
    assert isinstance(output_checks, List)

    print("# Checking...")

    for output_check in output_checks:
        output_name: str = output_check.name
        print(f"# - {output_name}")
        expected_file: str = os.path.join(
            t_compose.get_test_project_path(), output_name
        )

        for check in output_check.checks:
            check_type: str = list(check.keys())[0]
            if check_type == "exists":
                if not _check_exists(
                    output_name, expected_file, check.exists, fix_permissions
                ):
                    return False
            elif check_type == "lineCount":
                if not _check_line_count(output_name, expected_file, check.lineCount):
                    return False
            else:
                print("! FAILURE")
                print(f"! Unknown output check type ({check_type})")
                return False

    print("# Checked")

    return True


def _run_nextflow(
    command: str, project_path: str, timeout_minutes: int = DEFAULT_TEST_TIMEOUT_M
) -> Tuple[int, str, str]:
    """Runs nextflow in the project directory returning the exit code,
    stdout and stderr.
    """
    assert command
    assert project_path

    # The user cannot have a nextflow config in their home directory.
    # Nextflow looks here and any config will be merged with the test config.
    if _USR_HOME:
        home_config: str = os.path.join(_USR_HOME, ".nextflow", "config")
        if os.path.exists(home_config) and os.path.isfile(home_config):
            print("! FAILURE")
            print(
                "! A nextflow test but"
                f" you have your own config file ({home_config})"
            )
            print("! You cannot test Jobs and have your own config file")
            return 1, "", ""

    print('# Executing the test ("nextflow")...')
    print(f'# Execution directory is "{project_path}"')

    cwd = os.getcwd()
    os.chdir(project_path)

    try:
        test = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            timeout=timeout_minutes * 60,
        )
    finally:
        os.chdir(cwd)

    return test.returncode, test.stdout.decode("utf-8"), test.stderr.decode("utf-8")


def _test(
    args: argparse.Namespace,
    filename: str,
    collection: str,
    job: str,
    job_definition: DefaultMunch,
) -> Tuple[int, int, int, int]:
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

    if args.image_tag:
        print(f"W Replacing image tag. Using '{args.image_tag}'")
        job_image: str = f"{job_definition.image.name}:{args.image_tag}"
    else:
        job_image = f"{job_definition.image.name}:{job_definition.image.tag}"
    job_image_memory: str = job_definition.image["memory"]
    if job_image_memory is None:
        job_image_memory = "1Gi"
    job_image_cores: int = job_definition.image["cores"]
    if job_image_cores is None:
        job_image_cores = 1
    job_project_directory: str = job_definition.image["project-directory"]
    job_working_directory: str = job_definition.image["working-directory"]
    if "type" in job_definition.image:
        job_image_type: str = job_definition.image["type"].lower()
    else:
        job_image_type = _DEFAULT_IMAGE_TYPE
    # Does the image need the (group write) permissions
    # of files it creates fixing? Default is 'no'.
    # If 'yes' (true) the DM is expected to fix the permissions of the
    # generated files once the job has finished.
    job_image_fix_permissions: bool = False
    if "fix-permissions" in job_definition.image:
        job_image_fix_permissions = job_definition.image["fix-permissions"]

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
        print(f"> definition filename={filename}")

        # Does the test have an 'ignore' declaration?
        # Obey it unless the test is named explicitly -
        # i.e. if th user has named a specific test, run it.
        if "ignore" in job_definition.tests[job_test_name]:
            if args.test:
                print("W Ignoring the ignore: property (told to run this test)")
            else:
                print('W Ignoring test (found "ignore")')
                tests_ignored += 1
                continue

        # Does the test have a 'run-level' declaration?
        # If so, is it higher than the run-level specified?
        if args.test:
            print("W Ignoring any run-level check (told to run this test)")
        else:
            if "run-level" in job_definition.tests[job_test_name]:
                run_level = job_definition.tests[job_test_name]["run-level"]
                print(f"> run-level={run_level}")
                if run_level > args.run_level:
                    print(f'W Skipping test (test is "run-level: {run_level}")')
                    tests_skipped += 1
                    continue
            else:
                print("> run-level=Undefined")

        # Render the command for this test.

        # First extract the variables and values from 'options'
        # and then 'inputs'.
        job_variables: Dict[str, Any] = {}
        for variable in job_definition.tests[job_test_name].options:
            job_variables[variable] = job_definition.tests[job_test_name].options[
                variable
            ]

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
        if job_definition.tests[job_test_name].inputs:
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
                    print("! FAILURE")
                    print(
                        f"! Test variable ({variable})"
                        + " not declared as input or option"
                    )
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

        decoded_command: str = ""
        test_environment: Dict[str, str] = {}
        if test_status:

            # Jote injects Job variables that are expected.
            # 'DM_' variables are injected by the Data Manager,
            # other are injected by Jote.
            # - DM_INSTANCE_DIRECTORY
            job_variables["DM_INSTANCE_DIRECTORY"] = INSTANCE_DIRECTORY
            # - CODE_DIRECTORY
            job_variables["CODE_DIRECTORY"] = os.getcwd()

            # Has the user defined any environment variables in the test?
            # If so they must exist, although we don't care about their value.
            # Extract them here to pass to the test.
            if "environment" in job_definition.tests[job_test_name]:
                for env_name in job_definition.tests[job_test_name].environment:
                    env_value: Optional[str] = os.environ.get(env_name, None)
                    if env_value is None:
                        print("! FAILURE")
                        print("! Test environment variable is not defined")
                        print(f"! variable={env_name}")
                        # Record but do no further processing
                        tests_failed += 1
                        test_status = False
                        break
                    test_environment[env_name] = env_value

            if test_status:
                # Get the raw (encoded) command from the job definition...
                raw_command: str = job_definition.command
                # Decode it using our variables...
                decoded_command, test_status = decoder.decode(
                    raw_command,
                    job_variables,
                    "command",
                    decoder.TextEncoding.JINJA2_3_0,
                )
                if not test_status:
                    print("! FAILURE")
                    print("! Failed to render command")
                    print(f"! error={decoded_command}")
                    # Record but do no further processing
                    tests_failed += 1
                    test_status = False

        # Create the test directories, docker-compose file
        # and copy inputs...
        t_compose: Optional[Compose] = None
        job_command: str = ""
        project_path: str = ""
        if test_status:

            # The command must not contain new-lines.
            # So split then join the command.
            assert decoded_command
            job_command = "".join(decoded_command.splitlines())

            print(f"> image={job_image}")
            print(f"> image-type={job_image_type}")
            print(f"> command={job_command}")

            # Create the project
            t_compose = Compose(
                collection,
                job,
                job_test_name,
                job_image,
                job_image_type,
                job_image_memory,
                job_image_cores,
                job_project_directory,
                job_working_directory,
                job_command,
                test_environment,
                args.run_as_user,
            )
            project_path = t_compose.create()

            if input_files:
                # Copy the data into the test's project directory.
                # Data's expected to be found in the Job's 'inputs'.
                test_status = _copy_inputs(input_files, project_path)

        # Run the container
        if test_status and not args.dry_run:

            timeout_minutes: int = DEFAULT_TEST_TIMEOUT_M
            if "timeout-minutes" in job_definition.tests[job_test_name]:
                timeout_minutes = job_definition.tests[job_test_name]["timeout-minutes"]

            exit_code: int = 0
            out: str = ""
            err: str = ""
            if job_image_type in [_IMAGE_TYPE_SIMPLE]:
                # Run the image container
                assert t_compose
                exit_code, out, err = t_compose.run(timeout_minutes)
            elif job_image_type in [_IMAGE_TYPE_NEXTFLOW]:
                # Run nextflow directly
                assert job_command
                assert project_path
                exit_code, out, err = _run_nextflow(
                    job_command, project_path, timeout_minutes
                )
            else:
                print("! FAILURE")
                print(f"! unsupported image-type ({job_image_type}")
                test_status = False

            if test_status:
                expected_exit_code: int = job_definition.tests[
                    job_test_name
                ].checks.exitCode

                if exit_code != expected_exit_code:
                    print("! FAILURE")
                    print(
                        f"! exit_code={exit_code}"
                        f" expected_exit_code={expected_exit_code}"
                    )
                    print("! Test stdout follows...")
                    print(out)
                    print("! Test stderr follows...")
                    print(err)
                    test_status = False

            if args.verbose:
                print(out)

        # Inspect the results
        # (only if successful so far)
        if (
            test_status
            and not args.dry_run
            and job_definition.tests[job_test_name].checks.outputs
        ):

            assert t_compose
            test_status = _check(
                t_compose,
                job_definition.tests[job_test_name].checks.outputs,
                job_image_fix_permissions,
            )

        # Clean-up
        if test_status and not args.keep_results:
            assert t_compose
            t_compose.delete()

        # Count?
        if test_status:
            print("- SUCCESS")
            tests_passed += 1
        else:
            tests_failed += 1

        # Told to stop on first failure?
        if not test_status and args.exit_on_failure:
            break

    return tests_passed, tests_skipped, tests_ignored, tests_failed


def _wipe() -> None:
    """Wipes the results of all tests."""
    test_root: str = get_test_root()
    if os.path.isdir(test_root):
        shutil.rmtree(test_root)


def arg_check_run_level(value: str) -> int:
    """A type checker for the argparse run-level."""
    i_value = int(value)
    if i_value < 1:
        raise argparse.ArgumentTypeError("Minimum value is 1")
    if i_value > 100:
        raise argparse.ArgumentTypeError("Maximum value is 100")
    return i_value


def arg_check_run_as_user(value: str) -> int:
    """A type checker for the argparse run-as-user."""
    i_value = int(value)
    if i_value < 0:
        raise argparse.ArgumentTypeError("Minimum value is 0")
    if i_value > 65_535:
        raise argparse.ArgumentTypeError("Maximum value is 65535")
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
    arg_parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Data Manager Job Tester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    arg_parser.add_argument(
        "-m",
        "--manifest",
        help="The manifest file.",
        default=_DEFAULT_MANIFEST,
        type=str,
    )
    arg_parser.add_argument(
        "-c",
        "--collection",
        help="The Job collection to test. If not"
        " specified the Jobs in all collections"
        " will be candidates for testing.",
    )
    arg_parser.add_argument(
        "-j",
        "--job",
        help="The Job to test. If specified the collection"
        " is required. If not specified all the Jobs"
        " that match the collection will be"
        " candidates for testing.",
    )
    arg_parser.add_argument(
        "--image-tag",
        help="An image tag to use rather then the one defined in the job definition.",
    )
    arg_parser.add_argument(
        "-t",
        "--test",
        help="A specific test to run. If specified the job"
        " is required. If not specified all the Tests"
        " that match the collection will be"
        " candidates for testing.",
    )
    arg_parser.add_argument(
        "-r",
        "--run-level",
        help="The run-level of the tests you want to"
        " execute. All tests at or below this level"
        " will be executed, a value from 1 to 100",
        default=1,
        type=arg_check_run_level,
    )
    arg_parser.add_argument(
        "-u",
        "--run-as-user",
        help="A user ID to run the tests as. If not set"
        " your user ID is used to run the test"
        " containers.",
        type=arg_check_run_as_user,
    )

    arg_parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Setting this flag will result in jote"
        " simply parsing the Job definitions"
        " but not running any of the tests."
        " It is can be used to check the syntax of"
        " your definition file and its test commands"
        " and data.",
    )

    arg_parser.add_argument(
        "-k",
        "--keep-results",
        action="store_true",
        help="Normally all material created to run each"
        " test is removed when the test is"
        " successful",
    )

    arg_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Displays test stdout"
    )

    arg_parser.add_argument(
        "--version", action="store_true", help="Displays jote version"
    )

    arg_parser.add_argument(
        "-x",
        "--exit-on-failure",
        action="store_true",
        help="Normally jote reports test failures but"
        " continues with the next test."
        " Setting this flag will force jote to"
        " stop when it encounters the first failure",
    )

    arg_parser.add_argument(
        "-s",
        "--skip-lint",
        action="store_true",
        help="Normally jote runs the job definition"
        " files against the prevailing lint"
        " configuration of the repository under test."
        " Using this flag skips that step",
    )

    arg_parser.add_argument(
        "-w",
        "--wipe",
        action="store_true",
        help="Wipe does nto run any tests, it simply"
        " wipes the repository clean of jote"
        " test material. It would be wise"
        " to run this once you have finished testing."
        " Using this negates the effect of any other"
        " option.",
    )

    arg_parser.add_argument(
        "-a",
        "--allow-no-tests",
        action="store_true",
        help="Normally jote expects to run tests"
        " and if you have no tests jote will fail."
        " To prevent jote complaining about the lack"
        " of tests you can use this option.",
    )

    args: argparse.Namespace = arg_parser.parse_args()

    # If a version's been asked for act on it and then leave
    if args.version:
        print(_VERSION)
        return 0

    if args.test and args.job is None:
        arg_parser.error("--test requires --job")
    if args.job and args.collection is None:
        arg_parser.error("--job requires --collection")
    if args.wipe and args.keep_results:
        arg_parser.error("Cannot use --wipe and --keep-results")

    # Args are OK if we get here.
    total_passed_count: int = 0
    total_skipped_count: int = 0
    total_ignore_count: int = 0
    total_failed_count: int = 0

    # Check CWD
    if not _check_cwd():
        print("! FAILURE")
        print("! The directory does not look correct")
        arg_parser.error("Done (FAILURE)")

    # Told to wipe?
    # If so wipe, and leave.
    if args.wipe:
        _wipe()
        print("Done [Wiped]")
        return 0

    print(f'# Using manifest "{args.manifest}"')

    # Load all the files we can and then run the tests.
    job_definitions, num_tests = _load(args.manifest, args.skip_lint)
    if num_tests < 0:
        print("! FAILURE")
        print("! Definition file has failed yamllint")
        arg_parser.error("Done (FAILURE)")

    msg: str = "test" if num_tests == 1 else "tests"
    print(f"# Found {num_tests} {msg}")
    if args.collection:
        print(f'# Limiting to Collection "{args.collection}"')
    if args.job:
        print(f'# Limiting to Job "{args.job}"')
    if args.test:
        print(f'# Limiting to Test "{args.test}"')

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
                    num_passed, num_skipped, num_ignored, num_failed = _test(
                        args,
                        job_definition.definition_filename,
                        collection,
                        job_name,
                        job_definition.jobs[job_name],
                    )
                    total_passed_count += num_passed
                    total_skipped_count += num_skipped
                    total_ignore_count += num_ignored
                    total_failed_count += num_failed

                    # Break out of this loop if told to stop on failures
                    if num_failed > 0 and args.exit_on_failure:
                        break

            # Break out of this loop if told to stop on failures
            if num_failed > 0 and args.exit_on_failure:
                break

    # Success or failure?
    # It's an error to find no tests.
    print("  ---")
    dry_run: str = "[DRY RUN]" if args.dry_run else ""
    summary: str = (
        f"passed={total_passed_count}"
        f" skipped={total_skipped_count}"
        f" ignored={total_ignore_count}"
        f" failed={total_failed_count}"
    )
    failed: bool = False
    if total_failed_count:
        arg_parser.error(f"Done (FAILURE) {summary} {dry_run}")
        failed = True
    elif total_passed_count == 0 and not args.allow_no_tests:
        arg_parser.error(
            f"Done (FAILURE) {summary}" f" (at least one test must pass)" f" {dry_run}"
        )
        failed = True
    else:
        print(f"Done (OK) {summary} {dry_run}")

    # Automatically wipe.
    # If there have been no failures
    # and not told to keep directories.
    if total_failed_count == 0 and not args.keep_results:
        _wipe()

    return 1 if failed else 0


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    _RET_VAL: int = main()
    if _RET_VAL != 0:
        sys.exit(_RET_VAL)
