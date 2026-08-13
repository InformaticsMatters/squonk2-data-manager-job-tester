"""Tests for jote's import-time dependencies.

These focus on the requirement (issue #12) that jote starts on a fresh
install. 'pkg_resources' was removed in setuptools 81, so nothing jote
imports may rely on it - importing it was what munch 2.5.0 did, and it took
jote down at startup before any work began.
"""

import subprocess
import sys
import textwrap

# Imports jote with 'pkg_resources' made unimportable, as it is on any
# environment built with setuptools >= 81.
_IMPORT_WITHOUT_PKG_RESOURCES = textwrap.dedent(
    """
    import sys

    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "pkg_resources" or name.startswith("pkg_resources."):
                raise ModuleNotFoundError("No module named 'pkg_resources'")
            return None

    sys.meta_path.insert(0, _Blocker())
    sys.modules.pop("pkg_resources", None)

    import jote.jote
    """
)


def test_imports_without_pkg_resources():
    # Given an environment with no 'pkg_resources'
    # When jote is imported
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_WITHOUT_PKG_RESOURCES],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it imports cleanly
    assert result.returncode == 0, result.stderr


def test_entry_point_runs_without_pkg_resources():
    # Given an environment with no 'pkg_resources'
    # When the jote entry point is asked for its usage
    script = _IMPORT_WITHOUT_PKG_RESOURCES + textwrap.dedent(
        """
        sys.argv = ["jote", "--help"]
        try:
            jote.jote.main()
        except SystemExit as exit_code:
            sys.exit(exit_code.code)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it prints usage rather than failing to start
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
