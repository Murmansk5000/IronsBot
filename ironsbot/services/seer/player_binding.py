# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from typing import NamedTuple, Protocol

_BINDING_COMMAND_RE = re.compile(r"^(?:绑定米米号|更改米米号)(\d+)$")


class PlayerBindingState(NamedTuple):
    qq_user_id: int
    player_id: int | None = None
    player_nick: str = ""
    choice_completed: bool = False

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
    ) -> None: ...

    def decline(self, *, qq_user_id: int) -> None: ...

    def unbind(self, *, qq_user_id: int) -> bool: ...


def parse_player_binding_target(text: str) -> int | None:
    match = _BINDING_COMMAND_RE.fullmatch(text.strip())
    return int(match.group(1)) if match is not None else None


def player_binding_offer_message(player_id: int, nick: str) -> str:
    return (
        f"已查到米米号：{player_id}（{nick}）\n\n"
        "是否将其设为默认米米号？\n"
        "回复“是”或“y”确认，回复“否”或“n”跳过。\n"
        "设置后发送“米米号 / 收集 / 巅峰 / 群星牌”即可快捷查询。\n"
        "以后可发送“解绑米米号”解除绑定。"
    )
