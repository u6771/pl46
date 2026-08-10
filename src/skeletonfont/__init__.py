"""Build OpenType fonts from normalized skeleton sources."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("skeletonfont")
except PackageNotFoundError:
    __version__ = "0+unknown"


__all__ = ["__version__"]
