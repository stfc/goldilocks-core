"""Central package version identifier shared by every transport surface.

``pyproject.toml`` is the single source of truth for the version; this module
reads it from distribution metadata so transports (HTTP responses, MCP
handshake, CLI) never hardcode a value that can drift from the package build.
The fallback only covers running directly from an uninstalled source tree.
"""

from __future__ import annotations

from goldilocks_core._lint import allow_swallow

__all__ = ["package_version"]

_DEV_FALLBACK = "0.0.0+dev"


@allow_swallow
def package_version() -> str:
    """Return the installed goldilocks-core version, or a dev fallback."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("goldilocks-core")
    except PackageNotFoundError:
        return _DEV_FALLBACK
