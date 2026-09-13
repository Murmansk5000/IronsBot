# SPDX-License-Identifier: MIT
"""Compile Bilibili target aliases into typed platform recipients."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.bilibili.target_models import (
    BiliConfiguredTargets,
    BiliTargetRule,
)
from ironsbot.services.bilibili.target_rules import (
    build_bili_target_rule,
    merge_bili_target_rules,
)

if TYPE_CHECKING:
    from ironsbot.config.platform_references import PlatformReferenceResolver
    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.platform import ConversationRef


def build_bili_configured_targets(
    config: BiliConfig,
    references: PlatformReferenceResolver,
) -> BiliConfiguredTargets:
    """Resolve each configured target to exactly one platform account."""

    group_rules: dict[ConversationRef, BiliTargetRule] = {}
    private_rules: dict[ConversationRef, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        _merge_rule(
            group_rules,
            references.group_conversation_ref(
                ref,
                location=f"bilibili.push.groups.{ref}",
            ),
            build_bili_target_rule(target_config, config),
        )
    for ref, target_config in config.push.users.items():
        _merge_rule(
            private_rules,
            references.private_conversation_ref(
                ref,
                location=f"bilibili.push.users.{ref}",
            ),
            build_bili_target_rule(target_config, config),
        )
    return BiliConfiguredTargets(group_rules, private_rules)


def _merge_rule(
    rules: dict[ConversationRef, BiliTargetRule],
    conversation: ConversationRef,
    rule: BiliTargetRule,
) -> None:
    rules[conversation] = (
        merge_bili_target_rules(rules[conversation], rule)
        if conversation in rules
        else rule
    )
