# SPDX-License-Identifier: MIT
"""Resolve the declarative NoneBot manifest selected by bot configuration."""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from pathlib import Path

PluginManifestProfile = Literal["full", "core"]


def nonebot_manifest_path(profile: PluginManifestProfile) -> Path:
    """Return the packaged TOML file for a configured local plugin profile."""

    resource = files("ironsbot.manifests").joinpath(f"{profile}.toml")
    return cast("Path", resource)
