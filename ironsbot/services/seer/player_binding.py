# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from datetime import datetime

class PlayerBindingState(NamedTuple):
    qq_user_id: int
    player_id: int | None = None
    player_nick: str = ""
    choice_completed: bool = False
    last_changed_at: datetime | None = None

    @property
    def is_bound(self) -> bool:
        return self.player_id is not None


class PlayerBindingStore(Protocol):
    def get(self, qq_user_id: int) -> PlayerBindingState: ...

    def bind(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
    ) -> None: ...

    def decline(self, *, qq_user_id: int) -> None: ...

    def unbind(
        self,
        *,
        qq_user_id: int,
        changed_at: datetime | None = None,
    ) -> bool: ...

def player_binding_offer_message(
    player_id: int,
    nick: str,
    *,
    unbound_daily_limit: int | None = None,
    bound_default_daily_limit: int | None = None,
) -> str:
    quota_hint = ""
    if (
        unbound_daily_limit is not None
        and bound_default_daily_limit is not None
        and bound_default_daily_limit > unbound_daily_limit
    ):
        quota_hint = (
            "设为默认米米号后，查询该米米号实时数据的每日额度可从 "
            f"{unbound_daily_limit} 次提升至 {bound_default_daily_limit} 次。\n"
        )
    return (
        f"已查到米米号：{player_id}（{nick}）\n\n"
        "是否将其设为默认米米号？\n"
        "回复“是”或“y”确认，回复“否”或“n”跳过。\n"
        f"{quota_hint}"
        "设置后发送“米米号 / 收集 / 巅峰 / 群星牌”即可快捷查询。\n"
        "以后可发送“解绑米米号”解除绑定。"
    )
