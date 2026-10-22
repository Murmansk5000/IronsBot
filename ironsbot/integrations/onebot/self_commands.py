# SPDX-License-Identifier: MIT
"""Opt-in own-account commands at the OneBot transport boundary."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Adapter, Bot, Event, GroupMessageEvent
from nonebot.adapters.onebot.v11.exception import (
    ActionFailed,
    ApiNotAvailable,
    NetworkError,
)
from pydantic import ValidationError

from ironsbot.integrations.onebot.errors import (
    OneBotActionError,
    OneBotTransportError,
)
from ironsbot.integrations.onebot.message_envelope import OneBotMessageEnvelope
from ironsbot.integrations.onebot.message_segments import (
    OneBotMessageDecodeError,
    decode_onebot_segments,
)
from ironsbot.integrations.onebot.native_reverse import NativeOneBotReverseServer

if TYPE_CHECKING:
    from nonebot.drivers import Driver, WebSocket

    from ironsbot.core.tasks import TaskSpawner

logger = logging.getLogger(__name__)


class SentGroupMessageEvent(GroupMessageEvent):
    """Tag an own-account sent event while the native host uses message matchers."""


class SelfCommandAdapter(Adapter):
    def __init__(self, driver: Driver, *, spawn: TaskSpawner, **kwargs: Any) -> None:
        super().__init__(driver, **kwargs)
        self.reverse_server = NativeOneBotReverseServer(self, spawn)

    async def _handle_ws(self, websocket: WebSocket) -> None:
        await self.reverse_server.handle(websocket)

    async def _stop(self) -> None:
        await self.reverse_server.close()
        await super()._stop()

    async def _call_api(self, bot: Bot, api: str, **data: Any) -> Any:
        if session := self.reverse_server.session_for(bot):
            return await session.call_api(api, **data)
        try:
            return await super()._call_api(bot, api, **data)
        except ActionFailed as error:
            retcode = error.info.get("retcode")
            raise OneBotActionError(retcode if type(retcode) is int else None) from None
        except ApiNotAvailable:
            raise OneBotTransportError(definitely_not_sent=True) from None
        except NetworkError:
            raise OneBotTransportError from None

    @classmethod
    def json_to_event(cls, json_data: Any) -> Event | None:
        if (
            isinstance(json_data, dict)
            and "post_type" in json_data
            and not isinstance(json_data["post_type"], str)
        ):
            logger.warning("OneBot event rejected: invalid post type")
            return None
        if isinstance(json_data, dict) and json_data.get("post_type") in (
            "message",
            "message_sent",
        ):
            try:
                json_data = {
                    **json_data,
                    "message": decode_onebot_segments(json_data.get("message")),
                }
                if "original_message" in json_data:
                    json_data["original_message"] = decode_onebot_segments(
                        json_data["original_message"]
                    )
            except OneBotMessageDecodeError:
                logger.warning("OneBot message rejected: invalid message segments")
                return None
            if json_data["post_type"] == "message":
                try:
                    json_data = OneBotMessageEnvelope.model_validate(
                        json_data
                    ).model_dump(exclude_unset=True)
                except ValidationError:
                    logger.warning("OneBot message rejected: invalid message envelope")
                    return None
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
