# SPDX-License-Identifier: MIT
"""Canonical frozen destinations using the existing shared routing policy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.services.bilibili.target_models import BiliPushTargets

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.private_conversation_routes import PrivateConversationRoutes

_LOGGER = logging.getLogger(__name__)


def canonical_targets(
    routes: PrivateConversationRoutes | None, targets: BiliPushTargets
) -> BiliPushTargets:
    def selected(conversations: Iterable[ConversationRef]) -> list[ConversationRef]:
        result = []
        for target in conversations:
            decision = routes.decision_for(target) if routes else None
            if decision is not None and decision.status == "skipped":
                _LOGGER.info(
                    "Bilibili target skipped by routing policy: recipient=%s reason=%s",
                    reference_digest(target.id),
                    decision.reason,
                )
                continue
            result.append(decision.target if decision is not None else target)
        return list(dict.fromkeys(result))

    full_groups = selected(targets.full_group_conversations)
    full_privates = selected(targets.full_private_conversations)
    full = {*full_groups, *full_privates}
    return BiliPushTargets(
        full_group_conversations=full_groups,
        link_group_conversations=[
            target
            for target in selected(targets.link_group_conversations)
            if target not in full
        ],
        full_private_conversations=full_privates,
        link_private_conversations=[
            target
            for target in selected(targets.link_private_conversations)
            if target not in full
        ],
    )
