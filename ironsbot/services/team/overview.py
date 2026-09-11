# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.team.resource import TeamResourceResult


class TeamOverviewLoader(Protocol):
    async def __call__(self, team_id: int, fallback_name: str) -> TeamOverviewItem: ...


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


async def load_team_overview(
    subscriptions: Sequence[tuple[int, str]],
    loader: TeamOverviewLoader,
    *,
    first_team_id: int | None = None,
) -> tuple[TeamOverviewItem, ...]:
    names = dict(subscriptions)
    team_ids = list(names)
    if first_team_id is not None:
        team_ids = [
            first_team_id,
            *(item for item in team_ids if item != first_team_id),
        ]
    return tuple(
        [await loader(team_id, names.get(team_id, "")) for team_id in team_ids]
    )
