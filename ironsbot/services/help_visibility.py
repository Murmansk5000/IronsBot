# SPDX-License-Identifier: MIT
"""Platform-neutral help visibility predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.feature_policy import FeatureService


def always_help_visible(_context: CommandContext) -> bool:
    return True


def feature_help_visible(
    context: CommandContext,
    *,
    features: FeatureService,
    feature: str,
    enabled: bool = True,
    group_only: bool = False,
) -> bool:
    if not enabled or (group_only and not context.is_group):
        return False
    if context.is_group:
        return features.conversation_has_feature(context.conversation, feature)
    return features.is_feature_allowed(context.actor, context.conversation, feature)


def superuser_help_visible(
    context: CommandContext,
    *,
    features: FeatureService,
) -> bool:
    return not context.is_group and features.is_actor_superuser(context.actor)
