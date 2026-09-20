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
    """Resolve each configured logical target into its platform endpoints."""

    group_rules: dict[ConversationRef, BiliTargetRule] = {}
    private_rules: dict[ConversationRef, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        rule = build_bili_target_rule(target_config, config)
        for conversation in references.group_conversation_refs(
            ref,
            location=f"bilibili.push.groups.{ref}",
        ):
            _merge_rule(group_rules, conversation, rule)
    for ref, target_config in config.push.users.items():
        rule = build_bili_target_rule(target_config, config)
        for conversation in references.private_conversation_refs(
            ref,
            location=f"bilibili.push.users.{ref}",
        ):
            _merge_rule(private_rules, conversation, rule)
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
