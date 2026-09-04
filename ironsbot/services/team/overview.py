# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.team.resource import TeamResourceResult


@dataclass(frozen=True, slots=True)
class TeamOverviewItem:
    team_id: int
    name: str
    member_count: int | None = None
    resource: int | None = None
    error: str = ""

    @classmethod
    def from_result(cls, result: TeamResourceResult) -> TeamOverviewItem:
        return cls(
            result.team_id, result.team_name, result.member_count, result.resource
        )

    @property
    def description(self) -> str:
        if self.error:
            return self.error
        members = self.member_count if self.member_count is not None else "暂未获取"
        return f"人数：{members}，资源数：{self.resource}"


def format_team_overview(items: Sequence[TeamOverviewItem]) -> str:
    lines = ["当前战队信息概览如下："]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. 【{item.team_id}】{item.name}\n{item.description}")
    lines.append("输入编号查看详情；群聊引用本条消息后输入，输入 0 退出。")
    return "\n".join(lines)
