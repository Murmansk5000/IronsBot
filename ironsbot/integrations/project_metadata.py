# SPDX-License-Identifier: GPL-3.0-or-later
"""Read metadata injected by the build that produced this runtime."""

from __future__ import annotations

import os

PROJECT_URL_ENV = "IRONSBOT_PROJECT_URL"


def current_project_url() -> str:
    """Return the normalized project URL supplied by the build environment."""
    return os.environ.get(PROJECT_URL_ENV, "").strip().rstrip("/")
