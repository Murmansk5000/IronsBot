# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.commands import command_text_matches
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.permissions import can_manage_conversation_event
from ironsbot.services.bilibili.commands import (
    BILI_ACCOUNT_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    is_dynamic_update_text,
    parse_bili_push_mode_command,
)

from .account_commands import (
    BILI_PUSH_MODE_ACCOUNT_KEY,
    BILI_PUSH_MODE_RAW_KEY,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService


def is_dynamic_menu_command(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    if not event_is_feature_allowed(features, event, "bili_query"):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


def is_update_dynamic_command(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return is_dynamic_update_text(event.get_plaintext()) and (
        features.is_actor_superuser(message_input_context(event).message.actor)
    )


def is_bili_account_command(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    if not command_text_matches(event.get_plaintext(), BILI_ACCOUNT_COMMANDS):
        return False
    if event_is_feature_allowed(features, event, "bili_query"):
        return True
    return event_is_feature_allowed(
        features,
        event,
        "bili_push",
    ) and can_manage_conversation_event(features, event)


def is_bili_push_mode_command(
    features: FeatureService,
    event: MessageEvent,
    state: T_State,
) -> bool:
    if not event_is_feature_allowed(features, event, "bili_push"):
        return False
    parsed = parse_bili_push_mode_command(event.get_plaintext())
    if parsed is None:
        return False

    account, raw_mode = parsed
    state[BILI_PUSH_MODE_ACCOUNT_KEY] = account
    state[BILI_PUSH_MODE_RAW_KEY] = raw_mode
    return True
