"""The Job Tester 'compose' module.

This module is responsible for injecting a docker-compose file into the
repository of the Data Manager Job repository under test. It also
executes docker-compose and can remove the test directory.
"""
import copy
import os
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

INSTANCE_DIRECTORY: str = ".instance-88888888-8888-8888-8888-888888888888"

# A default test execution timeout
DEFAULT_TEST_TIMEOUT_M: int = 10

# The user id containers will be started as
_USER_ID: int = 8888

_COMPOSE_CONTENT: str = """---
version: '2.4'
services:
  job:
    image: {image}
    container_name: {job}-{test}-jote
    user: '{uid}'
    entrypoint: /bin/sh
    command: {working_directory}/{instance_directory}/command
    working_dir: {working_directory}
    volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - {test_path}:{project_directory}
    mem_limit: {memory_limit}
    cpus: {cpus}.0
    environment:
    - DM_INSTANCE_DIRECTORY={instance_directory}
{additional_environment}
"""

_NF_CONFIG_CONTENT: str = """
docker.enabled = true
docker.runOptions = '-u $(id -u):$(id -g)'
"""


def _get_docker_compose_version() -> str:

    result = subprocess.run(
        ["docker-compose", "version"], capture_output=True, check=False, timeout=4
    )

    # stdout will contain the version on the first line: -
    # "docker-compose version 1.29.2, build unknown"
    # Ignore the first 23 characters of the first line...
    return str(result.stdout.decode("utf-8").split("\n")[0][23:])


def get_test_root() -> str:
    """Returns the root of the testing directory."""
    cwd: str = os.getcwd()
    return f"{cwd}/data-manager/jote"


class Compose:
    """A class handling the execution of 'docker-compose'
    for an individual test.
    """

    # The docker-compose version (for the first test)
    _COMPOSE_VERSION: Optional[str] = None

    def __init__(
        self,
        collection: str,
        job: str,
        test: str,
        image: str,
        image_type: str,
        memory: str,
        cores: int,
        project_directory: str,
        working_directory: str,
        command: str,
        test_environment: Dict[str, str],
        user_id: Optional[int] = None,
    ):

        # Memory must have a Mi or Gi suffix.
        # For docker-compose we translate to 'm' and 'g'
        if memory.endswith("Mi"):
            self._memory: str = f"{memory[:-2]}m"
        elif memory.endswith("Gi"):
            self._memory = f"{memory[:-2]}g"
        assert self._memory

        self._collection: str = collection
        self._job: str = job
        self._test: str = test
        self._image: str = image
        self._image_type: str = image_type
        self._cores: int = cores
        self._project_directory: str = project_directory
        self._working_directory: str = working_directory
        self._command: str = command
        self._test_environment = copy.deepcopy(test_environment)
        self._user_id: Optional[int] = user_id

    def get_test_path(self) -> str:
        """Returns the path to the root directory for a given test."""
        root: str = get_test_root()
        return f"{root}/{self._collection}.{self._job}.{self._test}"

    def get_test_project_path(self) -> str:
        """Returns the path to the root directory for a given test."""
        test_path: str = self.get_test_path()
        return f"{test_path}/project"

    def create(self) -> str:
        """Writes a docker-compose file
        and creates the test directory structure returning the
        full path to the test (project) directory.
        """

        print("# Creating test environment...")

        # First, delete
        test_path: str = self.get_test_path()
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

        # Do we have the docker-compose version the user's installed?
        if not Compose._COMPOSE_VERSION:
            Compose._COMPOSE_VERSION = _get_docker_compose_version()
            print(f"# docker-compose ({Compose._COMPOSE_VERSION})")

        # Make the test directory
        # (where the test is launched from)
        # and the project directory (a /project sud-directory of test)
        test_path = self.get_test_path()
        project_path: str = self.get_test_project_path()
        inst_path: str = f"{project_path}/{INSTANCE_DIRECTORY}"
        if not os.path.exists(inst_path):
            os.makedirs(inst_path)

        # Run as a specific user ID?
        if self._user_id is not None:
            user_id = self._user_id
        else:
            user_id = os.getuid()

        # Write the Docker compose content to a file in the test directory
        additional_environment: str = ""
        if self._test_environment:
            for e_name, e_value in self._test_environment.items():
                additional_environment += f"    - {e_name}='{e_value}'\n"
        variables: Dict[str, Any] = {
            "test_path": project_path,
            "job": self._job,
            "test": self._test,
            "image": self._image,
            "memory_limit": self._memory,
            "cpus": self._cores,
            "uid": user_id,
            "project_directory": self._project_directory,
            "working_directory": self._working_directory,
            "instance_directory": INSTANCE_DIRECTORY,
            "additional_environment": additional_environment,
        }
        compose_content: str = _COMPOSE_CONTENT.format(**variables)
        compose_path: str = f"{test_path}/docker-compose.yml"
        with open(compose_path, "wt", encoding="UTF-8") as compose_file:
            compose_file.write(compose_content)

        # Now write the command to the instance directory, as `command`.
        command_path: str = f"{inst_path}/command"
        with open(command_path, "wt", encoding="UTF-8") as command_file:
            command_file.write(self._command)

        # nextflow config?
        if self._image_type == "nextflow":
            # Write a nextflow config to the project path
            # (this is where the non-container-based nextflow is executed)
            # and where nextflow will, by default, look for the config.
            nf_cfg_path: str = f"{project_path}/nextflow.config"
            with open(nf_cfg_path, "wt", encoding="UTF-8") as nf_cfg_file:
                nf_cfg_file.write(_NF_CONFIG_CONTENT)

        print("# Created")

        return project_path

    def run(
        self, timeout_minutes: int = DEFAULT_TEST_TIMEOUT_M
    ) -> Tuple[int, str, str]:
        """Runs the container for the test, expecting the docker-compose file
        written by the 'create()'. The container exit code is returned to the
        caller along with the stdout and stderr content.
        A non-zero exit code does not necessarily mean the test has failed.
        """

        execution_directory: str = self.get_test_path()

        print('# Executing the test ("docker-compose up")...')
        print(f'# Execution directory is "{execution_directory}"')

        cwd = os.getcwd()
        os.chdir(execution_directory)

        try:
            # Run the container
            # and then cleanup
            test = subprocess.run(
                [
                    "docker-compose",
                    "up",
                    "--exit-code-from",
                    "job",
                    "--abort-on-container-exit",
                ],
                capture_output=True,
                timeout=timeout_minutes * 60,
                check=False,
            )
            _ = subprocess.run(
                ["docker-compose", "down"],
                capture_output=True,
                timeout=240,
                check=False,
            )
        finally:
            os.chdir(cwd)

        print(f"# Executed (exit code {test.returncode})")

        return test.returncode, test.stdout.decode("utf-8"), test.stderr.decode("utf-8")

    def delete(self) -> None:
        """Deletes a test directory created by 'create()'."""
        print("# Deleting the test...")

        test_path: str = self.get_test_path()
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

        print("# Deleted")
