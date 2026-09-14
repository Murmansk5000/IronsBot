# SPDX-License-Identifier: MIT
"""Opt-in OneBot transport isolation; identity observation is a separate port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters import (
    Event,  # noqa: TC002 - NoneBot resolves annotations at registration.
)
from nonebot.adapters.onebot.v11 import ActionFailed, Adapter, Bot
from nonebot.adapters.onebot.v11 import Event as OneBotEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver


READ_ONLY_APIS = frozenset(
    {
        "get_login_info",
        "get_stranger_info",
        "get_friend_list",
        "get_group_list",
        "get_group_info",
        "get_group_member_info",
        "get_group_member_list",
        "get_msg",
        "get_forward_msg",
        "get_status",
        "get_version_info",
        "can_send_image",
        "can_send_record",
    }
)


class ObserverApiRejected(ActionFailed):
    def __init__(self) -> None:
        super().__init__(
            status="failed",
            retcode=1,
            message="OneBot observer mode rejects non-read-only APIs",
        )


class ObserverOneBotAdapter(Adapter):
    async def _call_api(self, bot: Bot, api: str, **data: Any) -> Any:
        if api not in READ_ONLY_APIS:
            raise ObserverApiRejected
        return await super()._call_api(bot, api, **data)


async def ignore_observer_event(event: Event) -> None:
    if isinstance(event, OneBotEvent):
        reason = "OneBot observer mode does not execute commands"
        raise IgnoredException(reason)


def install_observer_adapter(driver: Driver) -> None:
    driver.register_adapter(ObserverOneBotAdapter)
    event_preprocessor(ignore_observer_event)
