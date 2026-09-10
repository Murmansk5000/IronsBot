# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - runtime handler annotations
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - runtime handler annotations

from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.semantic_requests import ActionDefinition
from ironsbot.services.seer.team import TeamQueryActor
from ironsbot.services.team.overview import (
    TeamOverviewItem,
    format_team_overview,
)
from ironsbot.services.team.resource import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService





class TeamOverviewMenus:
    def __init__(
        self,
        service: TeamResourceService,
        query: SeerTeamQueryService,
        player: PlayerService,
    ) -> None:
        self.service = service
        self.query = query
        self.player = player




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

