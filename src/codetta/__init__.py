"""Codetta: a private, self-hosted music library manager."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("codetta")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "dev"
