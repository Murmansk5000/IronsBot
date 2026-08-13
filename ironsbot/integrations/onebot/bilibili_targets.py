# SPDX-License-Identifier: MIT
"""Compile OneBot Bilibili target configuration into typed recipients."""

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
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.platform import ConversationRef


def build_onebot_bili_configured_targets(
    config: BiliConfig,
    references: OneBotReferenceResolver,
) -> BiliConfiguredTargets:
    """Resolve configured QQ aliases before Bili services see target rules."""

    return BiliConfiguredTargets(
        group_rules=_compile_group_rules(config, references),
        private_rules=_compile_private_rules(config, references),
    )


def _compile_group_rules(
    config: BiliConfig,
    references: OneBotReferenceResolver,
) -> dict[ConversationRef, BiliTargetRule]:
    rules: dict[ConversationRef, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        _merge_configured_rule(
            rules,
            references.group_conversation_refs(
                [ref],
                location=f"bilibili.push.groups.{ref}",
            ),
            build_bili_target_rule(target_config, config),
        )
    return rules


def _compile_private_rules(
    config: BiliConfig,
    references: OneBotReferenceResolver,
) -> dict[ConversationRef, BiliTargetRule]:
    rules: dict[ConversationRef, BiliTargetRule] = {}
    for ref, target_config in config.push.users.items():
        _merge_configured_rule(
            rules,
            references.private_conversation_refs(
                [ref],
                location=f"bilibili.push.users.{ref}",
            ),
            build_bili_target_rule(target_config, config),
        )
    return rules


def _merge_configured_rule(
    rules: dict[ConversationRef, BiliTargetRule],
    conversations: list[ConversationRef],
    rule: BiliTargetRule,
) -> None:
    for conversation in conversations:
        rules[conversation] = (
            merge_bili_target_rules(rules[conversation], rule)
            if conversation in rules
            else rule
        )
