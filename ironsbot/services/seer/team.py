# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_socket_recv_error
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
)
from ironsbot.services.seer.ids import TEAM_ID_ERROR_MESSAGE, is_valid_team_id

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamQueryConfig
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.team.resource import TeamResourceService

MAX_TEAM_QUERY_IDS = 3

@dataclass(frozen=True, slots=True)
class TeamQueryActor:
    user_id: int
    group_id: int | None
    can_manage: bool


class SeerTeamQueryService:
    def __init__(
        self,
        config: TeamQueryConfig,
        headless: HeadlessService,
        error_message: ErrorMessageLookup,
        team_resource: TeamResourceService,
        *,
        external_references: SeerInfoReferences | None = None,
    ) -> None:
        self._config = config
        self._headless = headless
        self._error_message = error_message
        self._team_resource = team_resource
        self._external_references = external_references

    @staticmethod
    def parse_team_ids(text: str) -> tuple[int, ...]:
        return tuple(dict.fromkeys(int(item) for item in re.findall(r"\d+", text)))

    async def query(  # noqa: C901 - distinct query failures retain their messages
        self,
        team_ids: tuple[int, ...],
        actor: TeamQueryActor,
    ) -> str:
        if len(team_ids) > MAX_TEAM_QUERY_IDS:
            return f"一次最多查询 {MAX_TEAM_QUERY_IDS} 个战队，请分开查询。"
        messages: list[str] = []
        subscription_prompt: str | None = None
        has_successful_reply = False
        for team_id in team_ids:
            if not is_valid_team_id(team_id):
                messages.append(TEAM_ID_ERROR_MESSAGE)
                continue
            try:
                message, team_info = await self._query_one(
                    team_id,
                    group_id=actor.group_id,
                )
            except (NotLoggedInError, DisconnectedError) as error:
                await self._headless.mark_unavailable(
                    str(error),
                    source="战队查询",
                )
                return _format_team_unavailable_message(team_ids[0])
            except TimeoutError:
                messages.append(_format_team_timeout_message(team_id))
                continue
            except SocketRecvError as error:
                messages.append(
                    _format_team_socket_error_message(
                        team_id,
                        format_socket_recv_error(error, self._error_message),
                    )
                )
                continue
            except Exception as error:  # noqa: BLE001
                messages.append(_format_team_generic_error_message(team_id, error))
                continue

            messages.append(message)
            has_successful_reply = True
            if subscription_prompt is None:
                subscription_prompt = self._subscription_prompt(actor, team_info)

        if subscription_prompt is not None:
            messages.append(subscription_prompt)
        reply = "\n\n".join(messages)
        if not has_successful_reply or self._external_references is None:
            return reply
        return self._external_references.append(reply, SeerInfoReference.TEAM_QUERY)

    async def _query_one(
        self,
        team_id: int,
        *,
        group_id: int | None,
    ) -> tuple[str, Any]:
        game = self._headless.get_game()
        with game.operations.track(
            "战队查询",
            f"战队 {team_id}",
            source="战队查询",
            group_id=group_id,
        ):
            team_info = await asyncio.wait_for(
                game.get_team_info(team_id),
                timeout=self._config.timeout_seconds,
            )
        await self._headless.mark_available(
            source="战队查询",
            user_id=int(game.user_id),
        )
        return (
            format_team_info(team_info, set(self._config.sections)),
            team_info,
        )

    def _subscription_prompt(
        self,
        actor: TeamQueryActor,
        team_info: Any,
    ) -> str | None:
        if actor.group_id is None:
            return None
        return self._team_resource.offer_subscription(
            group_id=actor.group_id,
            user_id=actor.user_id,
            team_id=int(team_info.team_id),
            team_name=str(team_info.name or ""),
            can_manage=actor.can_manage,
        )


def _format_team_unavailable_message(team_id: int) -> str:
    return (
        f"❌ 战队 {team_id} 暂时查不了："
        "查询需要连接赛尔号游戏服务器；当前服务器维护、未开放或无头客户端未登录。"
    )


def _format_team_timeout_message(team_id: int) -> str:
    return f"❌ 战队 {team_id} 查询超时，请稍后再试。"


def _format_team_socket_error_message(team_id: int, socket_error_text: str) -> str:
    return f"❌ 战队 {team_id} {socket_error_text}"


def _format_team_generic_error_message(team_id: int, error: object) -> str:
    return f"❌ 战队 {team_id} 查询失败：{error}"


def _append_section(
    lines: list[str],
    enabled_sections: set[str],
    section: str,
    section_lines: list[str],
) -> None:
    if section not in enabled_sections:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(section_lines)


def format_team_info(info: Any, enabled_sections: set[str]) -> str:
    slogan = info.slogan or "（无）"
    notice = info.notice or "（无）"
    lines = [f"🏰【战队信息：{info.name}】"]
    _append_section(
        lines,
        enabled_sections,
        "basic",
        [
            f"战队ID：{info.team_id}",
            f"队长：{info.leader}（米米号）",
            f"战队等级：{info.new_team_level}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "resource",
        [
            f"成员数：{info.member_count}",
            f"战队资源：{info.score}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "facilities",
        [
            "【设施等级】",
            f"科技中心：{info.tech_center_level}",
            f"奖励中心：{info.bonus_center_level}",
            f"资源中心：{info.res_center_level}",
            f"战队Boss总伤害：{info.total_boss_dmg}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "status",
        [
            "【权限与状态】",
            f"兴趣/分类值：{info.interest}",
            f"加入标记：{info.join_flag}",
            f"访问标记：{info.visit_flag}",
            f"功能禁用标记：{info.team_func_disalbed}",
            f"绘图数据：{info.drawing_uint}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "logo",
        [
            "【Logo参数】",
            f"背景：{info.logo_bg}",
            f"图标：{info.logo_icon}",
            f"颜色：{info.logo_color}",
            f"文字颜色：{info.txt_color}",
            f"Logo文字：{info.logo_word or '（无）'}",
        ],
    )
    _append_section(
        lines,
        enabled_sections,
        "text",
        [
            "【文本】",
            f"标语：{slogan}",
            f"公告：{notice}",
        ],
    )
    return "\n".join(lines)
