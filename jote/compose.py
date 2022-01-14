"""The Job Tester 'compose' module.

This module is responsible for injecting a docker-compose file into the
repository of the Data Manager Job repository under test. It also
executes docker-compose and can remove the test directory.
"""
import os
import shutil
import subprocess
from typing import Dict, Optional, Tuple

_INSTANCE_DIRECTORY: str = '.instance-88888888-8888-8888-8888-888888888888'

_COMPOSE_CONTENT: str = """---
version: '3.8'
services:
  job:
    image: {image}
    command: {command}
    working_dir: {working_directory}
    environment:
    - DM_INSTANCE_DIRECTORY={instance_directory}
    volumes:
    - {test_path}:{project_directory}
    deploy:
      resources:
        limits:
          cpus: 1
          memory: 1G
"""

# A default, 30 minute timeout
_DEFAULT_TEST_TIMEOUT: int = 30 * 60


def _get_docker_compose_version() -> str:

    result: subprocess.CompletedProcess =\
        subprocess.run(['docker-compose', 'version'],
                       capture_output=True, timeout=4)

    # stdout will contain the version on the first line: -
    # "docker-compose version 1.29.2, build unknown"
    # Ignore the first 23 characters of the first line...
    return result.stdout.decode("utf-8").split('\n')[0][23:]


class Compose:

    # The docker-compose version (for the first test)
    _COMPOSE_VERSION: Optional[str] = None

    def __init__(self, collection: str,
                 job: str,
                 test: str,
                 image: str,
                 project_directory: str,
                 working_directory: str,
                 command: str):

        self._collection = collection
        self._job = job
        self._test = test
        self._image = image
        self._project_directory = project_directory
        self._working_directory = working_directory
        self._command = command

    def get_test_path(self) -> str:
        """Returns the path to the root directory for a given test.
        """
        cwd: str = os.getcwd()
        return f'{cwd}/data-manager/jote/{self._collection}.{self._job}.{self._test}'

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
        test_path: str = self.get_test_path()
        project_path: str = self.get_test_project_path()
        inst_path: str = f'{project_path}/{_INSTANCE_DIRECTORY}'
        if not os.path.exists(inst_path):
            os.makedirs(inst_path)

        # Write the Docker compose content to a file to the test directory
        variables: Dict[str, str] = {'test_path': project_path,
                                     'image': self._image,
                                     'command': self._command,
                                     'project_directory': self._project_directory,
                                     'working_directory': self._working_directory,
                                     'instance_directory': _INSTANCE_DIRECTORY}
        compose_content: str = _COMPOSE_CONTENT.format(**variables)
        compose_path: str = f'{test_path}/docker-compose.yml'
        with open(compose_path, 'wt') as compose_file:
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
            test: subprocess.CompletedProcess =\
                subprocess.run(['docker-compose', 'up',
                                '--exit-code-from', 'job',
                                '--abort-on-container-exit'],
                               capture_output=True,
                               timeout=timeout)
            _ = subprocess.run(['docker-compose', 'down'],
                               capture_output=True,
                               timeout=120)
        finally:
            os.chdir(cwd)

        print(f'# Executed ({test.returncode})')

        return test.returncode,\
            test.stdout.decode("utf-8"),\
            test.stderr.decode("utf-8")

    def delete(self) -> None:
        """Deletes a test directory created by 'crete()'.
        """
        print(f'# Deleting the test...')

        test_path: str = self.get_test_path()
        if os.path.exists(test_path):
            shutil.rmtree(test_path)

        print('# Deleted')
