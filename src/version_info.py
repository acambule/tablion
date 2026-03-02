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
    display = os.environ.get(DISPLAY_ENV)
    if display:
        return display

    release = os.environ.get(RELEASE_ENV)
    if release:
        return f"{_package_version()}-{release}"

    return _package_version()
