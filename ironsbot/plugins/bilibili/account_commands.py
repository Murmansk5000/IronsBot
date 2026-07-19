# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.runtime.permissions import can_manage_conversation_event
from ironsbot.runtime.replies import finish_event_reply, message_event_target

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.core.features import FeatureService
    from ironsbot.services.bilibili.targets import BiliTargetService

BILI_PUSH_MODE_ACCOUNT_KEY = "_bili_push_mode_account"
BILI_PUSH_MODE_RAW_KEY = "_bili_push_mode_raw"


async def handle_bili_accounts_action(
    matcher: Matcher,
    event: MessageEvent,
    *,
    targets: BiliTargetService,
) -> None:
    target_type, target_id, _ = message_event_target(event)
    await finish_event_reply(
        matcher,
        event,
        targets.account_summary(target_type, target_id),
    )


async def handle_bili_push_mode_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    features: FeatureService,
    targets: BiliTargetService,
) -> None:
    if not can_manage_conversation_event(features, event):
        await finish_event_reply(
            matcher,
            event,
            "❌ 仅群主、管理员或超级管理员可用。",
        )
        return

    account_ref = str(state.get(BILI_PUSH_MODE_ACCOUNT_KEY, "") or "").strip()
    raw_mode = str(state.get(BILI_PUSH_MODE_RAW_KEY, "") or "")
    target_type, target_id, _ = message_event_target(event)
    await finish_event_reply(
        matcher,
        event,
        targets.update_push_mode(
            target_type,
            target_id,
            account_ref,
            raw_mode,
        ),
    )
