"""Tests for the jote 'compose' module.

These focus on the requirement (issue #10) that constructing the Compose
harness (as done during a '--dry-run') must not probe 'docker compose'.
"""

from unittest import mock

from jote.compose import Compose


def _make_compose() -> Compose:
    return Compose(
        collection="collection",
        job="job",
        test="test",
        image="image:1.0.0",
        image_type="simple",
        memory="1Gi",
        cores=1,
        project_directory="/data",
        working_directory="/data",
        command="echo hello",
        environment={},
    )


def test_construction_does_not_probe_docker_compose():
    # Given a patched docker-compose probe
    with mock.patch("jote.compose._get_docker_compose_command") as probe:
        # When we construct a Compose harness (as '--dry-run' does)
        _make_compose()
        # Then the docker-compose command must not have been probed
        probe.assert_not_called()


def test_create_does_not_probe_docker_compose(tmp_path, monkeypatch):
    # Given a working directory and a patched docker-compose probe
    monkeypatch.chdir(tmp_path)
    with mock.patch("jote.compose._get_docker_compose_command") as probe:
        # When we construct and 'create()' the test environment
        compose = _make_compose()
        compose.create()
        # Then the docker-compose command must not have been probed
        probe.assert_not_called()
