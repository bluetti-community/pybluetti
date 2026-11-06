"""The package's own metadata."""

from importlib.metadata import version

import pybluetti
from pybluetti import exceptions


def test_version_is_the_installed_packages() -> None:
    # Hard-coded, it stayed at 0.1.1 through every release after that one.
    assert pybluetti.__version__ == version("pybluetti")
    assert pybluetti.__version__ != "0.1.1"


def test_every_exception_is_exported() -> None:
    # A caller tells an on_error argument apart with isinstance, so every
    # exception it can receive has to be importable from the package itself.
    defined = {
        name
        for name, obj in vars(exceptions).items()
        if isinstance(obj, type) and issubclass(obj, Exception) and obj.__module__ == exceptions.__name__
    }
    assert defined
    assert defined <= set(pybluetti.__all__)
    for name in defined:
        assert getattr(pybluetti, name) is getattr(exceptions, name)
