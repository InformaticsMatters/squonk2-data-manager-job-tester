"""The Job Tester 'compose' module.

This module is responsible for injecting a docker-compose file into the
repository of the Data Manager Job repository under test. It also
executes docker-compose and can remove the test directory.
"""
import os
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

INSTANCE_DIRECTORY: str = '.instance-88888888-8888-8888-8888-888888888888'

_COMPOSE_CONTENT: str = """---
version: '2.4'
services:
  job:
    image: {image}
    container_name: {job}-{test}-jote
    user: '{uid}'
    command: {command}
    working_dir: {working_directory}
    environment:
    - DM_INSTANCE_DIRECTORY={instance_directory}
    volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - {test_path}:{project_directory}
    mem_limit: {memory_limit}
    cpus: {cpus}.0
"""

# A default, 30 minute timeout
_DEFAULT_TEST_TIMEOUT: int = 30 * 60

# The user id containers will be started as
_USER_ID: int = 8888


def _get_docker_compose_version() -> str:

    result = subprocess.run(['docker-compose', 'version'],
                            capture_output=True, check=False, timeout=4)

    # stdout will contain the version on the first line: -
    # "docker-compose version 1.29.2, build unknown"
    # Ignore the first 23 characters of the first line...
    return str(result.stdout.decode("utf-8").split('\n')[0][23:])


def get_test_root() -> str:
    """Returns the root of the testing directory.
    """
    cwd: str = os.getcwd()
    return f'{cwd}/data-manager/jote'


class Compose:
    """A class handling the execution of 'docker-compose'
    for an individual test.
    """

    # The docker-compose version (for the first test)
    _COMPOSE_VERSION: Optional[str] = None

    def __init__(self, collection: str,
                 job: str,
                 test: str,
                 image: str,
                 memory: str,
                 cores: int,
                 project_directory: str,
                 working_directory: str,
                 command: str,
                 user_id: Optional[int] = None):

        # Memory must have a Mi or Gi suffix.
        # For docker-compose we translate to 'm' and 'g'
        if memory.endswith('Mi'):
            self._memory: str = f'{memory[:-2]}m'
        elif memory.endswith('Gi'):
            self._memory = f'{memory[:-2]}g'
        assert self._memory

        self._collection: str = collection
        self._job: str = job
        self._test: str = test
        self._image: str = image
        self._cores: int = cores
        self._project_directory: str = project_directory
        self._working_directory: str = working_directory
        self._command: str = command
        self._user_id: Optional[int] = user_id

    def get_test_path(self) -> str:
        """Returns the path to the root directory for a given test.
        """
        root: str = get_test_root()
        return f'{root}/{self._collection}.{self._job}.{self._test}'

    def get_test_project_path(self) -> str:
        """Returns the path to the root directory for a given test.
        """
        test_path: str = self.get_test_path()
        return f'{test_path}/project'

    def create(self) -> str:
        """Writes a docker-compose file
        and creates the test directory structure returning the
        full path to the test (project) directory.
        """

        print('# Creating test environment...')

        # First, delete
        test_path: str = self.get_test_path()
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

        # Do we have the docker-compose version the user's installed?
        if not Compose._COMPOSE_VERSION:
            Compose._COMPOSE_VERSION = _get_docker_compose_version()
            print(f'# docker-compose ({Compose._COMPOSE_VERSION})')

        # Make the test directory...
        test_path = self.get_test_path()
        project_path: str = self.get_test_project_path()
        inst_path: str = f'{project_path}/{INSTANCE_DIRECTORY}'
        if not os.path.exists(inst_path):
            os.makedirs(inst_path)

        # Run as a specific user ID?
        if self._user_id is not None:
            user_id = self._user_id
        else:
            user_id = os.getuid()

        # Write the Docker compose content to a file in the test directory
        variables: Dict[str, Any] =\
            {'test_path': project_path,
             'job': self._job,
             'test': self._test,
             'image': self._image,
             'memory_limit': self._memory,
             'cpus': self._cores,
             'uid': user_id,
             'command': self._command,
             'project_directory': self._project_directory,
             'working_directory': self._working_directory,
             'instance_directory': INSTANCE_DIRECTORY}
        compose_content: str = _COMPOSE_CONTENT.format(**variables)
        compose_path: str = f'{test_path}/docker-compose.yml'
        with open(compose_path, 'wt', encoding='UTF-8') as compose_file:
            compose_file.write(compose_content)

        print('# Created')

        return project_path

    def run(self) -> Tuple[int, str, str]:
        """Runs the container for the test, expecting the docker-compose file
        written by the 'create()'. The container exit code is returned to the
        caller along with the stdout and stderr content.
        A non-zero exit code does not necessarily mean the test has failed.
        """

        print('# Executing the test ("docker-compose up")...')

        cwd = os.getcwd()
        os.chdir(self.get_test_path())

        timeout: int = _DEFAULT_TEST_TIMEOUT
        try:
            # Run the container
            # and then cleanup
            test = subprocess.run(['docker-compose', 'up',
                                   '--exit-code-from', 'job',
                                   '--abort-on-container-exit'],
                                  capture_output=True,
                                  timeout=timeout,
                                  check=False)
            _ = subprocess.run(['docker-compose', 'down'],
                               capture_output=True,
                               timeout=120,
                               check=False)
        finally:
            os.chdir(cwd)

        print(f'# Executed (exit code {test.returncode})')

        return test.returncode,\
            test.stdout.decode("utf-8"),\
            test.stderr.decode("utf-8")

    def delete(self) -> None:
        """Deletes a test directory created by 'crete()'.
        """
        print('# Deleting the test...')

        test_path: str = self.get_test_path()
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

        print('# Deleted')
