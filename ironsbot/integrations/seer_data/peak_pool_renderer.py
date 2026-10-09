# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-pool snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageEnhance, ImageOps

from ironsbot.core.message_origin import current_message_origin
from ironsbot.services.seer.image_failure_notice import report_render_asset_failures
from ironsbot.services.seer.images import (
    ImageSourceError,
    placeholder_image,
    to_data_uri,
)
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.peak_pool import (
    PeakPoolImageAssets,
    present_peak_pool,
    render_peak_pool_document,
)

if TYPE_CHECKING:
    from ironsbot.core.outbound import ExecutionIdentity
    from ironsbot.services.seer.images import (
        ImageFailureReporter,
        ImageKind,
        SeerImageSource,
    )
    from ironsbot.services.seer.peak import PeakPoolRenderSnapshot
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

_CACHE_CATEGORY = "peak_pool"
logger = logging.getLogger(__name__)


async def render_peak_pool(  # noqa: PLR0913 - render ports and optional notice context
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    snapshot: PeakPoolRenderSnapshot,
    pool_type: str,
    *,
    image_failure_reporter: ImageFailureReporter | None = None,
    execution_identity: ExecutionIdentity | None = None,
) -> bytes:
    """Render current and historical pool positions from one immutable snapshot."""
    request_key = render_request_cache_key(_CACHE_CATEGORY, (pool_type, snapshot))
    cache_entry = cache.entry(_CACHE_CATEGORY, request_key)
    if cached := cache_entry.get():
        return cached
    assets, failures = await _load_peak_pool_image_assets(images, snapshot)
    if failures and image_failure_reporter is not None:
        origin = current_message_origin()
        await report_render_asset_failures(
            image_failure_reporter,
            failures,
            execution_identity or (origin.execution_identity if origin else None),
        )
    document = present_peak_pool(snapshot, pool_type, assets)
    rendered = await render_peak_pool_document(render_html, document)
    if not failures:
        cache_entry.put(rendered)
    return rendered


async def _load_peak_pool_image_assets(
    images: SeerImageSource,
    snapshot: PeakPoolRenderSnapshot,
) -> tuple[PeakPoolImageAssets, tuple[tuple[str, str, ImageSourceError], ...]]:
    pets = {
        pet.id: pet
        for pet in (
            *(pet for pool in snapshot.pools for pet in pool.pets),
            *(transition.pet for transition in snapshot.transitions),
        )
    }
    resource_ids = tuple(sorted({pet.resource_id for pet in pets.values()}))
    type_ids = tuple(sorted({pet.type_id for pet in pets.values() if pet.type_id > 0}))
    requests: tuple[tuple[ImageKind, str], ...] = (
        *(("pet_head", str(resource_id)) for resource_id in resource_ids),
        *(("element_type", str(type_id)) for type_id in type_ids),
    )
    results = await asyncio.gather(
        *(_load_pool_asset(images, kind, key) for kind, key in requests)
    )
    fetched = [data for data, _error in results]
    failures = tuple(
        (kind, key, error)
        for (kind, key), (_data, error) in zip(requests, results, strict=True)
        if error is not None
    )
    head_values = fetched[: len(resource_ids)]
    type_values = fetched[len(resource_ids) :]
    historical_resource_ids = {
        transition.pet.resource_id for transition in snapshot.transitions
    }
    historical_ids = tuple(
        resource_id
        for resource_id in resource_ids
        if resource_id in historical_resource_ids
    )
    head_by_resource_id = dict(zip(resource_ids, head_values, strict=True))
    dimmed_values = await asyncio.gather(
        *(
            asyncio.to_thread(
                _dim_historical_head,
                head_by_resource_id[resource_id],
            )
            for resource_id in historical_ids
        )
    )
    dimmed_by_resource_id = dict(zip(historical_ids, dimmed_values, strict=True))
    assets = PeakPoolImageAssets(
        heads=tuple(
            (resource_id, to_data_uri(value))
            for resource_id, value in zip(resource_ids, head_values, strict=True)
        ),
        historical_heads=tuple(
            (
                resource_id,
                to_data_uri(dimmed_by_resource_id.get(resource_id, value)),
            )
            for resource_id, value in zip(
                resource_ids,
                head_values,
                strict=True,
            )
        ),
        type_icons=tuple(
            (type_id, to_data_uri(value))
            for type_id, value in zip(type_ids, type_values, strict=True)
        ),
    )
    return assets, failures


async def _load_pool_asset(
    images: SeerImageSource, kind: ImageKind, key: str
) -> tuple[bytes, ImageSourceError | None]:
    try:
        return await images.fetch(kind, key, fallback=False), None
    except ImageSourceError as error:
        logger.warning(
            "peak pool asset replaced with placeholder: kind=%s key=%s error_type=%s",
            kind,
            key,
            type(error).__name__,
        )
        return placeholder_image(kind), error


def _dim_historical_head(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as source:
            rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        grayscale = ImageOps.grayscale(rgb).convert("RGB")
        dimmed = ImageEnhance.Brightness(Image.blend(rgb, grayscale, 0.75)).enhance(0.5)
        dimmed.putalpha(alpha)
        output = BytesIO()
        dimmed.save(output, format="PNG")
        return output.getvalue()
    except (OSError, ValueError):
        return data
