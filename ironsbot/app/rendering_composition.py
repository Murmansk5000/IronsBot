# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose the shared Seer rendering ports and disposable caches."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec

from ironsbot.integrations.htmlkit import (
    HTML_TEMPLATE_RENDERER_SOURCE_PATH,
    render_html_template,
)
from ironsbot.integrations.htmlkit_resources import HtmlkitResources
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.litehtml import SOURCE_PATH as LITEHTML_SOURCE_PATH
from ironsbot.integrations.project_metadata import current_project_url
from ironsbot.integrations.seer_data import SEER_DATA_RENDERERS_PATH
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.integrations.storage.render_cache_version import RenderCacheVersion
from ironsbot.integrations.storage.seer_assets import build_seer_asset_store
from ironsbot.services.seer.image_failure_notice import report_render_asset_failures
from ironsbot.services.seer.render_assets import RenderAssetSession
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.render_paths import SEER_RENDERING_PATH
from ironsbot.services.seer.render_pipeline import RenderRequest, mark_render_degraded

FINAL_RENDER_CACHE_INPUTS = (
    Path(__file__),
    SEER_RENDERING_PATH.parent / "render_assets.py",
    SEER_RENDERING_PATH.parent / "render_pipeline.py",
    SEER_RENDERING_PATH.parent / "render_coordinator.py",
    SEER_RENDERING_PATH,
    SEER_RENDERING_PATH.parent / "type_calc.py",
    SEER_RENDERING_PATH.parent / "type_query.py",
    SEER_DATA_RENDERERS_PATH,
    HTML_TEMPLATE_RENDERER_SOURCE_PATH,
    HTML_TEMPLATE_RENDERER_SOURCE_PATH.with_name("htmlkit_resources.py"),
    LITEHTML_SOURCE_PATH,
)
_P = ParamSpec("_P")

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from ironsbot.config.models.seer import RenderConfig
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.seer_data.database import SeerDatabase, SeerReadSnapshot
    from ironsbot.integrations.storage.seer_assets import SeerAssetStore
    from ironsbot.runtime.cache_paths import CachePaths
    from ironsbot.services.seer.images import ImageFailureReporter, SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache


@dataclass(frozen=True, slots=True)
class SeerRenderInputs:
    data: SeerReadSnapshot
    images: SeerImageSource
    cache: RenderCache
    coordinator: RenderCoordinator
    version: str

    def guard(
        self,
        template: str,
        operation: Callable[_P, Awaitable[bytes]],
        *,
        fallback_text: str = "",
        fallback: Callable[_P, str] | None = None,
    ) -> Callable[_P, Awaitable[bytes]]:
        async def image(*args: _P.args, **kwargs: _P.kwargs) -> bytes:
            async def prepare() -> bytes:
                result = await operation(*args, **kwargs)
                if (
                    isinstance(self.images, RenderAssetSession)
                    and not self.images.complete
                ):
                    mark_render_degraded()
                return result

            return await self.coordinator.image(
                RenderRequest(
                    template,
                    fallback(*args, **kwargs)
                    if fallback is not None
                    else fallback_text,
                    self.version,
                ),
                prepare,
            )

        return image


@dataclass(frozen=True, slots=True)
class SeerRenderSessions:
    database: SeerDatabase
    clients: HttpClients
    assets: SeerAssetStore
    cache: FileRenderCache
    versions: RenderCacheVersion
    spawn: TaskSpawner
    coordinator: RenderCoordinator
    image_failure_reporter: ImageFailureReporter | None = None

    @contextmanager
    def open(self) -> Iterator[SeerRenderInputs]:
        with self.database.read_snapshot() as snapshot:
            publication = snapshot.publication
            assets = RenderAssetSession(
                self.assets.bind(
                    HttpSeerImageSource(
                        self.clients,
                        asset_snapshot_getter=lambda: publication.assets,
                        asset_blob_getter=self.database.render_asset_blob,
                    )
                ),
                self.cache.bind(
                    self.versions.for_version(publication.version),
                    publication.category_available,
                ),
                timeout_seconds=self.coordinator.timeout_seconds,
            )
            try:
                yield SeerRenderInputs(
                    snapshot, assets, assets, self.coordinator, publication.version
                )
            finally:
                if assets.failures and self.image_failure_reporter is not None:
                    failures = tuple(
                        (kind, key, error)
                        for (kind, key), error in assets.failures.items()
                    )
                    self.spawn(
                        report_render_asset_failures(
                            self.image_failure_reporter, failures, None
                        ),
                        name="render-asset-failure-notice",
                    )


def build_seer_rendering_components(
    http_clients: HttpClients,
    cache_paths: CachePaths,
    render_config: RenderConfig,
    seer_database: SeerDatabase,
    *,
    spawn: TaskSpawner,
) -> tuple[SeerImageSource, RenderCoordinator, SeerRenderSessions]:
    """Build the single image source, rendered-image cache, and native gate."""
    images = build_seer_asset_store(
        HttpSeerImageSource(
            http_clients,
            asset_snapshot_getter=seer_database.render_asset_snapshot,
            asset_blob_getter=seer_database.render_asset_blob,
        ),
        cache_paths.assets_dir(),
        render_config,
        spawn=spawn,
    )
    versions = RenderCacheVersion(seer_database.version, FINAL_RENDER_CACHE_INPUTS)
    cache = FileRenderCache(
        cache_paths.render_dir(),
        render_config.final_cache_max_size_mb * 1024 * 1024,
        version_getter=versions,
        category_available=seer_database.render_category_available,
        scope=current_project_url(),
    )
    resources = HtmlkitResources(http_clients)
    coordinator = RenderCoordinator(
        partial(
            render_html_template,
            img_fetch_fn=resources.image,
            css_fetch_fn=resources.css,
        ),
        render_config.native_timeout_seconds,
    )
    return (
        images,
        coordinator,
        SeerRenderSessions(
            seer_database, http_clients, images, cache, versions, spawn, coordinator
        ),
    )
