#!/usr/bin/env python

"""Informatics Matters Job Tester (JOTE).

Get help running this utility with 'jote --help'
"""
import argparse
from enum import Enum
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


class TestResult(Enum):
    """Return value from '_run_a_test()'"""

    FAILED = 0
    PASSED = 1
    SKIPPED = 2
    IGNORED = 3


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


def _add_grouped_test(
    jd_filename: str,
    job_collection: str,
    job_name: str,
    job: List[DefaultMunch],
    run_group_names: List[str],
    test_groups: List[DefaultMunch],
    grouped_job_definitions: Dict[str, Any],
) -> None:
    """Adds a job definition to a test group for a job-definition file.

    grouped_job_definitions is a map, indexed by JD filename.
    It contains a list of dictionaries that are the set of group tests
    """

    for run_group_name in run_group_names:

        # Find the test-group for this test
        test_group_definition: Optional[DefaultMunch] = None
        for test_group in test_groups:
            if test_group.name == run_group_name:
                test_group_definition = test_group
                break
        assert test_group_definition

        # Does the file already exist in the definition?
        if jd_filename not in grouped_job_definitions:
            # First group of tests for this file
            grouped_job_definitions[jd_filename] = [
                {
                    "test-group-name": run_group_name,
                    "test-group": test_group_definition,
                    "jobs": [(job_collection, job_name, job)],
                }
            ]
        else:
            # We already have some group definitions for this file.
            # Is this a new test group or a job for an exitign test group?
            found_test_group: bool = False
            for existing_file_run_groups in grouped_job_definitions[jd_filename]:
                # The value of the map is a dictionary containing
                # the group name, the group definition and the list of jobs.
                if existing_file_run_groups["test-group-name"] == run_group_name:
                    # Another job for an existing test group
                    existing_file_run_groups["jobs"].append(
                        (job_collection, job_name, job)
                    )
                    found_test_group = True
            # Did we find an existing test group?
            if not found_test_group:
                # First test for this group in the job definition file
                grouped_job_definitions[jd_filename].append(
                    {
                        "test-group-name": run_group_name,
                        "test-group": test_group_definition,
                        "jobs": [(job_collection, job_name, job)],
                    }
                )


def _load(
    manifest_filename: str, skip_lint: bool
) -> Tuple[List[DefaultMunch], Dict[str, Any], int]:
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
        return [], {}, -1

    if not _validate_manifest_schema(manifest_path):
        return [], {}, -1

    with open(manifest_path, "r", encoding="UTF-8") as manifest_file:
        manifest: Dict[str, Any] = yaml.load(manifest_file, Loader=yaml.FullLoader)
    manifest_munch: Optional[DefaultMunch] = None
    if manifest:
        manifest_munch = DefaultMunch.fromDict(manifest)
    assert manifest_munch

    # Iterate through the named files.
    # 'job_definitions' are all those jobs that have at least one test that is not
    # part of a 'run-group'. 'grouped_job_definitions' are all the definitions that
    # are part of a 'run-group', indexed by group name.
    # the 'grouped_job_definitions' structure is:
    #
    # - <job-definition filename>
    #   - <test group name>
    #     <test compose file>
    #     - <job-definition>
    #
    job_definitions: List[DefaultMunch] = []
    grouped_job_definitions: Dict[str, Any] = {}
    num_tests: int = 0

    for jd_filename in manifest_munch["job-definition-files"]:

        # Does the definition comply with the schema?
        # No options here - it must.
        jd_path: str = os.path.join(_DEFINITION_DIRECTORY, jd_filename)
        if not _validate_schema(jd_path):
            return [], {}, -1

        # YAML-lint the definition?
        if not skip_lint:
            if not _lint(jd_path):
                return [], {}, -2

        # Load the Job definitions optionally compiling a set of 'run-groups'
        with open(jd_path, "r", encoding="UTF-8") as jd_file:
            job_def: Dict[str, Any] = yaml.load(jd_file, Loader=yaml.FullLoader)

        if job_def:
            jd_munch: DefaultMunch = DefaultMunch.fromDict(job_def)

            jd_collection: str = jd_munch["collection"]

            # Test groups defined in this file...
            test_groups: List[DefaultMunch] = []
            if "test-groups" in jd_munch:
                for test_group in jd_munch["test-groups"]:
                    test_groups.append(test_group)

            # Process each job.
            # It goes into 'job_definitions' if it has at least one non-grouped test,
            # and into 'grouped_job_definitions' if it has at least one grouped test.
            for jd_name in jd_munch.jobs:
                test_run_group_names: List[str] = []
                if jd_munch.jobs[jd_name].tests:
                    # Job has some tests
                    num_tests += len(jd_munch.jobs[jd_name].tests)
                    for job_test in jd_munch.jobs[jd_name].tests:
                        # Is there a run-group defined for this test?
                        if "run-groups" in jd_munch.jobs[jd_name].tests[job_test]:
                            # Do the run-groups exists (in test-groups)
                            for run_group in jd_munch.jobs[jd_name].tests[job_test][
                                "run-groups"
                            ]:
                                group_exists: bool = False
                                for test_group in test_groups:
                                    if run_group.name == test_group.name:
                                        group_exists = True
                                        break
                                if not group_exists:
                                    print(
                                        f'! Test "{job_test}" for Job "{jd_name}"'
                                        f' refers to unknown run-group "{run_group.name}"'
                                    )
                                    return [], {}, -3
                                test_run_group_names.append(run_group.name)
                    if test_run_group_names:
                        _add_grouped_test(
                            jd_path,
                            jd_collection,
                            jd_name,
                            jd_munch.jobs[jd_name],
                            test_run_group_names,
                            test_groups,
                            grouped_job_definitions,
                        )

            # Job definitions is simply a copy of the whole decoded file.
            job_definitions.append(jd_munch)

    return job_definitions, grouped_job_definitions, num_tests


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
    *,
    command: str,
    project_path: str,
    nextflow_config_file: str,
    test_environment: Optional[Dict[str, str]] = None,
    timeout_minutes: int = DEFAULT_TEST_TIMEOUT_M,
) -> Tuple[int, str, str]:
    """Runs nextflow in the project directory returning the exit code,
    stdout and stderr.
    """
    assert command
    assert project_path

    print('# Executing the test ("nextflow")...')

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

    # Is there a Nextflow config file defined for this test?
    # It's a file in the 'data-manager' directory.
    if nextflow_config_file:
        print(
            f'# Copying nextflow config file ("{nextflow_config_file}") to {project_path}'
        )
        shutil.copyfile(
            os.path.join("data-manager", nextflow_config_file),
            os.path.join(project_path, "nextflow.config"),
        )

    print(f'# Execution directory is "{project_path}"')

    cwd = os.getcwd()
    os.chdir(project_path)

    # Inject an environment?
    # Yes if some variables are provided.
    # We copy the exiting env and add those provided.
    env: Optional[Dict[str, Any]] = None
    if test_environment:
        env = os.environ.copy()
        env.update(test_environment)

    try:
        test = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            timeout=timeout_minutes * 60,
            env=env,
        )
    finally:
        os.chdir(cwd)

    return test.returncode, test.stdout.decode("utf-8"), test.stderr.decode("utf-8")


def _run_a_test(
    args: argparse.Namespace,
    filename: str,
    collection: str,
    job: str,
    job_test_name: str,
    job_definition: DefaultMunch,
    test_group: str = "",
    test_group_ordinal: int = 0,
    test_group_environment: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Compose], TestResult]:
    """Runs a singe test printing a test group and non-zero optional ordinal,
    which is used for group test runs. If a test group is provided a valid ordinal
    (1..N) must also be used."""

    _print_test_banner(collection, job, job_test_name)

    # The status changes to False if any
    # part of this block fails.
    print(f"> definition filename={filename}")

    # Does the test have an 'ignore' declaration?
    # Obey it unless the test is named explicitly -
    # i.e. if th user has named a specific test, run it.
    if "ignore" in job_definition.tests[job_test_name]:
        if args.test:
            print("W Ignoring the ignore: property (told to run this test)")
        else:
            print('W Ignoring test (found "ignore")')
            return None, TestResult.IGNORED

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
                return None, TestResult.SKIPPED
        else:
            print("> run-level=Undefined")

    # Was a test group ordinal provided?
    if test_group:
        assert test_group_ordinal > 0
        print(f"> test-group={test_group} ordinal={test_group_ordinal}")

    # Render the command for this test.

    # First extract any variables and values from 'options' (if there are any).
    job_variables: Dict[str, Any] = {}
    if job_definition.tests[job_test_name].options:
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
                    f"! Test variable ({variable})" + " not declared as input or option"
                )
                # Record but do no further processing
                return None, TestResult.FAILED

            if variable_is_input:
                # Is it an input (not an option).
                # The input is a list if it's declared as 'multiple'
                if job_definition.variables.inputs.properties[variable].multiple:
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
            if test_group_environment and env_name in test_group_environment:
                # The environment variable is provided by the test group,
                # we don't need to go to the OS, we'll use what's provided.
                env_value: Optional[str] = str(test_group_environment[env_name])
            else:
                env_value = os.environ.get(env_name, None)
                if env_value is None:
                    print("! FAILURE")
                    print("! Test environment variable is not defined")
                    print(f"! variable={env_name}")
                    # Record but do no further processing
                    return None, TestResult.FAILED
            assert env_value
            test_environment[env_name] = env_value

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
        return None, TestResult.FAILED

    # The command must not contain new-lines.
    # So split then join the command.
    assert decoded_command
    job_command: str = "".join(decoded_command.splitlines())

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

    print(f"> image={job_image}")
    print(f"> image-type={job_image_type}")
    print(f"> command={job_command}")

    # Create the project
    t_compose: Compose = Compose(
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
    project_path: str = t_compose.create()

    if input_files:
        # Copy the data into the test's project directory.
        # Data's expected to be found in the Job's 'inputs'.
        if not _copy_inputs(input_files, project_path):
            return t_compose, TestResult.FAILED

    # Run the container
    if not args.dry_run:

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

            # Is there a nextflow config file for this test?
            nextflow_config_file: str = ""
            if "nextflow-config-file" in job_definition.tests[job_test_name]:
                nextflow_config_file = job_definition.tests[job_test_name][
                    "nextflow-config-file"
                ]

            exit_code, out, err = _run_nextflow(
                command=job_command,
                project_path=project_path,
                nextflow_config_file=nextflow_config_file,
                test_environment=test_environment,
                timeout_minutes=timeout_minutes,
            )
        else:
            print("! FAILURE")
            print(f"! unsupported image-type ({job_image_type}")
            return t_compose, TestResult.FAILED

        expected_exit_code: int = job_definition.tests[job_test_name].checks.exitCode

        if exit_code != expected_exit_code:
            print("! FAILURE")
            print(
                f"! exit_code={exit_code}" f" expected_exit_code={expected_exit_code}"
            )
            print("! Test stdout follows...")
            print(out)
            print("! Test stderr follows...")
            print(err)
            return t_compose, TestResult.FAILED

        if args.verbose:
            print(out)

    # Inspect the results
    # (only if successful so far)
    if not args.dry_run and job_definition.tests[job_test_name].checks.outputs:
        assert t_compose
        if not _check(
            t_compose,
            job_definition.tests[job_test_name].checks.outputs,
            job_image_fix_permissions,
        ):
            return t_compose, TestResult.FAILED

    # Success.
    # If dry-run was set the test wasn't actually run.
    return t_compose, TestResult.PASSED


def _run_ungrouped_tests(
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

    for job_test_name in job_definition.tests:

        # If a job test has been named,
        # skip this test if it doesn't match.
        # We do not include this test in the count.
        if args.test and not args.test == job_test_name:
            continue

        # If the test is part of a group then skip it.
        # We only run ungrouped tests here.
        if "run-groups" in job_definition.tests[job_test_name]:
            continue

        # Now run the test...
        compose, test_result = _run_a_test(
            args,
            filename,
            collection,
            job,
            job_test_name,
            job_definition,
        )

        # Clean-up?
        if test_result == TestResult.PASSED and not args.keep_results:
            assert compose
            compose.delete()

        # Count?
        if test_result == TestResult.PASSED:
            print("- SUCCESS")
            tests_passed += 1
        elif test_result == TestResult.FAILED:
            tests_failed += 1

        # Told to stop on first failure?
        if test_result == TestResult.FAILED and args.exit_on_failure:
            break

    return tests_passed, tests_skipped, tests_ignored, tests_failed


def _run_grouped_tests(
    args: argparse.Namespace,
    grouped_job_definitions: Dict[str, Any],
) -> Tuple[int, int, int, int]:
    """Runs grouped tests.
    Test provided indexed by job-definition file path.
    Here we run all the tests that belong to a group without resetting
    between the tests. At the end of each group we clean up.
    """

    # The test status, assume success
    tests_passed: int = 0
    tests_skipped: int = 0
    tests_ignored: int = 0
    tests_failed: int = 0

    # 'grouped_job_definitions' is a dictionary indexed by
    # the job-definition path and filename. For each entry there's a list
    # that contains the 'group-name', the 'test-group' and a list of 'jobs'.
    # 'test-group' is the test group from the original definition
    # (i.e. having a name, optional compose-file, and optional environment)
    # and 'jobs' is a list of job definitions (DefaultMunch stuff) for jobs
    # that have at least one test that runs in that group.
    #
    # See '_add_grouped_test()', which is used by _load() to build the map.

    test_result: Optional[TestResult] = None
    for jd_filename, grouped_tests in grouped_job_definitions.items():

        # The grouped definitions are indexed by JobDefinition filename
        # and for each there is a list of dictionaries (indexed by group name).
        for file_run_group in grouped_tests:

            run_group_name: str = file_run_group["test-group-name"]
            if args.run_group and run_group_name != args.run_group:
                # A specific group has been named
                # and this isn't it, so skip these tests.
                continue
            group_struct: Dict[str, Any] = file_run_group["test-group"]
            jobs: List[Tuple[str, str, DefaultMunch]] = file_run_group["jobs"]

            # We have a run-group structure (e.g.  a name and optional compose file)
            # and a list of jobs (job definitions), each with at least one test in
            # the group. We collect the following into a 'grouped_tests' list: -
            #  0 - the name of the run-group,
            #  1 - the test ordinal
            #  2 - the job collection
            #  3 - the job name
            #  4 - the job test name
            #  5 - the job definition
            #
            # We'll sort after we've collected every test for this group.
            #
            # The job is a DefaultMunch and contains everything for that
            # job, including its tests.
            grouped_tests = []
            for job in jobs:
                # the 'job' is a tuple of collection, job name and DefaultMunch.
                # The Job will have a tests section.
                for job_test_name in job[2].tests:
                    if "run-groups" in job[2].tests[job_test_name]:
                        for run_group in job[2].tests[job_test_name]["run-groups"]:
                            if run_group.name == run_group_name:
                                # OK - we have a test for this group.
                                # Assume we've not seen his before...
                                new_test: bool = True
                                for existing_group_test in grouped_tests:
                                    # Have we seen this before?
                                    # If not the ordinal cannot exist in a different
                                    # collection or job.
                                    if (
                                        existing_group_test[2] == job[0]
                                        and existing_group_test[3] == job[1]
                                        and existing_group_test[4] == job_test_name
                                    ):

                                        new_test = False
                                        break

                                    if run_group.ordinal == existing_group_test[1] and (
                                        existing_group_test[2] != job[0]
                                        or existing_group_test[3] != job[1]
                                    ):

                                        # Oops - ordinal used elsewhere in this group.
                                        # Return a failure!
                                        print("! FAILURE")
                                        print(
                                            f"! Test '{job_test_name}' ordinal"
                                            f" {run_group.ordinal} is not unique"
                                            f" within test group '{run_group.name}'"
                                        )
                                        tests_failed += 1
                                        return (
                                            tests_passed,
                                            tests_skipped,
                                            tests_ignored,
                                            tests_failed,
                                        )

                                if new_test:
                                    # New test in the group with a unique ordinal.
                                    grouped_tests.append(
                                        (
                                            group_struct,
                                            run_group.ordinal,
                                            job[0],  # Collection
                                            job[1],  # Job (name)
                                            job_test_name,
                                            job[2],  # Job definition
                                        )
                                    )

            # We now have a set of grouped tests for a given test group in a file.
            # Sort them according to 'ordinal' (the first entry of the tuple)
            grouped_tests.sort(key=lambda tup: tup[1])

            # Now run the tests in this group...
            # 1. Apply the group compose file (if there is one)
            # 2. run the tests (in ordinal order)
            # 3. stop the compose file
            group_compose_file: Optional[str] = None
            for index, grouped_test in enumerate(grouped_tests):

                # For each grouped test we have a test-group definition [at index 0],
                # an 'ordinal' [1], 'collection' [2], 'job name' [3], 'job test' [4]
                # and the 'job' definition [5]

                # Start the group compose file?
                if index == 0 and "compose" in grouped_test[0] and not args.dry_run:
                    group_compose_file = grouped_test[0].compose.file
                    assert group_compose_file
                    # Optional post-compose (up) delay?
                    delay_seconds: int = 0
                    if "delay-seconds" in grouped_test[0].compose:
                        delay_seconds = grouped_test[0].compose["delay-seconds"]
                    # Bring 'up' the group compose file...
                    g_compose_result: bool = Compose.run_group_compose_file(
                        group_compose_file,
                        delay_seconds,
                    )
                    if not g_compose_result:
                        print("! FAILURE")
                        print(
                            f"! Test group compose file failed ({group_compose_file})"
                        )
                        break

                # Does the test group define an environment?
                test_group_environment: Dict[str, Any] = {}
                if grouped_test[0].environment:
                    for gt_env in grouped_test[0].environment:
                        key: str = list(gt_env.keys())[0]
                        value: str = str(gt_env[key])
                        test_group_environment[key] = value

                # The test
                compose, test_result = _run_a_test(
                    args,
                    jd_filename,
                    grouped_test[2],  # Collection
                    grouped_test[3],  # Job name
                    grouped_test[4],  # Test name
                    grouped_test[5],  # The job definition
                    run_group_name,
                    grouped_test[1],  # Ordinal
                    test_group_environment=test_group_environment,
                )

                # Always try and teardown the test compose
                # between tests in a group.
                if compose and not args.keep_results:
                    compose.delete()

                # And stop if any test has failed.
                if test_result == TestResult.FAILED:
                    tests_failed += 1
                    break

                if test_result == TestResult.PASSED:
                    tests_passed += 1
                elif test_result == TestResult.SKIPPED:
                    tests_skipped += 1
                elif test_result == TestResult.IGNORED:
                    tests_ignored += 1

            # Always stop the group compose file at the end of the test group
            # (if there is one)
            if group_compose_file and not args.dry_run:
                _ = Compose.stop_group_compose_file(group_compose_file)

            # Told to exit on first failure?
            if test_result == TestResult.FAILED and args.exit_on_failure:
                break

        # Told to exit on first failure?
        if test_result == TestResult.FAILED and args.exit_on_failure:
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
        "-g",
        "--run-group",
        help="The run-group of the tests you want to"
        " execute. All tests that belong to the named group"
        " will be executed",
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
    if args.run_group and args.collection:
        arg_parser.error("Cannot use --run-groups and --collection")
    if args.run_group and args.job:
        arg_parser.error("Cannot use --run-groups and --job")
    if args.run_group and args.test:
        arg_parser.error("Cannot use --run-groups and --test")

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
    job_definitions, grouped_job_definitions, num_tests = _load(
        args.manifest, args.skip_lint
    )
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
    if args.run_group:
        print(f'# Limiting to Run Group "{args.run_group}"')

    # Run ungrouped tests (unless a test group has been named)
    if not args.run_group and job_definitions:
        # We've not been told to run a test group and have at least one job-definition
        # that has a test that does not need a group.
        # These tests can be run in any order.
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

                # Skip any test that has a run-group defined.
                # These will be handled sepratately.
                if job_definition.jobs[job_name].tests:
                    (
                        num_passed,
                        num_skipped,
                        num_ignored,
                        num_failed,
                    ) = _run_ungrouped_tests(
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
            if total_failed_count > 0 and args.exit_on_failure:
                break

    # Success so far.
    # Run grouped tests?
    if grouped_job_definitions:
        num_passed, num_skipped, num_ignored, num_failed = _run_grouped_tests(
            args,
            grouped_job_definitions,
        )
        total_passed_count += num_passed
        total_skipped_count += num_skipped
        total_ignore_count += num_ignored
        total_failed_count += num_failed

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
