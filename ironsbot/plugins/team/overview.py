# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - runtime handler annotations
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - runtime handler annotations
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - runtime rule annotations

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.onebot_reply import event_reply_message_id
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.runtime.semantic_requests import ActionDefinition
from ironsbot.services.seer.team import TeamQueryActor
from ironsbot.services.team.overview import (
    TeamOverviewItem,
    format_team_overview,
)
from ironsbot.services.team.resource import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.core.messaging import DeliveryReceipt
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService

NOTICE_ITEMS_KEY = "_team_notice_items"


@dataclass
class NoticeMenu:
    message_id: int
    items: tuple[TeamOverviewItem, ...]
    expires_at: float
    consumed_by: set[int] = field(default_factory=set)


class TeamOverviewMenus:
    def __init__(
        self,
        service: TeamResourceService,
        query: SeerTeamQueryService,
        timeout_seconds: float,
    ) -> None:
        self.service = service
        self.query = query
        self.timeout_seconds = timeout_seconds
        self.notices: dict[tuple[int, str, int], NoticeMenu] = {}

    def record_notice(
        self, receipt: DeliveryReceipt, items: tuple[TeamOverviewItem, ...]
    ) -> None:
        if receipt.message_id is None or receipt.bot_id is None:
            return
        now = monotonic()
        self.notices = {
            key: value for key, value in self.notices.items() if value.expires_at > now
        }
        key = (
            int(receipt.bot_id),
            receipt.target.target_type,
            receipt.target.target_id,
        )
        self.notices[key] = NoticeMenu(
            receipt.message_id, items, now + self.timeout_seconds
        )

    def match_notice(self, event: MessageEvent, state: T_State) -> bool:
        is_group = isinstance(event, GroupMessageEvent)
        target_id = event.group_id if is_group else event.user_id
        kind = "group" if is_group else "private"
        menu = self.notices.get((event.self_id, kind, target_id))
        if (
            menu is None
            or menu.expires_at <= monotonic()
            or event.user_id in menu.consumed_by
        ):
            return False
        reply_id = event_reply_message_id(event)
        if (is_group or reply_id is not None) and reply_id != menu.message_id:
            return False
        if (
            not event.get_plaintext().strip().isdigit()
            or not self.service.allows_target(
                event.user_id,
                TeamResourceSubscriptionTarget(kind, target_id),
            )
        ):
            return False
        state[NOTICE_ITEMS_KEY] = menu
        return True

    async def handle_notice(
        self, matcher: Matcher, event: MessageEvent, state: T_State
    ) -> None:
        menu: NoticeMenu = state[NOTICE_ITEMS_KEY]
        if event.user_id in menu.consumed_by:
            await matcher.finish()
        menu.consumed_by.add(event.user_id)
        choice = int(event.get_plaintext().strip())
        if choice == 0:
            await finish_event_reply(matcher, event, "已退出战队概览。")
            return
        first_item = menu.items[choice - 1] if 1 <= choice <= len(menu.items) else None
        await self.open(matcher, event, menu.items, first_item=first_item)

    async def select(
        self, item: PromptItem[TeamOverviewItem], matcher: Matcher, event: Event
    ) -> None:
        if not isinstance(event, MessageEvent):
            return
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
        target = TeamResourceSubscriptionTarget(
            "group" if group_id is not None else "private", group_id or event.user_id
        )
        if not self.service.allows_target(event.user_id, target):
            await finish_event_reply(matcher, event, "当前会话未开放战队订阅查询。")
            return
        reply = await self.query.query(
            (item.value.team_id,),
            TeamQueryActor(
                event.user_id,
                group_id,
                can_manage_group_event(self.service, event),
            ),
        )
        await send_event_reply(matcher, event, reply)

    async def open(
        self,
        matcher: Matcher,
        event: MessageEvent,
        items: tuple[TeamOverviewItem, ...],
        *,
        first_item: TeamOverviewItem | None = None,
    ) -> None:
        async def initial_reply() -> str:
            if first_item is not None:
                await self.select(PromptItem("", "", first_item), matcher, event)
            return format_team_overview(items)

        await enter_prompt(
            matcher,
            event,
            matcher.state,
            Prompt(
                title="当前战队信息概览如下：",
                items=[
                    PromptItem(f"【{item.team_id}】{item.name}", item.description, item)
                    for item in items
                ],
                action=ActionDefinition("team_resource_detail", "战队详情"),
            ),
            self.select,
            # Reserve menu input before waiting for the first live query.
            prompt_message=initial_reply()
            if first_item is not None
            else format_team_overview(items),
        )

    def install(self, registry: MatcherRegistry) -> None:
        self.service.notice_observers.append(self.record_notice)
        matcher = registry.on_message(
            policy=CommandPolicy.exempt("team resource notification menu"),
            rule=Rule(self.match_notice) & explicit_command(),
            priority=registry.priority("team_resource_subscription"),
            block=True,
        )
        matcher.append_handler(self.handle_notice)
