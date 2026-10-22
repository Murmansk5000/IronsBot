# SPDX-License-Identifier: MIT
"""Opt-in own-account commands at the OneBot transport boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Adapter, Bot, Event, GroupMessageEvent
from nonebot.adapters.onebot.v11.exception import (
    ActionFailed,
    ApiNotAvailable,
    NetworkError,
)

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.errors import (
    OneBotActionError,
    OneBotTransportError,
)
from ironsbot.integrations.onebot.message_segments import onebot_own_account_input

if TYPE_CHECKING:
    from ironsbot.core.own_commands import OwnAccountInput


class SentGroupMessageEvent(GroupMessageEvent):
    """Tag an own-account sent event while the native host uses message matchers."""


class SelfCommandAdapter(Adapter):
    async def _call_api(self, bot: Bot, api: str, **data: Any) -> Any:
        try:
            return await super()._call_api(bot, api, **data)
        except ActionFailed as error:
            retcode = error.info.get("retcode")
            raise OneBotActionError(
                retcode if type(retcode) is int else None
            ) from None
        except ApiNotAvailable:
            raise OneBotTransportError(definitely_not_sent=True) from None
        except NetworkError:
            raise OneBotTransportError from None

    @classmethod
    def json_to_event(cls, json_data: Any) -> Event | None:
        if (
            isinstance(json_data, dict)
            and json_data.get("post_type") == "message_sent"
            and json_data.get("message_type") == "group"
            and json_data.get("user_id") == json_data.get("self_id")
        ):
            return SentGroupMessageEvent.model_validate(
                {**json_data, "post_type": "message"}
            )
        return super().json_to_event(json_data)


def own_account_input(event: SentGroupMessageEvent) -> OwnAccountInput:
    result = onebot_own_account_input(
        str(event.self_id),
        ConversationRef(Platform.ONEBOT, "group", str(event.group_id)),
        [
            {"type": segment.type, "data": segment.data}
            for segment in (event.original_message or event.message)
        ],
        is_own_message=event.user_id == event.self_id,
    )
    assert result is not None
    return result
