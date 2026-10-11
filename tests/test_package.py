"""The package's own metadata."""

from importlib.metadata import version

import pybluetti


def test_version_is_the_installed_packages() -> None:
    # Hard-coded, it stayed at 0.1.1 through every release after that one.
    assert pybluetti.__version__ == version("pybluetti")
    assert pybluetti.__version__ != "0.1.1"
