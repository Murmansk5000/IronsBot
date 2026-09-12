# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose the shared Seer rendering ports and disposable caches."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.htmlkit import (
    HTML_TEMPLATE_RENDERER_SOURCE_PATH,
    render_html_template,
)
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.seer_data import SEER_DATA_RENDERERS_PATH
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.integrations.storage.render_cache_version import RenderCacheVersion
from ironsbot.integrations.storage.seer_assets import build_seer_asset_store
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.render_paths import SEER_RENDERING_PATH

FINAL_RENDER_CACHE_INPUTS = (
    SEER_RENDERING_PATH,
    SEER_DATA_RENDERERS_PATH,
    HTML_TEMPLATE_RENDERER_SOURCE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.config.models.seer import RenderConfig
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.seer_data.database import SeerDatabase, SeerReadSnapshot
    from ironsbot.integrations.storage.seer_assets import SeerAssetStore
    from ironsbot.runtime.cache_paths import CachePaths
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache


@dataclass(frozen=True, slots=True)
class SeerRenderInputs:
    data: SeerReadSnapshot
    images: SeerImageSource
    cache: RenderCache


@dataclass(frozen=True, slots=True)
class SeerRenderSessions:
    database: SeerDatabase
    clients: HttpClients
    assets: SeerAssetStore
    cache: FileRenderCache
    versions: RenderCacheVersion

    @contextmanager
    def open(self) -> Iterator[SeerRenderInputs]:
        with self.database.read_snapshot() as snapshot:
            publication = snapshot.publication
            yield SeerRenderInputs(
                snapshot,
                self.assets.bind(
                    HttpSeerImageSource(
                        self.clients, asset_snapshot_getter=lambda: publication.assets
                    )
                ),
                self.cache.bind(
                    self.versions.for_version(publication.version),
                    publication.category_available,
                ),
            )


def build_seer_rendering_components(
    http_clients: HttpClients,
    cache_paths: CachePaths,
    render_config: RenderConfig,
    seer_database: SeerDatabase,
) -> tuple[SeerImageSource, RenderCoordinator, SeerRenderSessions]:
    """Build the single image source, rendered-image cache, and native gate."""
    images = build_seer_asset_store(
        HttpSeerImageSource(
            http_clients,
            asset_snapshot_getter=seer_database.render_asset_snapshot,
        ),
        cache_paths.assets_dir(),
        render_config,
    )
    versions = RenderCacheVersion(seer_database.version, FINAL_RENDER_CACHE_INPUTS)
    cache = FileRenderCache(
        cache_paths.render_dir(),
        render_config.final_cache_max_size_mb * 1024 * 1024,
        version_getter=versions,
        category_available=seer_database.render_category_available,
    )
    return (
        images,
        RenderCoordinator(
            render_html_template,
            render_config.native_timeout_seconds,
        ),
        SeerRenderSessions(seer_database, http_clients, images, cache, versions),
    )
