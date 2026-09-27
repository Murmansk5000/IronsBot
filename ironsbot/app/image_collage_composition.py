# SPDX-License-Identifier: MIT
"""Shared image collage service for features that send multiple images."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.integrations.animated_collage import (
    inspect_animation,
    render_vertical_animation,
)
from ironsbot.integrations.image_collage import (
    fetch_collage_image,
    render_adaptive_collage,
)
from ironsbot.services.messaging.image_collage import ImageCollageService

if TYPE_CHECKING:
    from httpx import AsyncClient


def build_image_collage_service(client: AsyncClient) -> ImageCollageService:
    return ImageCollageService(
        partial(fetch_collage_image, client),
        render_adaptive_collage,
        render_animation=render_vertical_animation,
        inspect_animation=inspect_animation,
    )
