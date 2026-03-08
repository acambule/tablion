"""Expose version identifiers that come from the package metadata."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version

PACKAGE_NAME = "tablion-file-manager"
DISPLAY_ENV = "TABLION_DISPLAY_VERSION"
RELEASE_ENV = "TABLION_RELEASE"


def _package_version() -> str:
    try:
        return _pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def formatted_version() -> str:
    package_version = _package_version()

    release = os.environ.get(RELEASE_ENV)
    if release:
        return f"{package_version}-{release}"

    display = os.environ.get(DISPLAY_ENV)
    if display:
        normalized = display.strip()
        # Guard against stale launcher entries carrying an old full display version.
        if normalized == package_version or normalized.startswith(f"{package_version}-"):
            return normalized

    return package_version
