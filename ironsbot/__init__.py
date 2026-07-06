# SPDX-License-Identifier: MIT
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ironsbot")
except PackageNotFoundError:  # pragma: no cover
    __version__ = None
