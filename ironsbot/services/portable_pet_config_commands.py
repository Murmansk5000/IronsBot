# SPDX-License-Identifier: MIT
"""Portable operation for locally maintained pet configuration images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.pet_config_commands import pet_config_input
from ironsbot.services.portable_query_sessions import (
    QueryOperationSpec,
    build_query_operation,
)

if TYPE_CHECKING:
    from ironsbot.services.pet_config import PetConfigQueryService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation


def build_portable_pet_config_operation(
    service: PetConfigQueryService,
    sessions: PortableQuerySessions,
    *,
    image_command_texts: frozenset[str] = frozenset(),
) -> PortableOperation:
    """Build the catalog-owned pet configuration query operation."""

    parser = pet_config_input(image_command_texts)
    return build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=lambda text: (
                None if (parsed := parser(text)) is None else parsed.argument
            ),
            search=service.search,
            select=service.select,
            prompt_title="请问你想查询哪只精灵的配置？",
            not_found_message=None,
        ),
    )
