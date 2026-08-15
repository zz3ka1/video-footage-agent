"""Video Footage Agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("video-footage-agent")
except PackageNotFoundError:  # Running from a source checkout.
    __version__ = "0.1.0"

__all__ = ["__version__"]
